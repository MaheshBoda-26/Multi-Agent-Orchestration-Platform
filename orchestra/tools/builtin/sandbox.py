import sys
from io import StringIO
from typing import Any

from tools.registry import BaseTool, ToolResult, ToolSchema


class CodeExecutionTool(BaseTool):
    """Executes Python code.

    NOTE: this is still the in-process simulation. It runs code inside the API
    process with a redirected stdout, which is NOT a security boundary. It must
    be replaced by the Docker sandbox (no network, resource limits, read-only
    rootfs) before any real model reaches this tool.
    """

    def __init__(self) -> None:
        schema = ToolSchema(
            name="code_execute",
            description="Execute Python code in a secure sandbox.",
            parameters={"code": {"type": "string", "description": "Python code to execute"}},
            allowed_specialists=["code_executor", "data_analyst"],
        )
        super().__init__(schema)

    async def run(self, code: str = "", **kwargs: Any) -> ToolResult:
        old_stdout = sys.stdout
        captured = StringIO()
        sys.stdout = captured
        try:
            exec_globals: dict = {"__builtins__": __builtins__}
            exec(code, exec_globals)
            output = captured.getvalue()
        except Exception as e:
            return ToolResult(content="", status="error", error=f"Execution Error: {e}")
        finally:
            sys.stdout = old_stdout

        return ToolResult(content=output if output else "Execution completed successfully (no output).")
