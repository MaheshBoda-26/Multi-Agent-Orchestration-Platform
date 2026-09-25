from typing import Dict, Any, Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import Status, StatusCode

class TracingManager:
    """Manages OpenTelemetry tracing for the orchestra."""
    
    def __init__(self, service_name: str = "orchestra", otlp_endpoint: str = "http://localhost:4318/v1/traces"):
        self.provider = TracerProvider()
        self.exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        self.provider.add_span_processor(BatchSpanProcessor(self.exporter))
        trace.set_tracer_provider(self.provider)
        self.tracer = trace.get_tracer(service_name)

    def start_span(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """Start a new span with optional attributes."""
        span = self.tracer.start_span(name)
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        return span

    def record_error(self, span, error: Exception):
        span.set_status(Status(StatusCode.ERROR, str(error)))
        span.record_exception(error)
