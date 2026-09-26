"""Task-scoped context so every span can carry its task_id automatically.

The worker sets the current task id once; span() reads it when building
attributes, which lets /tasks/{id}/trace find every span of a run by task.
"""
import contextvars
from typing import Optional

_current_task_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "orchestra_task_id", default=None
)


def set_current_task_id(task_id: Optional[str]) -> None:
    _current_task_id.set(task_id)


def get_current_task_id() -> Optional[str]:
    return _current_task_id.get()
