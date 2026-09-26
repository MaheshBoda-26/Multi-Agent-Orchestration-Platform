"""User-scoped task persistence (TRD section 4).

The API is the only writer for task rows; the graph and worker process read and
update status through these helpers. Everything lives in Postgres so an API or
worker restart never loses a task.
"""
import json
import uuid
from typing import Any, Dict, Optional

import asyncpg

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


async def create_task(pool: asyncpg.Pool, task_id: uuid.UUID, request: str,
                      user_id: Optional[str] = None) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tasks (id, user_id, request, status, created_at)
            VALUES ($1, $2, $3, 'queued', NOW())
            """,
            task_id, user_id, request,
        )


async def set_task_status(pool: asyncpg.Pool, task_id: uuid.UUID, status: str,
                          error: Optional[str] = None) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET status = $2::varchar,
                error = COALESCE($3, error),
                started_at = CASE WHEN $2::text = 'running' THEN NOW() ELSE started_at END
            WHERE id = $1
            """,
            task_id, status, error,
        )


async def save_task_plan(pool: asyncpg.Pool, task_id: uuid.UUID,
                         plan: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tasks SET plan = $2 WHERE id = $1",
            task_id, json.dumps(plan),
        )


async def complete_task(pool: asyncpg.Pool, task_id: uuid.UUID,
                        result: Dict[str, Any]) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'completed', result = $2, finished_at = NOW()
            WHERE id = $1
            """,
            task_id, json.dumps(result),
        )


async def fail_task(pool: asyncpg.Pool, task_id: uuid.UUID, error: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'failed', error = $2, finished_at = NOW()
            WHERE id = $1
            """,
            task_id, error,
        )


async def get_task(pool: asyncpg.Pool, task_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
    if row is None:
        return None
    return _serialize(dict(row))


def _serialize(row: Dict[str, Any]) -> Dict[str, Any]:
    """Make a task row JSON-friendly for the API."""
    return {
        "task_id": str(row["id"]),
        "user_id": row.get("user_id"),
        "request": row.get("request"),
        "status": row.get("status"),
        "plan": json.loads(row["plan"]) if isinstance(row.get("plan"), str) else row.get("plan"),
        "result": json.loads(row["result"]) if isinstance(row.get("result"), str) else row.get("result"),
        "error": row.get("error"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "started_at": row["started_at"].isoformat() if row.get("started_at") else None,
        "finished_at": row["finished_at"].isoformat() if row.get("finished_at") else None,
    }
