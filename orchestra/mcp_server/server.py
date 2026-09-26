"""Expose Orchestra's tools over MCP (Task 42).

A small, dependency-free Model Context Protocol server speaking the stdio
JSON-RPC dialect (``initialize``, ``tools/list``, ``tools/call``), so an
MCP-capable client can drive the same audited tool registry the graph uses:
every call flows through ``tools.execution.execute_tool`` and lands in the
``tool_calls`` audit table.

Security posture: sensitive tools (code_execute, http_get, file_write) are
marked sensitive by the registry bootstrap and stay gated - the server returns
the approval signature instead of executing them unless
``ORCHESTRA_MCP_ALLOW_SENSITIVE=1`` is set explicitly. The workspace is jailed
to one directory, exactly like a graph-run task workspace.

Run: uv run python -m mcp_server.server
"""
import asyncio
import json
import os
import sys
import uuid
from typing import Any, Dict, List, Optional

from tools.bootstrap import build_tool_registry
from tools.execution import ApprovalRequired, execute_tool
from tools.registry import ToolRegistry

JSONRPC = "2.0"
SERVER_INFO = {"name": "orchestra-mcp", "version": "0.1.0"}
PROTOCOL_VERSION = "2024-11-05"


def jsonrpc_result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": JSONRPC, "id": request_id, "result": result}


def jsonrpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": JSONRPC, "id": request_id, "error": {"code": code, "message": message}}


class OrchestraMCPServer:
    """MCP tool server over one jailed workspace-backed tool registry."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        *,
        task_id: Optional[str] = None,
        allow_sensitive: Optional[bool] = None,
    ):
        self.task_id = task_id or f"mcp-{uuid.uuid4()}"
        self.registry = registry or build_tool_registry(self.task_id)
        self.allow_sensitive = (
            allow_sensitive
            if allow_sensitive is not None
            else os.getenv("ORCHESTRA_MCP_ALLOW_SENSITIVE") == "1"
        )

    # ------------------------------------------------------------- schemas

    def list_tool_schemas(self) -> List[Dict[str, Any]]:
        """Tools in MCP ``tools/list`` shape, built from the registry."""
        tools = []
        for schema in self.registry.list_tools():
            properties = {
                name: {
                    "type": (spec or {}).get("type", "string"),
                    "description": (spec or {}).get("description", ""),
                }
                for name, spec in (schema.parameters or {}).items()
            }
            tools.append({
                "name": schema.name,
                "description": schema.description,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                },
            })
        return tools

    # --------------------------------------------------------------- calls

    async def call_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute through the audited path; sensitive tools stay gated."""
        if self.registry.get_tool(name) is None:
            raise KeyError(f"Unknown tool: {name}")
        try:
            result = await execute_tool(
                self.registry,
                None,  # no audit DB in MCP mode; the graph keeps DB auditing
                task_id=self.task_id,
                subtask_id="mcp",
                specialist="mcp_client",
                tool_name=name,
                arguments=arguments or {},
            )
        except ApprovalRequired as request:
            if not self.allow_sensitive:
                return {
                    "content": [{
                        "type": "text",
                        "text": (
                            f"Tool {name} is sensitive and requires human approval "
                            f"in Orchestra. Approval signature: {request.signature}. "
                            "Run it inside an Orchestra task instead, or set "
                            "ORCHESTRA_MCP_ALLOW_SENSITIVE=1 to override."
                        ),
                    }],
                    "isError": True,
                }
            result = await execute_tool(
                self.registry,
                None,
                task_id=self.task_id,
                subtask_id="mcp",
                specialist="mcp_client",
                tool_name=name,
                arguments=arguments or {},
                approved_signature=request.signature,
            )
        payload = {"content": [{"type": "text", "text": result.content}]}
        if result.status != "success":
            payload["isError"] = True
            payload["content"] = [{
                "type": "text",
                "text": result.error or result.content,
            }]
        return payload

    # ------------------------------------------------------------ dispatch

    async def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Dispatch one JSON-RPC request; notifications return None."""
        method = request.get("method", "")
        request_id = request.get("id")
        params = request.get("params") or {}

        if method == "initialize":
            return jsonrpc_result(request_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        if method == "ping":
            return jsonrpc_result(request_id, {})
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return jsonrpc_result(request_id, {"tools": self.list_tool_schemas()})
        if method == "tools/call":
            name = str(params.get("name", ""))
            arguments = params.get("arguments") or {}
            try:
                result = await self.call_tool(name, arguments)
            except KeyError as exc:
                return jsonrpc_error(request_id, -32602, str(exc))
            except Exception as exc:  # noqa: BLE001 - report as tool error
                return jsonrpc_result(request_id, {
                    "content": [{"type": "text", "text": f"tool crashed: {exc}"}],
                    "isError": True,
                })
            return jsonrpc_result(request_id, result)
        return jsonrpc_error(request_id, -32601, f"Method not found: {method}")


async def serve_stdio(server: Optional[OrchestraMCPServer] = None) -> None:
    """Read newline-delimited JSON-RPC requests from stdin, write to stdout."""
    server = server or OrchestraMCPServer()
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = jsonrpc_error(None, -32700, "Parse error")
        else:
            response = await server.handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(serve_stdio())
