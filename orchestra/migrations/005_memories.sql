-- Migration: pgvector long-term memories (Phase 5)
-- Version: 5
-- One table: metadata + embedding live together, so deleting a user's rows
-- removes vector and metadata in one statement (per-user scoped, HNSW cosine).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    kind VARCHAR(50) NOT NULL DEFAULT 'task_lesson',
    content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TIMESTAMP WITH TIME ZONE,
    source_task_id VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_user_kind ON memories(user_id, kind);
-- Cosine similarity search scoped by user_id; HNSW trades a little recall for
-- fast approximate top-k at this table's expected size.
CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops);
