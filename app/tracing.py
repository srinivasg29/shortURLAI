from __future__ import annotations

from functools import lru_cache

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Tracer


@lru_cache
def _provider() -> TracerProvider:
    """A ConsoleSpanExporter by default - dependency-free and inspectable
    without standing up a collector, which fits a prototype. Swapping to an
    OTLP exporter for a real deployment is a one-line change here; nothing
    else in the codebase needs to know about it, since callers only ever
    go through get_tracer()."""
    provider = TracerProvider(
        resource=Resource.create({"service.name": "agentic-url-shortener"})
    )
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider


def get_tracer(name: str) -> Tracer:
    _provider()
    return trace.get_tracer(name)
