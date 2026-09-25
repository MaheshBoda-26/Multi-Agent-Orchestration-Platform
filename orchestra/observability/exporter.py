import asyncio
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncpg
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace import ReadableSpan

class PostgresSpanExporter(SpanExporter):
    """Custom exporter that writes spans to a Postgres JSONB table."""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def export(self, spans: List[ReadableSpan]) -> SpanExportResult:
        try:
            async with self.pool.acquire() as conn:
                for span in spans:
                    await self._insert_span(conn, span)
            return SpanExportResult.SUCCESS
        except Exception as e:
            print(f"Failed to export spans to Postgres: {e}")
            return SpanExportResult.FAILURE

    async def _insert_span(self, conn: asyncpg.Connection, span: ReadableSpan):
        attributes = dict(span.attributes) if span.attributes else {}
        events = [
            {
                "name": e.name,
                "timestamp": e.timestamp,
                "attributes": dict(e.attributes) if e.attributes else {}
            }
            for e in (span.events or [])
        ]
        
        await conn.execute("""
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
            str(span.context.trace_id),
            str(span.context.span_id),
            str(span.parent.span_id) if span.parent else None,
            span.name,
            str(span.kind),
            str(span.status.status_code),
            datetime.fromtimestamp(span.start_time / 1e9),
            datetime.fromtimestamp(span.end_time / 1e9) if span.end_time else None,
            json.dumps(attributes),
            json.dumps(events),
            json.dumps({"service": "orchestra"})
        )

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

async def init_span_table(pool: asyncpg.Pool):
    """Initialize the spans table in Postgres."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS spans (
                trace_id VARCHAR(32) NOT NULL,
                span_id VARCHAR(16) NOT NULL,
                parent_span_id VARCHAR(16),
                name VARCHAR(255),
                kind VARCHAR(50),
                status VARCHAR(50),
                start_time TIMESTAMP WITH TIME ZONE,
                end_time TIMESTAMP WITH TIME ZONE,
                attributes JSONB,
                events JSONB,
                resource JSONB,
                PRIMARY KEY (trace_id, span_id)
            );
            CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
        """)
