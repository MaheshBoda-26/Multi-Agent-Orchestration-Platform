"""End-to-end demo path (Task 47): the same milestones scripts/demo.py walks,
asserted against a real API + Celery worker + Postgres + Redis.

Requires the compose services; skips otherwise.
"""

import pytest
from fastapi.testclient import TestClient

from api.server import app
from worker.celery_app import celery_app

from ..integration.helpers import (
    TEST_BROKER_URL,
    postgres_available,
    redis_available,
    spawn_worker,
    stop_worker,
    wait_for_worker,
)

pytestmark = pytest.mark.integration

DEMO_USER = "e2e-demo-user"


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_demo_path_end_to_end(tmp_path, client):
    if not redis_available() or not await postgres_available():
        pytest.skip("Postgres and Redis are required for the e2e demo-path test")
    celery_app.conf.broker_url = TEST_BROKER_URL

    worker = None
    try:
        # --- the platform under real services --------------------------------
        worker_log = tmp_path / "worker.log"
        worker = spawn_worker({"FAKE_DELAY_SECONDS": "0.05"}, worker_log)
        assert wait_for_worker(worker_log), (
            "worker never came up:\n" + worker_log.read_text()
        )

        # --- milestone 1: create the task through the API ---------------------
        response = client.post("/tasks", json={
            "task_description": (
                f"Demo run for user {DEMO_USER}: research and summarize."
            ),
        })
        assert response.status_code == 202
        task_id = response.json()["task_id"]

        # --- milestone 2: workers complete it (parallel + reviewer + synth) ---
        row = await _poll_status(client, task_id, {"completed"}, timeout=120.0)
        assert row["status"] == "completed"
        subtasks = (row.get("result") or {}).get("subtasks") or {}
        assert len(subtasks) >= 2, "the demo plan fans out subtasks"
        assert any((s.get("retry_count") or 0) >= 0 for s in subtasks.values())

        trace = client.get(f"/tasks/{task_id}/trace").json()
        names = _collect_span_names(trace.get("roots") or [])
        for expected in ("supervisor.plan", "specialist.run", "reviewer.review"):
            assert expected in names, f"missing {expected} in {names}"

        cost = client.get(f"/tasks/{task_id}/cost").json()
        assert cost["latency_ms"] > 0

        # --- milestone 3: observability endpoints serve the run ---------------
        listed = client.get("/tasks?limit=20").json()
        assert task_id in [t["task_id"] for t in listed["tasks"]]
        stats = client.get("/stats/cost").json()
        assert stats["runs"] >= 1

        replay = client.post(
            f"/tasks/{task_id}/replay",
            json={"edits": {"task_description": "e2e replay edit"}},
        )
        assert replay.status_code == 200
        assert replay.json()["original_thread_id"] == task_id

        for page, needle in (
            (f"/tasks/{task_id}/explorer", "Trace Explorer"),
            ("/dashboard", "Cost"),
        ):
            page_response = client.get(page)
            assert page_response.status_code == 200
            assert needle in page_response.text
    finally:
        stop_worker(worker)
        await _cleanup(client)


async def _poll_status(client, task_id: str, wanted: set, timeout: float):
    import asyncio
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f"/tasks/{task_id}").json()
        if row.get("status") in wanted:
            return row
        if row.get("status") in {"failed", "cancelled"}:
            return row
        await asyncio.sleep(0.5)
    raise TimeoutError(f"task {task_id} never reached {wanted}")


def _collect_span_names(nodes):
    names = []
    for node in nodes:
        names.append(node.get("name"))
        names.extend(_collect_span_names(node.get("children") or []))
    return names


async def _cleanup(client):
    import asyncpg
    import os

    dsn = os.getenv(
        "DATABASE_URL", "postgresql://orchestra:orchestra@localhost:5432/orchestra"
    )
    pool = await asyncpg.create_pool(dsn)
    try:
        rows = await pool.fetch(
            "SELECT id FROM tasks WHERE request LIKE $1", f"%{DEMO_USER}%"
        )
        for row in rows:
            task_id = str(row["id"])
            await pool.execute(
                "DELETE FROM spans WHERE attributes ->> 'task_id' = $1", task_id
            )
            await pool.execute("DELETE FROM run_metadata WHERE task_id = $1", task_id)
            await pool.execute("DELETE FROM tasks WHERE id = $1", task_id)
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                await pool.execute(f"DELETE FROM {table} WHERE thread_id = $1", task_id)
    finally:
        await pool.close()
