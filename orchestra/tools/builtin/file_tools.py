import os
import shutil
from typing import Optional
from tools.registry import BaseTool, ToolSchema, ToolResult

class FileReadTool(BaseTool):
    """Reads a file from the jailed workspace."""
    
    def __init__(self, workspace_root: str):
        schema = ToolSchema(
            name="file_read",
            description="Read the content of a file in the workspace.",
            parameters={"path": {"type": "string", "description": "Relative path to the file"}},
            allowed_specialists=["researcher", "code_executor", "writer"]
        )
        super().__init__(schema)
        self.workspace_root = os.path.abspath(workspace_root)

    async def run(self, path: str, **kwargs) -> ToolResult:
        # Jail check: Ensure path is within workspace_root
        full_path = os.path.abspath(os.path.join(self.workspace_root, path))
        if not full_path.startswith(self.workspace_root):
            return ToolResult(content="", status="error", error="Security violation: path outside workspace")

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            return ToolResult(content=content)
        except Exception as e:
            return ToolResult(content="", status="error", error=str(e))

class FileWriteTool(BaseTool):
    """Writes content to a file in the jailed workspace."""
    
    def __init__(self, workspace_root: str):
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

    async def run(self, path: str, content: str, **kwargs) -> ToolResult:
        full_path = os.path.abspath(os.path.join(self.workspace_root, path))
        if not full_path.startswith(self.workspace_root):
            return ToolResult(content="", status="error", error="Security violation: path outside workspace")

        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(content=f"Successfully wrote to {path}")
        except Exception as e:
            return ToolResult(content="", status="error", error=str(e))
