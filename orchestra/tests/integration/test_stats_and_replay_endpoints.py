"""Phase 8 endpoints over real data: task list, stats rollup, replay.

Requires Postgres; skips otherwise. Runs one real task in-process (same
pattern as test_trace_endpoint) so run_metadata, spans and checkpoints exist
for the stats and replay endpoints to aggregate.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from api.server import app
from worker.tasks import _run_task_async

pytestmark = pytest.mark.integration


async def _run_one_task(pool, request: str) -> uuid.UUID:
    task_id = uuid.uuid4()
    await pool.execute(
        "INSERT INTO tasks (id, request, status) VALUES ($1, $2, 'queued')",
        task_id, request,
    )
    await _run_task_async(str(task_id), request)
    return task_id


async def _cleanup(pool, task_id: uuid.UUID) -> None:
    await pool.execute("DELETE FROM spans WHERE attributes ->> 'task_id' = $1", str(task_id))
    await pool.execute("DELETE FROM run_metadata WHERE task_id = $1", task_id)
    await pool.execute("DELETE FROM tasks WHERE id = $1", task_id)
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        await pool.execute(f"DELETE FROM {table} WHERE thread_id = $1", str(task_id))
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        await pool.execute(f"DELETE FROM {table} WHERE thread_id LIKE 'replay-%'")


@pytest.mark.asyncio
async def test_task_list_stats_and_replay_endpoints(postgres_pool):
    task_id = await _run_one_task(postgres_pool, "phase 8 endpoint test")
    try:
        with TestClient(app) as client:
            listed = client.get("/tasks?limit=10").json()
            ids = [task["task_id"] for task in listed["tasks"]]
            assert str(task_id) in ids
            entry = next(t for t in listed["tasks"] if t["task_id"] == str(task_id))
            assert entry["status"] == "completed"
            assert entry["request"] == "phase 8 endpoint test"

            stats = client.get("/stats/cost").json()
            assert stats["runs"] >= 1
            assert stats["runs_by_status"].get("completed", 0) >= 1
            assert stats["prompt_tokens"] >= 0
            assert stats["avg_latency_ms"] >= 0
            assert isinstance(stats["models"], dict)
            assert isinstance(stats["escalations"], dict)

            replay = client.post(
                f"/tasks/{task_id}/replay",
                json={"edits": {"task_description": "phase 8 endpoint test (edited)"}},
            )
            assert replay.status_code == 200
            body = replay.json()
            assert body["original_thread_id"] == str(task_id)
            assert body["replay_thread_id"].startswith("replay-")
            assert body["edited_fields"] == ["task_description"]
            assert "changed" in body and "changed_fields" in body

            bad_field = client.post(
                f"/tasks/{task_id}/replay",
                json={"edits": {"not_a_field": "x"}},
            )
            assert bad_field.status_code == 422

            missing = client.post(
                f"/tasks/{uuid.uuid4()}/replay", json={"edits": {}}
            )
            assert missing.status_code == 404

            explorer_page = client.get(f"/tasks/{task_id}/explorer")
            assert explorer_page.status_code == 200
            assert "Trace Explorer" in explorer_page.text
            dashboard_page = client.get("/dashboard")
            assert dashboard_page.status_code == 200
            assert "Cost" in dashboard_page.text
    finally:
        await _cleanup(postgres_pool, task_id)
