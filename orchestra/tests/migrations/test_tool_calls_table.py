import pytest


@pytest.mark.asyncio
async def test_tool_calls_table_exists_with_audit_columns(postgres_pool):
    async with postgres_pool.acquire() as conn:
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'tool_calls'
            )
        """)
        assert exists, "tool_calls table should exist"

        columns = await conn.fetch("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'tool_calls'
        """)
        names = {c["column_name"] for c in columns}
        for expected in (
            "task_id", "subtask_id", "specialist", "tool_name", "arguments",
            "result", "status", "error", "latency_ms", "sensitive", "created_at",
        ):
            assert expected in names, f"missing column {expected}"

        version = await conn.fetchval(
            "SELECT version FROM migrations WHERE name = '003_tool_calls'"
        )
        assert version == 3
