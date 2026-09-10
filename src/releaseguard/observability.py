"""Vendor-neutral tracing configuration."""

from threading import Lock

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExporter
from opentelemetry.trace import Tracer

from releaseguard import __version__
from releaseguard.config import Settings

_configuration_lock = Lock()
_configured = False


def configure_tracing(settings: Settings) -> Tracer:
    """Configure one process-wide provider and return the application tracer."""
    global _configured

    if settings.trace_exporter == "none":
        return trace.get_tracer("releaseguard", __version__)

    with _configuration_lock:
        if not _configured:
            resource = Resource.create(
                {
                    SERVICE_NAME: "releaseguard",
                    SERVICE_VERSION: __version__,
                    "deployment.environment.name": settings.environment,
                }
            )
            provider = TracerProvider(resource=resource)
            exporter: SpanExporter
            if settings.trace_exporter == "console":
                exporter = ConsoleSpanExporter()
            else:
                exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            _configured = True
    return trace.get_tracer("releaseguard", __version__)
