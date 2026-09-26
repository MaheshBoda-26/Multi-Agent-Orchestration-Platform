"""Replay a run from its checkpoint with an edited input (Task 41).

Divergence analysis: load the final checkpointed state of a completed run,
change one or more inputs (task description, user id, shared context), then
re-invoke the graph into a *fresh* checkpointer thread and diff the outcome
against the original. The original checkpoint is never touched, so a replay is
always a read-only experiment.

Semantics: the replay re-executes the graph from its entry node with the edited
inputs, exactly like a fresh run of the edited request would go. Edits to
``task_description``/``user_id`` therefore flow through planning and memory;
editing ``plan``/``results``/``final_response`` only moves the outcome if the
run honors the provided state. This is the "what would have happened if" tool.
"""
import logging
import uuid
from typing import Any, Dict

logger = logging.getLogger(__name__)

# State fields the divergence diff compares. plan/results/final_response are
# the outputs a replay is supposed to move; everything else is plumbing.
_DIFF_FIELDS = ("plan", "results", "final_response")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def load_checkpoint_values(snapshot: Any) -> Dict[str, Any]:
    """Extract channel values from a CheckpointTuple (version-tolerant).

    This langgraph version exposes the deserialized state only as
    ``snapshot.checkpoint["channel_values"]``; newer versions may hang it off
    ``state``/``values`` directly, so both shapes are accepted.
    """
    state = getattr(snapshot, "state", None) or getattr(snapshot, "values", None)
    if isinstance(state, dict) and state:
        return dict(state)
    checkpoint = getattr(snapshot, "checkpoint", None) or {}
    values = checkpoint.get("channel_values") if hasattr(checkpoint, "get") else None
    if not isinstance(values, dict):
        raise LookupError("Checkpoint carries no channel values")
    # Internal LangGraph channels (e.g. __pregel_tasks) are plumbing, not state.
    return {key: value for key, value in values.items() if not key.startswith("__")}


def apply_edits(state: Dict[str, Any], edits: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of the checkpoint state with inputs replaced."""
    edited = dict(state)
    for field, value in edits.items():
        if field not in state:
            raise KeyError(
                f"Cannot edit unknown state field {field!r}. "
                f"Editable fields: {sorted(set(_DIFF_FIELDS) | {'task_description', 'shared_context', 'user_id'})}"
            )
        edited[field] = value
    return edited


def divergence_diff(
    original_state: Dict[str, Any], replayed_state: Dict[str, Any]
) -> Dict[str, Any]:
    """Which output fields moved between the original and replayed runs?"""
    diffs: Dict[str, Any] = {}
    for field in _DIFF_FIELDS:
        before = _jsonable(original_state.get(field))
        after = _jsonable(replayed_state.get(field))
        if before != after:
            diffs[field] = {"original": before, "replayed": after}
    return {
        "changed": bool(diffs),
        "changed_fields": sorted(diffs),
        "diffs": diffs,
    }


async def replay_task(
    checkpointer: Any,
    workflow: Any,
    thread_id: str,
    edits: Dict[str, Any],
) -> Dict[str, Any]:
    """Replay one run with edited inputs; returns the divergence diff.

    The replay runs in a new checkpointer thread seeded with the edited state,
    so the source run's checkpoints stay intact and re-runnable.
    """
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await checkpointer.aget_tuple(config)
    if snapshot is None:
        raise LookupError(f"No checkpoint exists for task {thread_id}")
    original_state = load_checkpoint_values(snapshot)

    edited_state = apply_edits(original_state, edits)
    replay_thread = f"replay-{uuid.uuid4()}"
    replay_config = {"configurable": {"thread_id": replay_thread}}
    logger.info(
        "Replaying task %s with edited %s into thread %s",
        thread_id, sorted(edits), replay_thread,
    )
    replayed_state = await workflow.ainvoke(
        edited_state, replay_config, durability="sync"
    )

    result = {
        "original_thread_id": thread_id,
        "replay_thread_id": replay_thread,
        "edited_fields": sorted(edits),
        "edited_inputs": edits,
        **divergence_diff(original_state, replayed_state),
    }
    logger.info(
        "Replay of %s diverged in %s", thread_id, result["changed_fields"]
    )
    return result
