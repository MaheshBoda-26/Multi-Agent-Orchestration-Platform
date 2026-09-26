import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider

from observability.exporter import PostgresSpanExporter
from tools.builtin.file_tools import FileReadTool, FileWriteTool, resolve_in_workspace
from tools.builtin.web_tools import HttpCallTool


# --------------------------------------------------------------- workspace jail

def test_jail_rejects_sibling_directory_with_shared_prefix(tmp_path):
    workspace = tmp_path / "ws"
    sibling = tmp_path / "ws-evil"
    workspace.mkdir()
    sibling.mkdir()
    (sibling / "secret.txt").write_text("classified")

    assert resolve_in_workspace(str(workspace), "../ws-evil/secret.txt") is None


def test_jail_rejects_symlink_escape(tmp_path):
    workspace = tmp_path / "ws"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    outside.write_text("classified")
    os.symlink(outside, workspace / "link.txt")

    assert resolve_in_workspace(str(workspace), "link.txt") is None


@pytest.mark.asyncio
async def test_file_tools_allow_paths_inside_workspace(tmp_path):
    read_tool = FileReadTool(str(tmp_path))
    write_tool = FileWriteTool(str(tmp_path))

    written = await write_tool.run(path="notes/plan.md", content="hello")
    assert written.status == "success"

    read_back = await read_tool.run(path="notes/plan.md")
    assert read_back.content == "hello"

    escaped = await read_tool.run(path="../../etc/passwd")
    assert escaped.status == "error"
    assert "Security violation" in escaped.error


# --------------------------------------------------------------------- http_get

@pytest.mark.asyncio
async def test_http_get_blocks_private_address_even_when_allowlisted():
    tool = HttpCallTool(allowed_domains=["localhost"])
    result = await tool.run(url="http://localhost/admin")
    assert result.status == "error"
    assert "private or reserved address" in result.error


@pytest.mark.asyncio
async def test_http_get_rejects_non_allowlisted_and_non_http_schemes():
    tool = HttpCallTool(allowed_domains=["example.com"])

    blocked = await tool.run(url="https://evil.test/steal")
    assert blocked.status == "error"
    assert "not in the allowlist" in blocked.error

    file_scheme = await tool.run(url="file:///etc/passwd")
    assert file_scheme.status == "error"
    assert "Scheme" in file_scheme.error


# ------------------------------------------------------------- span exporter API

def _pool_returning(conn):
    pool = MagicMock()
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)
    return pool


def test_span_exporter_is_synchronous():
    """export() must return a SpanExportResult, not a coroutine (OTel calls it sync)."""
    conn = AsyncMock()
    exporter = PostgresSpanExporter(_pool_returning(conn))
    try:
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("unit") as span:
            span.set_attribute("task_id", "task-1")

        result = exporter.export([span])

        assert result.name == "SUCCESS"
        conn.execute.assert_awaited_once()
        args = conn.execute.await_args.args
        assert len(args[1]) == 32  # hex trace id, not a decimal int
        assert len(args[2]) == 16  # hex span id
    finally:
        exporter.shutdown()
