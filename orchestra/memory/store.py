import json
from typing import Any, List, Optional
from pydantic import BaseModel, Field
import asyncpg
from datetime import datetime, timezone

class MemoryEntry(BaseModel):
    """A single unit of long-term memory."""
    id: Optional[str] = None
    user_id: str
    task_id: str
    request: str
    approach: str
    tools_used: List[str]
    outcome: str
    facts: List[str]
    preferences: List[str] = Field(default_factory=list)
    embedding: Optional[List[float]] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 0

class MemoryStore:
    """Handles persistence of memories in Postgres and ChromaDB."""
    
    def __init__(self, pool: asyncpg.Pool, chroma_client: Any):
        self.pool = pool
        self.chroma = chroma_client

    async def save_memory(self, entry: MemoryEntry):
        # 1. Save metadata to Postgres
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO memories (user_id, task_id, request, approach, tools_used, outcome, facts, preferences, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
            """,
                entry.user_id, entry.task_id, entry.request, entry.approach,
                json.dumps(entry.tools_used), entry.outcome,
                json.dumps(entry.facts), json.dumps(entry.preferences), entry.created_at
            )
            entry.id = row['id']

        # 2. Save embedding to ChromaDB
        if entry.embedding:
            self.chroma.get_or_create_collection("orchestra_memories").add(
                ids=[entry.id],
                embeddings=[entry.embedding],
                metadatas=[{"user_id": entry.user_id, "task_id": entry.task_id}]
            )
        return entry

    async def delete_user_memories(self, user_id: str):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM memories WHERE user_id = $1", user_id)
        # Note: ChromaDB deletion would happen here via metadata filter

async def init_memory_table(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                task_id VARCHAR(255) NOT NULL,
                request TEXT NOT NULL,
                approach TEXT,
                tools_used JSONB,
                outcome TEXT,
                facts JSONB,
                preferences JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                access_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
        """)
