import os
from typing import Any, Optional

from tools.registry import BaseTool, ToolResult, ToolSchema


def resolve_in_workspace(workspace_root: str, path: str) -> Optional[str]:
    """Resolve a relative path inside the workspace, or None if it escapes.

    Uses realpath (so symlinks cannot escape) and commonpath (so a sibling
    directory that merely shares a name prefix, e.g. /tmp/ws-evil next to
    /tmp/ws, is rejected too).
    """
    root = os.path.realpath(workspace_root)
    candidate = os.path.realpath(os.path.join(root, path))
    if candidate != root and os.path.commonpath([root, candidate]) != root:
        return None
    return candidate


class FileReadTool(BaseTool):
    """Reads a file from the jailed workspace."""

    def __init__(self, workspace_root: str) -> None:
        schema = ToolSchema(
            name="file_read",
            description="Read the content of a file in the workspace.",
            parameters={"path": {"type": "string", "description": "Relative path to the file"}},
            allowed_specialists=["researcher", "code_executor", "writer"]
        )
        super().__init__(schema)
        self.workspace_root = os.path.abspath(workspace_root)

    async def run(self, path: str = "", **kwargs: Any) -> ToolResult:
        full_path = resolve_in_workspace(self.workspace_root, path)
        if full_path is None:
            return ToolResult(content="", status="error", error="Security violation: path outside workspace")

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            return ToolResult(content=content)
        except Exception as e:
            return ToolResult(content="", status="error", error=str(e))


class FileWriteTool(BaseTool):
    """Writes content to a file in the jailed workspace."""

    def __init__(self, workspace_root: str) -> None:
        schema = ToolSchema(
            name="file_write",
            description="Write content to a file in the workspace.",
            parameters={
                "path": {"type": "string", "description": "Relative path to the file"},
                "content": {"type": "string", "description": "Content to write"}
            },
            allowed_specialists=["code_executor", "writer"]
        )
        super().__init__(schema)
        self.workspace_root = os.path.abspath(workspace_root)

    async def run(self, path: str = "", content: str = "", **kwargs: Any) -> ToolResult:
        full_path = resolve_in_workspace(self.workspace_root, path)
        if full_path is None:
            return ToolResult(content="", status="error", error="Security violation: path outside workspace")

        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(content=f"Successfully wrote to {path}")
        except Exception as e:
            return ToolResult(content="", status="error", error=str(e))
