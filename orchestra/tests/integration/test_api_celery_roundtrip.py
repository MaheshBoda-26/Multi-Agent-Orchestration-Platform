"""API roundtrip: POST /tasks enqueues on Celery, the worker runs the graph,
the DB row completes, and SSE reports status then done.

Requires Postgres + Redis (compose services); skips otherwise.
"""
import asyncio
import time
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient

from api.server import app
from worker.celery_app import celery_app

from .helpers import (
    DATABASE_URL,
    TEST_BROKER_URL,
    cleanup_task,
    postgres_available,
    redis_available,
    spawn_worker,
    stop_worker,
    wait_for_worker,
)

pytestmark = pytest.mark.integration


async def _cleanup(task_id: uuid.UUID) -> None:
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    try:
        await cleanup_task(pool, task_id)
    finally:
        await pool.close()


def test_api_roundtrip_completes_task(tmp_path):
    if not redis_available() or not asyncio.run(postgres_available()):
        pytest.skip("Postgres and Redis are required for the roundtrip test")
    celery_app.conf.broker_url = TEST_BROKER_URL

    worker_log = tmp_path / "worker.log"
    worker = spawn_worker({"FAKE_COMPLETION_LOG": str(tmp_path / "calls.log")}, worker_log)
    assert wait_for_worker(worker_log), (
        "worker never came up:\n" + worker_log.read_text()
    )

    task_id = None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/tasks", json={"task_description": "roundtrip test task"}
            )
            assert response.status_code == 202, response.text
            task_id = uuid.UUID(response.json()["task_id"])
            assert response.json()["status"] == "queued"

            deadline = time.time() + 60
            body = {}
            while time.time() < deadline:
                body = client.get(f"/tasks/{task_id}").json()
                if body["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.5)

            assert body["status"] == "completed", body
            assert body["result"]["final_response"]

            # SSE reports the terminal state and then closes with `done`.
            with client.stream("GET", f"/tasks/{task_id}/events") as stream:
                assert stream.status_code == 200
                chunks = []
                for line in stream.iter_lines():
                    chunks.append(line)
                    if any("event: done" in c for c in chunks):
                        break
                    if len(chunks) > 40:
                        break
            assert any("event: done" in c for c in chunks), chunks
    finally:
        stop_worker(worker)
        if task_id is not None:
            asyncio.run(_cleanup(task_id))
