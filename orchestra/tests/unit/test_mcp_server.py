"""MCP server (Task 42): schema listing, audited calls, sensitive gating."""
import pytest

from mcp_server.server import OrchestraMCPServer
from tools.bootstrap import build_tool_registry, SENSITIVE_TOOLS

EXPECTED_TOOLS = {"web_search", "http_get", "file_read", "file_write", "code_execute", "db_query"}


@pytest.fixture
def server(tmp_path):
    registry = build_tool_registry("mcp-test-task", workspace_root=str(tmp_path))
    return OrchestraMCPServer(registry, allow_sensitive=False)


def test_tools_list_exposes_registry_schemas(server):
    tools = server.list_tool_schemas()
    names = {tool["name"] for tool in tools}
    assert EXPECTED_TOOLS <= names

    by_name = {tool["name"]: tool for tool in tools}
    file_read = by_name["file_read"]
    assert file_read["description"]
    schema = file_read["inputSchema"]
    assert schema["type"] == "object"
    assert "path" in schema["properties"]
    assert schema["properties"]["path"]["type"] == "string"

    web_search = by_name["web_search"]
    assert "query" in web_search["inputSchema"]["properties"]


def test_initialize_and_tools_list_over_jsonrpc(server):
    init = server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    })
    assert init["jsonrpc"] == "2.0"
    assert init["result"]["serverInfo"]["name"] == "orchestra-mcp"

    listed = server.handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list",
    })
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert EXPECTED_TOOLS <= names


def test_unknown_method_is_jsonrpc_error(server):
    response = server.handle_request({
        "jsonrpc": "2.0", "id": 3, "method": "resources/list",
    })
    assert response["error"]["code"] == -32601


def test_notifications_return_none(server):
    assert server.handle_request({
        "jsonrpc": "2.0", "method": "notifications/initialized",
    }) is None


@pytest.mark.asyncio
async def test_tools_call_runs_through_the_registry(server):
    response = await server.handle_request({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "web_search", "arguments": {"query": "orchestra"}},
    })
    result = response["result"]
    assert result["isError"] is False or "isError" not in result
    text = result["content"][0]["text"]
    assert "orchestra" in text.lower()


@pytest.mark.asyncio
async def test_unknown_tool_call_is_invalid_params(server):
    response = await server.handle_request({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "no_such_tool", "arguments": {}},
    })
    assert response["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_sensitive_tools_are_gated_with_a_signature(server):
    for name in SENSITIVE_TOOLS:
        response = await server.handle_request({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": name, "arguments": {"path": "x.txt", "content": "hi", "code": "1", "url": "https://wikipedia.org"}},
        })
        result = response["result"]
        assert result["isError"] is True, f"{name} must not execute without approval"
        assert "approval signature" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_file_read_roundtrip_inside_the_jail(tmp_path):
    registry = build_tool_registry("mcp-test-task-2", workspace_root=str(tmp_path))
    server = OrchestraMCPServer(registry, allow_sensitive=False)
    write = await server.call_tool("file_write", {"path": "notes.txt", "content": "hello mcp"})
    assert write["content"][0]["text"].startswith("Successfully wrote")

    read = await server.call_tool("file_read", {"path": "notes.txt"})
    assert read["content"][0]["text"] == "hello mcp"

    escape = await server.call_tool("file_read", {"path": "../../etc/passwd"})
    assert escape["isError"] is True
    assert "outside workspace" in escape["content"][0]["text"]
