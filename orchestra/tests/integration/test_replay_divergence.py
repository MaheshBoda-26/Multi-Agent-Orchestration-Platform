"""Replay-with-divergence proof (Task 41): a completed run's checkpoint is
loaded, one input is edited, the graph re-runs in a fresh thread, and the diff
shows which outputs moved - while the original checkpoint stays intact.

Requires Postgres + Redis reachable on localhost (compose services) and skips
otherwise. The FakeProvider makes divergence deterministic: editing
task_description changes the supervisor's plan input, so the replayed plan
differs from the original.
"""
import uuid

import asyncpg
import pytest

from graph.checkpointer import create_checkpointer
from graph.build import OrchestraGraph
from graph.replay import apply_edits, divergence_diff, replay_task
from llm.fake import FakeProvider
from worker.celery_app import celery_app
from worker.tasks import run_task

from .helpers import (
    DATABASE_URL,
    TEST_BROKER_URL,
    cleanup_task,
    postgres_available,
    redis_available,
    spawn_worker,
    stop_worker,
    wait_for_terminal,
    wait_for_worker,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_replay_shows_divergence_and_keeps_original(tmp_path):
    if not redis_available() or not await postgres_available():
        pytest.skip("Postgres and Redis are required for the replay test")
    celery_app.conf.broker_url = TEST_BROKER_URL

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    task_id = uuid.uuid4()
    worker = None
    ckpt_pool = None
    try:
        await pool.execute(
            "INSERT INTO tasks (id, request, status) VALUES ($1, $2, 'queued')",
            task_id, "replay divergence test",
        )

        # Complete a real run so a final checkpoint exists.
        worker = spawn_worker({}, tmp_path / "worker.log")
        assert wait_for_worker(tmp_path / "worker.log"), (
            "worker never came up:\n" + (tmp_path / "worker.log").read_text()
        )
        run_task.delay(str(task_id), "replay divergence test")
        status = await wait_for_terminal(pool, task_id)
        assert status == "completed", f"original run ended as {status!r}"

        ckpt_pool, checkpointer = await create_checkpointer(DATABASE_URL)
        graph = OrchestraGraph(FakeProvider(), checkpointer=checkpointer)
        thread_id = str(task_id)

        original_snapshot = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id}}
        )
        assert original_snapshot is not None
        original_state = (
            getattr(original_snapshot, "state", None)
            or getattr(original_snapshot, "values", None)
        )
        assert original_state.get("final_response")

        # Edit one input and replay into a fresh thread.
        result = await replay_task(
            checkpointer,
            graph.workflow,
            thread_id,
            {"task_description": "replay divergence test (edited)"},
        )
        assert result["edited_fields"] == ["task_description"]
        assert result["changed"], "editing the task description must move the plan"
        assert "plan" in result["changed_fields"]
        assert result["diffs"]["plan"]["original"] != result["diffs"]["plan"]["replayed"]

        # The original checkpoint is untouched by the replay.
        after = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id}}
        )
        after_state = (
            getattr(after, "state", None) or getattr(after, "values", None)
        )
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
        assert not same["changed"], "a replay with no edits must not diverge"

        # Unknown fields are rejected loudly.
        with pytest.raises(KeyError):
            apply_edits(dict(original_state), {"not_a_field": 1})

        # divergence_diff is pure and shape-stable.
        diff = divergence_diff(original_state, dict(original_state))
        assert diff == {"changed": False, "changed_fields": [], "diffs": {}}
    finally:
        stop_worker(worker)
        if ckpt_pool is not None:
            await ckpt_pool.close()
        await cleanup_task(pool, task_id)
        await pool.close()
