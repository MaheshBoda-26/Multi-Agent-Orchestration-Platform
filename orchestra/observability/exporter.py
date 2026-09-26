import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

import asyncpg
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)


class PostgresSpanExporter(SpanExporter):
    """Custom exporter that writes spans to a Postgres JSONB table.

    OpenTelemetry's ``SpanExporter.export`` is synchronous (it is called from
    the batch processor's own thread), so the asyncpg writes run on a dedicated
    event loop owned by this exporter instead of being awaited in place.
    """

    def __init__(self, dsn: str, pool: Any = None):
        # asyncpg pools are bound to the loop that created them, so the
        # exporter must own a pool created inside its own loop. `pool` exists
        # only so unit tests can inject a fake; production passes a DSN.
        self.dsn = dsn
        self._pool: Optional[asyncpg.Pool] = pool
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="span-exporter", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        future = asyncio.run_coroutine_threadsafe(self._export(spans), self._loop)
        try:
            return future.result(timeout=30)
        except Exception:
            logger.exception("Failed to export %s spans to Postgres", len(spans))
            return SpanExportResult.FAILURE

    async def _export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            for span in spans:
                await self._insert_span(conn, span)
        return SpanExportResult.SUCCESS

    async def _get_pool(self) -> Any:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=2)
        return self._pool

    async def _insert_span(self, conn: asyncpg.Connection, span: ReadableSpan) -> None:
        attributes = dict(span.attributes) if span.attributes else {}
        events = [
            {
                "name": e.name,
                "timestamp": e.timestamp,
                "attributes": dict(e.attributes) if e.attributes else {},
            }
            for e in (span.events or [])
        ]

        start_ns = span.start_time
        end_ns = span.end_time
        if start_ns is None:
            raise ValueError("span has no start time")
        start_time = datetime.fromtimestamp(start_ns / 1e9, tz=timezone.utc)
        end_time = (
            datetime.fromtimestamp(end_ns / 1e9, tz=timezone.utc)
            if end_ns is not None
            else None
        )

        await conn.execute(
            """
            INSERT INTO spans (trace_id, span_id, parent_span_id, name, kind, status,
                             start_time, end_time, attributes, events, resource)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (trace_id, span_id) DO UPDATE SET
                parent_span_id = EXCLUDED.parent_span_id,
                name = EXCLUDED.name,
                kind = EXCLUDED.kind,
                status = EXCLUDED.status,
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                attributes = EXCLUDED.attributes,
                events = EXCLUDED.events,
                resource = EXCLUDED.resource
            """,
            format(span.context.trace_id, "032x"),
            format(span.context.span_id, "016x"),
            format(span.parent.span_id, "016x") if span.parent else None,
            span.name,
            span.kind.name if span.kind else None,
            span.status.status_code.name if span.status else None,
            start_time,
            end_time,
            json.dumps(attributes),
            json.dumps(events),
            json.dumps({"service": "orchestra"}),
        )

    def shutdown(self) -> None:
        if self._pool is not None and self.dsn:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._pool.close(), self._loop
                ).result(timeout=5)
            except Exception:
                logger.exception("Failed to close the span exporter pool")
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


# The spans table is owned by migrations/004_spans.sql; nothing creates it at
# runtime so the schema is versioned with every other table.
