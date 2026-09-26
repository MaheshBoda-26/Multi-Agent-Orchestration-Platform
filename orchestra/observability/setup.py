"""Configure OpenTelemetry to export spans into Postgres (locked decision D6).

No OTLP exporter anywhere in app code: the custom Postgres exporter is the only
span sink, so the trace explorer and replay can query spans directly.
"""
import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from observability.exporter import PostgresSpanExporter

logger = logging.getLogger(__name__)

_provider: Optional[TracerProvider] = None


def configure_tracing(dsn: str) -> TracerProvider:
    """Install the Postgres span exporter exactly once per process.

    Takes a DSN, not the app pool: the exporter runs on its own event loop and
    owns a pool created there.
    """
    global _provider
    if _provider is not None:
        return _provider

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(PostgresSpanExporter(dsn)))
    trace.set_tracer_provider(provider)
    _provider = provider
    logger.info("Tracing configured with the Postgres span exporter")
    return provider


def flush_tracing() -> None:
    """Flush buffered spans; call before marking a run complete."""
    global _provider
    if _provider is not None:
        # BatchSpanProcessor flushes on its own thread; give it a moment to
        # write through before the run is marked complete.
        _provider.force_flush(timeout_millis=30000)


def _reset_for_tests() -> None:
    global _provider
    _provider = None
