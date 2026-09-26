"""Plan validation: reject a plan before it reaches the scheduler.

Runs before any subtask is sent so the graph never has to handle a dependency
cycle or an unknown specialist at execution time. Rules per TRD section 4:
no cycles, every dependency exists, every specialist is whitelisted, at most
12 subtasks, and every subtask has a non-empty description.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence

SPECIALIST_WHITELIST = {"researcher", "data_analyst", "writer", "code_executor"}
MAX_SUBTASKS = 12


def _cycles(tasks: Sequence[Dict[str, Any]]) -> List[str]:
    """Return a human-readable list of dependency cycles (Kahn's algorithm)."""
    ids: List[str] = [str(t.get("id") or "") for t in tasks]
    deps: Dict[str, set] = {
        str(t.get("id") or ""): {str(d) for d in (t.get("dependencies") or [])}
        for t in tasks
    }

    resolved: set = set()
    remaining: set = set(ids)
    while remaining:
        ready = {i for i in remaining if deps[i] <= resolved}
        if not ready:
            return sorted(remaining)
        resolved |= ready
        remaining -= ready
    return []


def validate_plan(
    tasks: Sequence[Dict[str, Any]],
    specialist_whitelist: Iterable[str] = SPECIALIST_WHITELIST,
    max_subtasks: int = MAX_SUBTASKS,
) -> List[str]:
    """Return validation errors for a plan; an empty list means the plan is valid."""
    errors: List[str] = []
    if not tasks:
        return ["plan contains no subtasks"]
    if len(tasks) > max_subtasks:
        errors.append(f"plan has {len(tasks)} subtasks, limit is {max_subtasks}")

    ids = [t.get("id") for t in tasks]
    if any(not i for i in ids):
        errors.append("every subtask needs a non-empty id")
    if len(set(ids)) != len(ids):
        errors.append("subtask ids must be unique")

    known = {i for i in ids}
    whitelist = set(specialist_whitelist)

    for task in tasks:
        task_id = task.get("id")
        if not str(task.get("description") or "").strip():
            errors.append(f"subtask {task_id} has no description")
        if task.get("specialist") not in whitelist:
            errors.append(
                f"subtask {task_id} uses unknown specialist {task.get('specialist')!r}"
            )
        for dep in task.get("dependencies") or []:
            if dep == task_id:
                errors.append(f"subtask {task_id} depends on itself")
            elif dep not in known:
                errors.append(f"subtask {task_id} depends on unknown subtask {dep!r}")

    if not errors:
        stuck = _cycles(tasks)
        if stuck:
            errors.append(f"dependency cycle between subtasks: {', '.join(stuck)}")

    return errors
