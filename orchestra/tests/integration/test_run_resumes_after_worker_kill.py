"""Durability proof: SIGKILL a worker mid-run, restart it, and verify the run
resumes from the last checkpoint without repeating completed steps.

Requires Postgres + Redis reachable on localhost (compose services) and skips
otherwise. The FakeProvider hooks (FAKE_COMPLETION_LOG, FAKE_KILL_AFTER_CALLS)
make the crash deterministic: the worker kills itself during the reviewer call
for the first subtask, after that subtask's execute super-step was checkpointed.
"""
import signal
import uuid

import asyncpg
import pytest

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

FIRST_SUBTASK = "Task: Gather information for the request"
SECOND_SUBTASK = "Task: Write up the final answer"

# FakeProvider calls in order: 1 supervisor plan, 2 first specialist,
# 3 first reviewer -> kill here, after the first execute super-step checkpointed.
KILL_AFTER_CALLS = 3


@pytest.mark.asyncio
async def test_run_resumes_after_worker_kill(tmp_path):
    if not redis_available() or not await postgres_available():
        pytest.skip("Postgres and Redis are required for the durability test")
    celery_app.conf.broker_url = TEST_BROKER_URL

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    task_id = uuid.uuid4()
    log_path = tmp_path / "fake-calls.log"
    first_worker = None
    second_worker = None

    try:
        await pool.execute(
            "INSERT INTO tasks (id, request, status) VALUES ($1, $2, 'queued')",
            task_id, "durability test task",
        )

        # --- attempt 1: worker crashes during the first review ---
        first_log = tmp_path / "worker-1.log"
        first_worker = spawn_worker({
            "FAKE_COMPLETION_LOG": str(log_path),
            "FAKE_KILL_AFTER_CALLS": str(KILL_AFTER_CALLS),
        }, first_log)
        assert wait_for_worker(first_log), (
            "first worker never came up:\n" + first_log.read_text()
        )
        run_task.delay(str(task_id), "durability test task")

        first_worker.wait(timeout=60)
        assert first_worker.returncode == -signal.SIGKILL, (
            f"worker should have been SIGKILLed, got {first_worker.returncode}"
        )

        # --- attempt 2: fresh worker resumes from the checkpoint ---
        second_log = tmp_path / "worker-2.log"
        second_worker = spawn_worker({"FAKE_COMPLETION_LOG": str(log_path)}, second_log)
        assert wait_for_worker(second_log), (
            "second worker never came up:\n" + second_log.read_text()
        )
        run_task.delay(str(task_id), "durability test task")

        status = await wait_for_terminal(pool, task_id)
        assert status == "completed", f"task ended as {status!r}"

        # No repeated completed steps: each subtask line appears exactly once.
        lines = [line.strip() for line in log_path.read_text().splitlines()]
        assert lines.count(FIRST_SUBTASK) == 1, (
            "the first subtask ran again after resume:\n" + "\n".join(lines)
        )
        assert lines.count(SECOND_SUBTASK) == 1

        run = await pool.fetchrow(
            "SELECT status, completed_at, latency_ms FROM run_metadata WHERE task_id = $1",
            task_id,
        )
        assert run is not None, "run_metadata row missing"
        assert run["status"] == "completed"
        assert run["completed_at"] is not None
        assert run["latency_ms"] >= 0

        result = await pool.fetchrow("SELECT result FROM tasks WHERE id = $1", task_id)
        assert result["result"] is not None
    finally:
        stop_worker(second_worker)
        stop_worker(first_worker)
        await cleanup_task(pool, task_id)
        await pool.close()
