"""Build the tool registry for a single task.

Each task gets its own workspace directory for the file tools, its own registry
(so rate-limit state is per task), and the sensitive tools are marked so the
approval gate can require a human before they run.
"""
import os
from pathlib import Path
from typing import List, Optional

from tools.builtin.db_tools import ReadOnlySQLTool
from tools.builtin.file_tools import FileReadTool, FileWriteTool
from tools.builtin.sandbox import CodeExecutionTool
from tools.builtin.web_tools import HttpCallTool, TavilySearchTool, WebSearchTool
from tools.permissions import permission_manager
from tools.registry import BaseTool, ToolRegistry

DEFAULT_WORKSPACES_ROOT = "./workspaces"
DEFAULT_HTTP_ALLOWLIST = [
    "wikipedia.org",
    "arxiv.org",
    "docs.python.org",
    "openrouter.ai",
]
# Tools that mutate the world or leave the machine need human approval.
SENSITIVE_TOOLS = ("code_execute", "http_get", "file_write")


def _search_tool(search_backend: Optional[str]) -> BaseTool:
    """Tavily when a key (or explicit backend) exists, simulated otherwise."""
    backend = (search_backend or os.getenv("SEARCH_BACKEND") or "").lower()
    if backend == "tavily" or (not backend and os.getenv("TAVILY_API_KEY")):
        return TavilySearchTool()
    return WebSearchTool()


def workspace_for_task(task_id: str, root: Optional[str] = None) -> Path:
    base = Path(root or os.getenv("WORKSPACES_ROOT") or DEFAULT_WORKSPACES_ROOT)
    path = base / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_tool_registry(
    task_id: str,
    *,
    workspace_root: Optional[str] = None,
    allowed_domains: Optional[List[str]] = None,
    search_backend: Optional[str] = None,
) -> ToolRegistry:
    """Register the builtin tools rooted at this task's workspace."""
    registry = ToolRegistry()
    workspace = workspace_for_task(task_id, workspace_root)

    registry.register(FileReadTool(str(workspace)))
    registry.register(FileWriteTool(str(workspace)))
    registry.register(CodeExecutionTool())
    registry.register(HttpCallTool(allowed_domains or DEFAULT_HTTP_ALLOWLIST))
    registry.register(_search_tool(search_backend))
    registry.register(ReadOnlySQLTool())

    for name in SENSITIVE_TOOLS:
        permission_manager.mark_sensitive(name)
    return registry
