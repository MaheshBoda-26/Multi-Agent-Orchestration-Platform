import pytest

from tools.builtin.db_tools import ReadOnlySQLTool


def test_rejects_non_select_statements():
    assert ReadOnlySQLTool.rejection_reason("INSERT INTO tasks VALUES (1)") is not None
    assert ReadOnlySQLTool.rejection_reason("UPDATE tasks SET status = 'x'") is not None
    assert ReadOnlySQLTool.rejection_reason("DROP TABLE tasks") is not None
    assert ReadOnlySQLTool.rejection_reason("TRUNCATE tasks") is not None


def test_rejects_multi_statement_queries():
    reason = ReadOnlySQLTool.rejection_reason("SELECT 1; DELETE FROM tasks")
    assert reason is not None and "single statement" in reason


def test_accepts_select_and_with():
    assert ReadOnlySQLTool.rejection_reason("SELECT * FROM tasks LIMIT 5") is None
    assert ReadOnlySQLTool.rejection_reason(
        "WITH recent AS (SELECT * FROM tasks) SELECT count(*) FROM recent"
    ) is None


@pytest.mark.asyncio
async def test_rejected_query_never_reaches_the_database():
    tool = ReadOnlySQLTool(dsn="postgresql://invalid:invalid@127.0.0.1:1/never")
    result = await tool.run(query="DELETE FROM tasks")
    assert result.status == "error"
    assert "SELECT / WITH" in (result.error or "")


@pytest.mark.asyncio
async def test_select_returns_rows(postgres_pool):
    tool = ReadOnlySQLTool()
    result = await tool.run(query="SELECT 1 AS one, 'x' AS letter")
    assert result.status == "success"
    assert "one | letter" in result.content
    assert "1 | x" in result.content
