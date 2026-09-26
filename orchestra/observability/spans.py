"""Small span helper used across the graph and tools.

Every span automatically carries the current task_id (see context.py), so the
trace endpoint can find a whole run's spans without threading the id through
every call.
"""
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.trace import Span

from observability.context import get_current_task_id

_TRACER_NAME = "orchestra"


def _clean(attributes: dict) -> dict:
    return {k: v for k, v in attributes.items() if v is not None}


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Span]:
    tracer = trace.get_tracer(_TRACER_NAME)
    attrs = {"task_id": get_current_task_id(), **attributes}
    with tracer.start_as_current_span(name) as current:
        for key, value in _clean(attrs).items():
            current.set_attribute(key, value)
        yield current


def record_span_attributes(current: Span, **attributes: Any) -> None:
    for key, value in _clean(attributes).items():
        current.set_attribute(key, value)
