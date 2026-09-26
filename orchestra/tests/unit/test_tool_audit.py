import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.execution import ApprovalRequired, execute_tool, tool_signature
from tools.permissions import permission_manager
from tools.registry import BaseTool, ToolResult, ToolRegistry, ToolSchema


class DummyTool(BaseTool):
    def __init__(self, name: str = "dummy", rate_limit=None, allowed=None):
        schema = ToolSchema(
            name=name,
            description="test",
            parameters={},
            rate_limit=rate_limit,
            allowed_specialists=allowed or [],
        )
        super().__init__(schema)
        self.calls = 0

    async def run(self, **kwargs):
        self.calls += 1
        return ToolResult(content="success", metadata={"kwargs": kwargs})


def _pool_with_conn(conn):
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


@pytest.fixture(autouse=True)
def clean_permissions():
    permission_manager._sensitive_tools.clear()
    yield
    permission_manager._sensitive_tools.clear()


@pytest.mark.asyncio
async def test_every_call_logged_with_inputs_outputs_latency_status():
    registry = ToolRegistry()
    tool = DummyTool("lookup")
    registry.register(tool)
    conn = AsyncMock()
    pool = _pool_with_conn(conn)

    result = await execute_tool(
        registry, pool,
        task_id="task-1", subtask_id="t1", specialist="researcher",
        tool_name="lookup", arguments={"query": "x"},
    )

    assert result.status == "success"
    assert tool.calls == 1
    conn.execute.assert_awaited_once()
    sql, *params = conn.execute.await_args.args
    assert "INSERT INTO tool_calls" in sql
    task_id, subtask_id, specialist, tool_name, arguments, result_json, status, error, latency, sensitive = params
    assert (task_id, subtask_id, specialist, tool_name) == ("task-1", "t1", "researcher", "lookup")
    assert json.loads(arguments) == {"query": "x"}
    assert json.loads(result_json)["content"] == "success"
    assert status == "success"
    assert error is None
    assert isinstance(latency, int) and latency >= 0
    assert sensitive is False


@pytest.mark.asyncio
async def test_denied_call_is_logged_as_error():
    registry = ToolRegistry()
    registry.register(DummyTool("restricted", allowed=["admin"]))
    conn = AsyncMock()
    pool = _pool_with_conn(conn)

    result = await execute_tool(
        registry, pool,
        task_id="task-1", subtask_id="t1", specialist="guest",
        tool_name="restricted", arguments={},
    )

    assert result.status == "error"
    assert "not permitted" in (result.error or "")
    params = conn.execute.await_args.args[1:]
    assert params[6] == "error"
    assert "not permitted" in params[7]


@pytest.mark.asyncio
async def test_sensitive_tool_requires_approval_signature():
    registry = ToolRegistry()
    registry.register(DummyTool("danger"))
    permission_manager.mark_sensitive("danger")
    conn = AsyncMock()
    pool = _pool_with_conn(conn)

    with pytest.raises(ApprovalRequired) as excinfo:
        await execute_tool(
            registry, pool,
            task_id="task-1", subtask_id="t1", specialist="code_executor",
            tool_name="danger", arguments={"x": 1},
        )
    assert excinfo.value.signature == tool_signature("t1", "danger", {"x": 1})
    conn.execute.assert_not_awaited()

    approved = await execute_tool(
        registry, pool,
        task_id="task-1", subtask_id="t1", specialist="code_executor",
        tool_name="danger", arguments={"x": 1},
        approved_signature=excinfo.value.signature,
    )
    assert approved.status == "success"
    params = conn.execute.await_args.args[1:]
    assert params[9] is True  # sensitive flag recorded
