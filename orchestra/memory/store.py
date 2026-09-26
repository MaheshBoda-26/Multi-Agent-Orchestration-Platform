"""Long-term memory storage on pgvector (Phase 5).

Metadata and the embedding live in one Postgres row, so per-user scoping is a
WHERE clause and deleting a user removes vectors and metadata together. Search
is cosine distance (`embedding <=> $1::vector`) over an HNSW index; ranking
blends similarity with importance and a recency half-life (Task 30).
"""
import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
from pydantic import BaseModel

from llm.embeddings import EmbeddingProvider


class MemoryRecord(BaseModel):
    """One row of the memories table."""
    id: int
    user_id: str
    kind: str
    content: str
    importance: float
    access_count: int
    last_accessed_at: Optional[datetime] = None
    source_task_id: Optional[str] = None
    created_at: datetime
    similarity: float = 0.0  # populated by search, 1.0 = identical


async def save_memory(
    pool: asyncpg.Pool,
    embeddings: EmbeddingProvider,
    *,
    user_id: str,
    content: str,
    kind: str = "task_lesson",
    importance: float = 0.5,
    source_task_id: Optional[str] = None,
) -> int:
    """Embed and insert one memory; returns its row id."""
    vector = await embeddings.embed(content)
    async with pool.acquire() as conn:
        row_id = await conn.fetchval(
            """
            INSERT INTO memories
                (user_id, kind, content, embedding, importance, source_task_id)
            VALUES ($1, $2, $3, $4::vector, $5, $6)
            RETURNING id
            """,
            user_id,
            kind,
            content,
            _vector_literal(vector),
            importance,
            source_task_id,
        )
    return int(row_id)


async def search_memories(
    pool: asyncpg.Pool,
    embeddings: EmbeddingProvider,
    *,
    user_id: str,
    query: str,
    top_k: int = 5,
    kind: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[MemoryRecord]:
    """Cosine top-k over one user's memories, ranked with Task 30 scoring.

    final score = cosine_similarity
                + 0.2 * importance
                + 0.1 * recency_half_life(30 days)
    Ties in the vector index don't matter: the blend is applied in SQL.
    """
    vector = await embeddings.embed(query)
    now = now or datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, kind, content, importance, access_count,
                   last_accessed_at, source_task_id, created_at,
                   1 - (embedding <=> $2::vector) AS similarity
            FROM memories
            WHERE user_id = $1 AND ($3::varchar IS NULL OR kind = $3)
            ORDER BY
                (1 - (embedding <=> $2::vector))
                  + 0.2 * importance
                  + 0.1 * power(0.5, EXTRACT(EPOCH FROM ($4 - created_at)) / 2592000.0)
                DESC
            LIMIT $5
            """,
            user_id,
            _vector_literal(vector),
            kind,
            now,
            top_k,
        )
    records = [
        MemoryRecord(
            id=row["id"],
            user_id=row["user_id"],
            kind=row["kind"],
            content=row["content"],
            importance=float(row["importance"]),
            access_count=row["access_count"],
            last_accessed_at=row["last_accessed_at"],
            source_task_id=row["source_task_id"],
            created_at=row["created_at"],
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]
    if records:
        # Bump first, then reflect the new counts in what we return (the SELECT
        # snapshot predates the UPDATE, so add the increment here too).
        await _touch_accessed(pool, [r.id for r in records], now)
        for record in records:
            record.access_count += 1
            record.last_accessed_at = now
    return records


async def _touch_accessed(
    pool: asyncpg.Pool, ids: List[int], now: datetime
) -> None:
    """Bump access_count/last_accessed_at for retrieved memories."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE memories
            SET access_count = access_count + 1, last_accessed_at = $2
            WHERE id = ANY($1::bigint[])
            """,
            ids,
            now,
        )


async def list_user_memories(
    pool: asyncpg.Pool, user_id: str, limit: int = 100
) -> List[MemoryRecord]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, kind, content, importance, access_count,
                   last_accessed_at, source_task_id, created_at
            FROM memories WHERE user_id = $1
            ORDER BY created_at DESC LIMIT $2
            """,
            user_id,
            limit,
        )
    return [
        MemoryRecord(
            id=row["id"],
            user_id=row["user_id"],
            kind=row["kind"],
            content=row["content"],
            importance=float(row["importance"]),
            access_count=row["access_count"],
            last_accessed_at=row["last_accessed_at"],
            source_task_id=row["source_task_id"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


async def delete_user_memories(pool: asyncpg.Pool, user_id: str) -> int:
    """Remove every memory row (vector + metadata) for one user."""
    async with pool.acquire() as conn:
        status = await conn.execute("DELETE FROM memories WHERE user_id = $1", user_id)
    # asyncpg returns the command tag, e.g. "DELETE 3".
    return int(status.split()[-1]) if status and status.startswith("DELETE") else 0


def _vector_literal(vector: List[float]) -> str:
    """pgvector text format: '[1.0,2.0,...]' passed through ::vector."""
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


# Kept for compatibility with callers importing from memory.store.
def dumps(value: Any) -> str:
    return json.dumps(value)


def half_life(age_seconds: float, half_life_days: float = 30.0) -> float:
    """Exponential recency decay used by the SQL ranking blend."""
    return math.pow(0.5, age_seconds / (half_life_days * 86400.0))


def dict_helper(data: Dict[str, Any]) -> str:
    return json.dumps(data)
