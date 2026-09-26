"""Code execution tool backed by the Docker sandbox.

The previous in-process ``exec`` simulation is gone: code now runs inside a
container with no network, CPU/memory/pids limits, a read-only rootfs and only
the per-task workspace mounted writable. Never run real model output through a
weaker boundary than this.
"""
import asyncio
import logging
from typing import Any, Optional

from tools.registry import BaseTool, ToolResult, ToolSchema
from tools.sandbox_runner import DockerSandboxRunner

logger = logging.getLogger(__name__)

EXECUTION_TIMEOUT_SECONDS = 10


class CodeExecutionTool(BaseTool):
    def __init__(
        self,
        runner: Optional[DockerSandboxRunner] = None,
        workspace: Optional[str] = None,
    ) -> None:
        schema = ToolSchema(
            name="code_execute",
            description="Execute Python code in a secure sandbox.",
            parameters={"code": {"type": "string", "description": "Python code to execute"}},
            allowed_specialists=["code_executor", "data_analyst"],
        )
        super().__init__(schema)
        self.runner = runner or DockerSandboxRunner()
        self.workspace = workspace

    async def run(self, code: str = "", **kwargs: Any) -> ToolResult:
        if not code.strip():
            return ToolResult(content="", status="error", error="No code provided")

        result = await asyncio.to_thread(
            self.runner.run,
            code,
            workspace=self.workspace,
            timeout_seconds=EXECUTION_TIMEOUT_SECONDS,
        )

        if result.timed_out:
            return ToolResult(
                content="",
                status="error",
                error=f"Execution timed out after {EXECUTION_TIMEOUT_SECONDS}s",
            )
        if result.exit_code != 0:
            stderr = result.stderr.strip()
            return ToolResult(
                content=result.stdout,
                status="error",
                error=stderr or f"Execution failed with exit code {result.exit_code}",
            )
        return ToolResult(
            content=result.stdout or "Execution completed successfully (no output)."
        )
