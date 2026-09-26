"""Replay-with-divergence proof (Task 41): a completed run's checkpoint is
loaded, one input is edited, the graph re-runs in a fresh thread, and the diff
shows which outputs moved - while the original checkpoint stays intact.

Requires Postgres reachable on localhost (compose service) and skips
otherwise; the replay itself never involves the worker or broker. The
description-sensitive fake planner makes divergence deterministic: editing
task_description changes the supervisor's plan input, so the replayed plan
differs from the original, while a no-edit replay is bit-identical.
"""
import json
import uuid

import asyncpg
import pytest

from agents.supervisor import Plan, Subtask
from graph.checkpointer import create_checkpointer
from graph.build import OrchestraGraph
from graph.replay import (
    apply_edits,
    divergence_diff,
    load_checkpoint_values,
    replay_task,
)
from llm.fake import FakeProvider

from .helpers import DATABASE_URL, postgres_available

pytestmark = pytest.mark.integration

ORIGINAL_DESCRIPTION = "replay divergence test"
EDITED_DESCRIPTION = "replay divergence test (edited)"


class DescriptionSensitiveProvider(FakeProvider):
    """Plans echo the task description, so an edited description changes the
    plan deterministically - modelling "a different ask plans differently"."""

    async def complete_structured(self, prompt, response_model, **kwargs):
        if "Orchestra Supervisor" in prompt:
            line = next(
                (ln for ln in prompt.splitlines() if ln.startswith("Task: ")), "Task:"
            )
            description = line.removeprefix("Task: ").strip()
            return Plan(
                tasks=[Subtask(
                    id="t1",
                    description=f"Handle: {description}",
                    specialist="researcher",
                    dependencies=[],
                )],
                reasoning=f"Single-step plan for: {description}",
                confidence=0.9,
            )
        return await super().complete_structured(prompt, response_model, **kwargs)


def _initial_state(task_id: str, description: str) -> dict:
    return {
        "task_id": task_id,
        "task_description": description,
        "plan": None,
        "results": {},
        "attempts": {},
        "review_feedback": {},
        "shared_context": "",
        "final_response": None,
    }


@pytest.mark.asyncio
async def test_replay_shows_divergence_and_keeps_original():
    if not await postgres_available():
        pytest.skip("Postgres is required for the replay test")

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    ckpt_pool = None
    replay_thread_ids: list[str] = []
    try:
        ckpt_pool, checkpointer = await create_checkpointer(DATABASE_URL)
        provider = DescriptionSensitiveProvider()
        graph = OrchestraGraph(provider, checkpointer=checkpointer)

        # Complete a real run so a final checkpoint exists (in-process; the
        # worker path is covered by the durability tests).
        thread_id = str(uuid.uuid4())
        await graph.workflow.ainvoke(
            _initial_state(thread_id, ORIGINAL_DESCRIPTION),
            {"configurable": {"thread_id": thread_id}},
            durability="sync",
        )
        snapshot = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id}}
        )
        assert snapshot is not None
        original_state = load_checkpoint_values(snapshot)
        assert original_state.get("final_response")
        original_plan = json.dumps(original_state.get("plan"), default=str)
        assert ORIGINAL_DESCRIPTION in original_plan

        # Edit one input and replay into a fresh thread.
        result = await replay_task(
            checkpointer,
            graph.workflow,
            thread_id,
            {"task_description": EDITED_DESCRIPTION},
        )
        replay_thread_ids.append(result["replay_thread_id"])
        assert result["edited_fields"] == ["task_description"]
        assert result["changed"], "editing the task description must move the plan"
        assert "plan" in result["changed_fields"]
        replayed_plan = json.dumps(result["diffs"]["plan"]["replayed"], default=str)
        assert EDITED_DESCRIPTION in replayed_plan

        # The original checkpoint is untouched by the replay.
        after = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id}}
        )
        assert after is not None
        after_state = load_checkpoint_values(after)
        assert after_state.get("final_response") == original_state.get("final_response")
        assert after_state.get("task_description") == original_state.get(
            "task_description"
        )

        # The replay is itself checkpointed in its own thread.
        replay_snapshot = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": result["replay_thread_id"]}}
        )
        assert replay_snapshot is not None

        # No-edit replay: identical inputs, identical outputs.
        same = await replay_task(checkpointer, graph.workflow, thread_id, {})
        replay_thread_ids.append(same["replay_thread_id"])
        assert not same["changed"], "a replay with no edits must not diverge"

        # Unknown fields are rejected loudly.
        with pytest.raises(KeyError):
            apply_edits(dict(original_state), {"not_a_field": 1})

        # divergence_diff is pure and shape-stable.
        diff = divergence_diff(original_state, dict(original_state))
        assert diff == {"changed": False, "changed_fields": [], "diffs": {}}
    finally:
        if ckpt_pool is not None:
            await ckpt_pool.close()
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            await pool.execute(f"DELETE FROM {table} WHERE thread_id = ANY($1)",
                               replay_thread_ids)
        await pool.close()
