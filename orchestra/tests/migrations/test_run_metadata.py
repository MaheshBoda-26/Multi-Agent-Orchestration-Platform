import pytest

@pytest.mark.asyncio
async def test_run_metadata_table_exists(postgres_pool):
    """Table exists with correct schema after migration."""
    async with postgres_pool.acquire() as conn:
        # Check table exists
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'run_metadata'
            )
        """)
        assert exists, "run_metadata table should exist"

        # Check columns
        columns = await conn.fetch("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'run_metadata'
            ORDER BY ordinal_position
        """)
        column_names = [c['column_name'] for c in columns]
        expected = ['run_id', 'task_id', 'task_description', 'status',
                    'total_prompt_tokens', 'total_completion_tokens',
                    'total_cost_usd', 'latency_ms', 'model_breakdown',
                    'started_at', 'completed_at', 'error', 'checkpoint_data']
        for col in expected:
            assert col in column_names, f"Missing column: {col}"

        # Check indexes
        indexes = await conn.fetch("""
            SELECT indexname FROM pg_indexes WHERE tablename = 'run_metadata'
        """)
        index_names = [i['indexname'] for i in indexes]
        assert 'idx_run_metadata_task_id' in index_names
        assert 'idx_run_metadata_status' in index_names

@pytest.mark.asyncio
async def test_migrations_table_tracks_versions(postgres_pool):
    """Migrations table records applied versions."""
    async with postgres_pool.acquire() as conn:
        version = await conn.fetchval("SELECT version FROM migrations WHERE name = '001_run_metadata'")
        assert version == 1, "Migration 001 should be recorded as applied"