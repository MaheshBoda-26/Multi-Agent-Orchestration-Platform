import json
import uuid

import pytest

from api import run_metadata


@pytest.mark.asyncio
async def test_start_and_complete_run(postgres_pool):
    run_id, task_id = uuid.uuid4(), uuid.uuid4()
    try:
        await run_metadata.start_run(postgres_pool, run_id, task_id, "lifecycle test")

        async with postgres_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM run_metadata WHERE run_id = $1", run_id
            )
        assert row["status"] == "running"
        assert row["task_id"] == task_id
        assert row["completed_at"] is None

        await run_metadata.complete_run(
            postgres_pool, run_id,
            prompt_tokens=120, completion_tokens=40, cost_usd=0.0015,
            latency_ms=4321, model_breakdown={"fake-model-v1": {"calls": 3}},
        )

        async with postgres_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM run_metadata WHERE run_id = $1", run_id
            )
        assert row["status"] == "completed"
        assert row["total_prompt_tokens"] == 120
        assert row["total_completion_tokens"] == 40
        assert float(row["total_cost_usd"]) == pytest.approx(0.0015)
        assert row["latency_ms"] == 4321
        assert row["completed_at"] is not None
        breakdown = row["model_breakdown"]
        if isinstance(breakdown, str):
            breakdown = json.loads(breakdown)
        assert breakdown == {"fake-model-v1": {"calls": 3}}
    finally:
        await postgres_pool.execute("DELETE FROM run_metadata WHERE run_id = $1", run_id)


@pytest.mark.asyncio
async def test_fail_pause_and_latest_run(postgres_pool):
    task_id = uuid.uuid4()
    first, second = uuid.uuid4(), uuid.uuid4()
    try:
        await run_metadata.start_run(postgres_pool, first, task_id, "first attempt")
        await run_metadata.fail_run(postgres_pool, first, "boom")

        async with postgres_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, error, completed_at FROM run_metadata WHERE run_id = $1",
                first,
            )
        assert row["status"] == "failed"
        assert row["error"] == "boom"
        assert row["completed_at"] is not None

        await run_metadata.start_run(postgres_pool, second, task_id, "resumed attempt")
        assert await run_metadata.latest_run_id(postgres_pool, task_id) == second

        await run_metadata.mark_paused(postgres_pool, second)
        async with postgres_pool.acquire() as conn:
            status = await conn.fetchval(
                "SELECT status FROM run_metadata WHERE run_id = $1", second
            )
        assert status == "awaiting_human"
    finally:
        await postgres_pool.execute(
            "DELETE FROM run_metadata WHERE task_id = $1", task_id
        )
