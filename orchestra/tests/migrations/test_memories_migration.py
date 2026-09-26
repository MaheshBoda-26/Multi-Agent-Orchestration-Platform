"""Migration 005: memories table with pgvector column and HNSW index."""
import pytest

pytestmark = pytest.mark.usefixtures("postgres_pool")


@pytest.mark.asyncio
async def test_memories_table_and_indexes(postgres_pool):
    async with postgres_pool.acquire() as conn:
        columns = await conn.fetch("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'memories' ORDER BY ordinal_position
        """)
        names = [c["column_name"] for c in columns]
        for expected in (
            "id", "user_id", "kind", "content", "embedding", "importance",
            "access_count", "last_accessed_at", "source_task_id", "created_at",
        ):
            assert expected in names, f"missing column {expected}"

        embedding_type = next(
            c["data_type"] for c in columns if c["column_name"] == "embedding"
        )
        # information_schema reports custom types as USER-DEFINED; verify the
        # underlying type is pgvector's "vector" via the extension catalog.
        if embedding_type == "USER-DEFINED":
            real = await conn.fetchval(
                """
                SELECT t.typname FROM pg_type t
                JOIN pg_attribute a ON a.atttypid = t.oid
                JOIN pg_class c ON c.oid = a.attrelid
                WHERE c.relname = 'memories' AND a.attname = 'embedding'
                """
            )
            embedding_type = real
        assert embedding_type == "vector", embedding_type

        indexes = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'memories'"
        )
        index_names = {i["indexname"] for i in indexes}
        assert "idx_memories_user_id" in index_names
        assert "idx_memories_embedding_hnsw" in index_names


@pytest.mark.asyncio
async def test_vector_extension_and_cosine_operator(postgres_pool):
    async with postgres_pool.acquire() as conn:
        # The cosine distance operator must work on the column (round-trip).
        row = await conn.fetchrow(
            """
            SELECT 1 - (embedding <=> embedding) AS self_sim
            FROM memories LIMIT 1
            """
        )
        if row is None:
            pytest.skip("no memory rows yet")
        assert row["self_sim"] == 1.0
