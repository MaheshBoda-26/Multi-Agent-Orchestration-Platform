"""Run analytics lifecycle for the ``run_metadata`` table (migration 001).

One row per graph run: created when a worker picks up a task, completed with
token/cost/latency totals when the run finishes, failed on error, and paused
while a human decides. ``run_metadata`` is the per-task rollup source of truth;
spans are the per-step detail.
"""
import json
import uuid
from typing import Any, Dict, Optional

import asyncpg


async def start_run(
    pool: asyncpg.Pool,
    run_id: uuid.UUID,
    task_id: uuid.UUID,
    task_description: str,
) -> None:
    """Create the run row in status ``running`` (idempotent per run id)."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO run_metadata (run_id, task_id, task_description, status, started_at)
            VALUES ($1, $2, $3, 'running', NOW())
            ON CONFLICT (run_id) DO NOTHING
            """,
            run_id, task_id, task_description,
        )


async def complete_run(
    pool: asyncpg.Pool,
    run_id: uuid.UUID,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_ms: int = 0,
    model_breakdown: Optional[Dict[str, Any]] = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE run_metadata
            SET status = 'completed',
                total_prompt_tokens = $2,
                total_completion_tokens = $3,
                total_cost_usd = $4,
                latency_ms = $5,
                model_breakdown = $6,
                completed_at = NOW()
            WHERE run_id = $1
            """,
            run_id, prompt_tokens, completion_tokens, cost_usd, latency_ms,
            json.dumps(model_breakdown or {}),
        )


async def fail_run(pool: asyncpg.Pool, run_id: uuid.UUID, error: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE run_metadata
            SET status = 'failed', error = $2, completed_at = NOW()
            WHERE run_id = $1
            """,
            run_id, error,
        )


async def mark_paused(pool: asyncpg.Pool, run_id: uuid.UUID) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE run_metadata SET status = 'awaiting_human' WHERE run_id = $1",
            run_id,
        )


async def latest_run_id(pool: asyncpg.Pool, task_id: uuid.UUID) -> Optional[uuid.UUID]:
    """Newest run for a task, so a resumed worker updates the original row."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT run_id FROM run_metadata
            WHERE task_id = $1
            ORDER BY started_at DESC
            LIMIT 1
            """,
            task_id,
        )
