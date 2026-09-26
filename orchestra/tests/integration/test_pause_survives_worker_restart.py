"""HITL durability proof: a task pauses for plan approval, the worker is
SIGKILLed, a brand-new worker comes up, the human approves, and the run
completes from the checkpoint -- with the plan generated exactly once.

Requires Postgres + Redis reachable on localhost (compose services) and skips
otherwise. FAKE_PLAN_PATH scripts a low-confidence plan so the graph pauses at
the plan_approval gate before any specialist runs.
"""
import json
import uuid

import asyncpg
import pytest

from worker.celery_app import celery_app
from worker.tasks import resume_task, run_task

from .helpers import (
    DATABASE_URL,
    TEST_BROKER_URL,
    cleanup_task,
    postgres_available,
    redis_available,
    spawn_worker,
    stop_worker,
    wait_for_status,
    wait_for_terminal,
    wait_for_worker,
)

pytestmark = pytest.mark.integration

SUPERVISOR_CALL = "Orchestra Supervisor"


@pytest.mark.asyncio
async def test_pause_survives_worker_restart(tmp_path):
    if not redis_available() or not await postgres_available():
        pytest.skip("Postgres and Redis are required for the HITL durability test")
    celery_app.conf.broker_url = TEST_BROKER_URL

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    task_id = uuid.uuid4()
    low_confidence_plan = json.dumps({
        "tasks": [
            {
                "id": "t1",
                "description": "Gather information for the request",
                "specialist": "researcher",
                "dependencies": [],
            },
        ],
        "reasoning": "Uncertain plan awaiting approval.",
        "confidence": 0.2,
    })
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(low_confidence_plan, encoding="utf-8")

    first_worker = None
    second_worker = None
    try:
        await pool.execute(
            "INSERT INTO tasks (id, request, status) VALUES ($1, $2, 'queued')",
            task_id, "HITL pause durability test",
        )

        # --- attempt 1: run until the plan-approval pause, then kill ---
        first_log = tmp_path / "worker-1.log"
        first_worker = spawn_worker(
            {"FAKE_PLAN_PATH": str(plan_path)}, first_log
        )
        assert wait_for_worker(first_log), (
            "first worker never came up:\n" + first_log.read_text()
        )
        run_task.delay(str(task_id), "HITL pause durability test")

        paused = await wait_for_status(pool, task_id, "awaiting_human")
        assert paused, "task never paused for plan approval"

        approvals = await pool.fetch(
            "SELECT id, trigger, status FROM approvals WHERE task_id = $1 "
            "ORDER BY created_at ASC",
            str(task_id),
        )
        assert approvals, "paused task must persist an approvals row"
        assert approvals[0]["trigger"] == "low_confidence_plan"
        assert approvals[0]["status"] == "pending"
        approval_id = approvals[0]["id"]

        # --- kill the paused worker and start a fresh one ---
        first_worker.send_signal(__import__("signal").SIGKILL)
        first_worker.wait(timeout=10)

        second_log = tmp_path / "worker-2.log"
        second_worker = spawn_worker({}, second_log)
        assert wait_for_worker(second_log), (
            "second worker never came up:\n" + second_log.read_text()
        )

        # --- the human decides on the fresh worker's watch ---
        await pool.execute(
            "UPDATE approvals SET status = 'approve', resolution = $2, "
            "resolved_at = NOW() WHERE id = $1",
            approval_id,
            json.dumps({"action": "approve"}),
        )
        resume_task.delay(str(task_id), approval_id)

        status = await wait_for_terminal(pool, task_id)
        assert status == "completed", f"task ended as {status!r}"

        # The plan was generated exactly once: the resume must not re-plan.
        supervisor_calls = await pool.fetchval(
            """
            SELECT COUNT(*) FROM spans
            WHERE name = 'supervisor.plan'
              AND attributes ->> 'task_id' = $1
            """,
            str(task_id),
        )
        assert supervisor_calls == 1, (
            f"supervisor re-planned after resume ({supervisor_calls} times)"
        )

        result = await pool.fetchrow(
            "SELECT status, result FROM tasks WHERE id = $1", task_id
        )
        assert result["result"] is not None
    finally:
        stop_worker(second_worker)
        stop_worker(first_worker)
        await pool.execute("DELETE FROM approvals WHERE task_id = $1", str(task_id))
        await cleanup_task(pool, task_id)
        await pool.close()
