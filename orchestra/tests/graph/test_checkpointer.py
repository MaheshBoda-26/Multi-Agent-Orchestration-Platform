import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from graph.build import OrchestraGraph
from graph.checkpointer import create_checkpointer
from llm.fake import FakeProvider


@pytest.mark.asyncio
async def test_create_checkpointer_returns_async_postgres_saver(postgres_pool):
    pool, saver = await create_checkpointer()
    try:
        assert isinstance(saver, AsyncPostgresSaver)
        async with pool.connection() as conn:
            cursor = await conn.execute(
                "SELECT to_regclass('checkpoints') AS checkpoints,"
                " to_regclass('checkpoint_blobs') AS blobs"
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row["checkpoints"] is not None, "checkpoints table should exist after setup()"
        assert row["blobs"] is not None, "checkpoint_blobs table should exist after setup()"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_graph_compiles_with_checkpointer_and_enables_hitl(postgres_pool):
    pool, saver = await create_checkpointer()
    try:
        graph = OrchestraGraph(FakeProvider(), checkpointer=saver)
        assert graph.hitl_enabled is True
        assert graph.workflow.checkpointer is saver
    finally:
        await pool.close()


def test_hitl_stays_off_without_checkpointer():
    graph = OrchestraGraph(FakeProvider())
    assert graph.hitl_enabled is False
