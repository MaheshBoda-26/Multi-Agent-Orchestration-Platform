"""Trace/cost endpoints over a real run. Requires Postgres; skips otherwise."""
import uuid

import pytest
from fastapi.testclient import TestClient

from api.server import app
from worker.tasks import _run_task_async

pytestmark = pytest.mark.integration


def _collect_names(nodes):
    names = []
    for node in nodes:
        names.append(node["name"])
        names.extend(_collect_names(node["children"]))
    return names


@pytest.mark.asyncio
async def test_trace_and_cost_endpoints_after_a_run(postgres_pool):
    task_id = uuid.uuid4()
    await postgres_pool.execute(
        "INSERT INTO tasks (id, request, status) VALUES ($1, $2, 'queued')",
        task_id, "trace endpoint test",
    )
    try:
        await _run_task_async(str(task_id), "trace endpoint test")

        span_count = await postgres_pool.fetchval(
            "SELECT count(*) FROM spans WHERE attributes ->> 'task_id' = $1",
            str(task_id),
        )
        assert span_count >= 6, f"expected a span per agent/tool/model call, got {span_count}"

        with TestClient(app) as client:
            trace = client.get(f"/tasks/{task_id}/trace").json()
            cost = client.get(f"/tasks/{task_id}/cost").json()

        names = _collect_names(trace["roots"])
        for expected in (
            "task.run", "supervisor.plan", "specialist.run",
            "reviewer.review", "synthesize",
        ):
            assert expected in names, f"missing {expected} in {names}"

        span_cost = await postgres_pool.fetchval(
            """
            SELECT COALESCE(SUM((attributes ->> 'cost_usd')::numeric), 0)
            FROM spans
            WHERE name LIKE 'llm.%' AND attributes ->> 'task_id' = $1
            """,
            str(task_id),
        )
        assert float(span_cost) == pytest.approx(cost["cost_usd"])
        assert cost["status"] == "completed"
    finally:
        await postgres_pool.execute(
            "DELETE FROM spans WHERE attributes ->> 'task_id' = $1", str(task_id)
        )
        await postgres_pool.execute(
            "DELETE FROM run_metadata WHERE task_id = $1", task_id
        )
        await postgres_pool.execute("DELETE FROM tasks WHERE id = $1", task_id)
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            await postgres_pool.execute(
                f"DELETE FROM {table} WHERE thread_id = $1", str(task_id)
            )
