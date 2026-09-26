from opentelemetry.sdk.trace.export import SpanExportResult

from observability import setup


def test_configure_tracing_is_idempotent(monkeypatch):
    setup._reset_for_tests()
    created = []

    class StubExporter:
        def __init__(self, dsn, pool=None):
            created.append(dsn)

        def export(self, spans):
            return SpanExportResult.SUCCESS

        def shutdown(self):
            pass

        def force_flush(self, timeout_millis=30000):
            return True

    monkeypatch.setattr(setup, "PostgresSpanExporter", StubExporter)

    first = setup.configure_tracing("postgresql://test")
    second = setup.configure_tracing("postgresql://other")

    assert first is second
    assert len(created) == 1, "the exporter must be installed exactly once"
    setup._reset_for_tests()
