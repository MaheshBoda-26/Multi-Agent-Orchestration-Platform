"""Execute a tool with permission, approval and audit guarantees.

Every tool call in the system goes through this module, so one place owns:
the registry's permission and rate-limit checks, the sensitive-tool approval
gate (Phase 4 raises ``ApprovalRequired`` and the graph interrupts), and the
``tool_calls`` audit row (inputs, outputs, latency, status).
"""
import hashlib
import json
import time
from typing import Any, Dict, Optional

import asyncpg

from observability.spans import span
from tools.permissions import permission_manager
from tools.registry import ToolRegistry, ToolResult


class ApprovalRequired(Exception):
    """A sensitive tool needs a human decision before it can run."""

    def __init__(self, tool_name: str, arguments: Dict[str, Any], signature: str) -> None:
        super().__init__(f"Approval required for {tool_name}")
        self.tool_name = tool_name
        self.arguments = arguments
        self.signature = signature


def tool_signature(subtask_id: str, tool_name: str, arguments: Dict[str, Any]) -> str:
    """Stable per-call signature: the unit a human approval covers."""
    payload = json.dumps(
        {"subtask": subtask_id, "tool": tool_name, "arguments": arguments},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


async def log_tool_call(
    pool: asyncpg.Pool,
    *,
    task_id: Any,
    subtask_id: str,
    specialist: str,
    tool_name: str,
    arguments: Dict[str, Any],
    result: ToolResult,
    latency_ms: int,
    sensitive: bool,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tool_calls
                (task_id, subtask_id, specialist, tool_name, arguments, result,
                 status, error, latency_ms, sensitive)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            task_id,
            subtask_id,
            specialist,
            tool_name,
            json.dumps(arguments, default=str),
            json.dumps(result.model_dump(), default=str),
            result.status,
            result.error,
            latency_ms,
            sensitive,
        )


async def execute_tool(
    registry: ToolRegistry,
    pool: Optional[asyncpg.Pool],
    *,
    task_id: Any,
    subtask_id: str,
    specialist: str,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    approved_signature: Optional[str] = None,
) -> ToolResult:
    """Run one tool call, audited. Raises ApprovalRequired for sensitive tools."""
    args = arguments or {}
    sensitive = permission_manager.is_sensitive(tool_name)
    signature = tool_signature(subtask_id, tool_name, args)
    if sensitive and approved_signature != signature:
        raise ApprovalRequired(tool_name, args, signature)

    start = time.monotonic()
    with span("tool.call", tool_name=tool_name, specialist=specialist, subtask_id=subtask_id):
        result = await registry.execute(tool_name, specialist, **args)
    latency_ms = int((time.monotonic() - start) * 1000)

    if pool is not None:
        await log_tool_call(
            pool,
            task_id=task_id,
            subtask_id=subtask_id,
            specialist=specialist,
            tool_name=tool_name,
            arguments=args,
            result=result,
            latency_ms=latency_ms,
            sensitive=sensitive,
        )
    return result
