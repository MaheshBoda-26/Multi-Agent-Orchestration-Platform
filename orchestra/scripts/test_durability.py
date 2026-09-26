"""Crash-recovery doctor: kill a worker mid-run N times and verify resume.

Each run: start a worker that SIGKILLs itself during the first review call,
start a fresh worker, re-enqueue the same task, and assert every subtask ran
exactly once before the task completed.

Usage: .venv/bin/python scripts/test_durability.py [runs]   (default 20)
Requires Postgres + Redis on localhost.
"""
import asyncio
import signal
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

from tests.integration.helpers import (  # noqa: E402
    DATABASE_URL,
    TEST_BROKER_URL,
    cleanup_task,
    spawn_worker,
    stop_worker,
    wait_for_terminal,
    wait_for_worker,
)
from worker.celery_app import celery_app  # noqa: E402
from worker.tasks import run_task  # noqa: E402

FIRST_SUBTASK = "Task: Gather information for the request"
SECOND_SUBTASK = "Task: Write up the final answer"
KILL_AFTER_CALLS = 3


async def run_once(pool: asyncpg.Pool, workdir: Path, run_number: int) -> None:
    task_id = uuid.uuid4()
    log_path = workdir / f"calls-{run_number}.log"
    first_log = workdir / f"worker-{run_number}-a.log"
    second_log = workdir / f"worker-{run_number}-b.log"

    await pool.execute(
        "INSERT INTO tasks (id, request, status) VALUES ($1, $2, 'queued')",
        task_id, f"durability doctor run {run_number}",
    )
    first = second = None
    try:
        first = spawn_worker({
            "FAKE_COMPLETION_LOG": str(log_path),
            "FAKE_KILL_AFTER_CALLS": str(KILL_AFTER_CALLS),
        }, first_log)
        if not wait_for_worker(first_log):
            raise AssertionError("worker A never came up")
        run_task.delay(str(task_id), f"durability doctor run {run_number}")
        first.wait(timeout=60)
        if first.returncode != -signal.SIGKILL:
            raise AssertionError(f"worker A exit code {first.returncode}, expected SIGKILL")

        second = spawn_worker({"FAKE_COMPLETION_LOG": str(log_path)}, second_log)
        if not wait_for_worker(second_log):
            raise AssertionError("worker B never came up")
        run_task.delay(str(task_id), f"durability doctor run {run_number}")

        status = await wait_for_terminal(pool, task_id)
        if status != "completed":
            raise AssertionError(f"task ended as {status!r}")

        lines = [line.strip() for line in log_path.read_text().splitlines()]
        if lines.count(FIRST_SUBTASK) != 1 or lines.count(SECOND_SUBTASK) != 1:
            raise AssertionError("completed steps were repeated after resume")
    finally:
        stop_worker(second)
        stop_worker(first)
        await cleanup_task(pool, task_id)


async def main(runs: int) -> int:
    celery_app.conf.broker_url = TEST_BROKER_URL
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    passed = 0
    try:
        with tempfile.TemporaryDirectory(prefix="orchestra-durability-") as tmp:
            workdir = Path(tmp)
            for number in range(1, runs + 1):
                try:
                    await run_once(pool, workdir, number)
                except Exception as exc:
                    print(f"run {number:02d}: FAIL  ({exc})")
                else:
                    passed += 1
                    print(f"run {number:02d}: pass")
    finally:
        await pool.close()
    print(f"\nresume success rate: {passed}/{runs}")
    return 0 if passed == runs else 1


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    raise SystemExit(asyncio.run(main(count)))
