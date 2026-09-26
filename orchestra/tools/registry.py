import abc
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ToolSchema(BaseModel):
    """Schema for a tool's definition."""

    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema
    allowed_specialists: List[str] = Field(default_factory=list)
    rate_limit: Optional[int] = None  # Calls per minute


class ToolResult(BaseModel):
    """Standard response from a tool."""

    content: str
    status: str = "success"
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseTool(abc.ABC):
    """Abstract base class for all tools."""

    def __init__(self, schema: ToolSchema) -> None:
        self.schema = schema

    @abc.abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> ToolResult:
        """Execute the tool logic."""
        raise NotImplementedError


class ToolRegistry:
    """Central registry for managing and executing tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}
        self._usage: Dict[str, List[float]] = {}  # tool_name -> [timestamps]

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.schema.name] = tool
        logger.info("Registered tool: %s", tool.schema.name)

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolSchema]:
        return [tool.schema for tool in self._tools.values()]

    async def execute(self, name: str, specialist: str, **kwargs: Any) -> ToolResult:
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(content="", status="error", error=f"Tool {name} not found")

        # Permission check
        if tool.schema.allowed_specialists and specialist not in tool.schema.allowed_specialists:
            return ToolResult(
                content="", status="error",
                error=f"Specialist {specialist} not permitted to use {name}",
            )

        # Rate limiting
        if tool.schema.rate_limit and not self._check_rate_limit(name):
            return ToolResult(content="", status="error", error=f"Rate limit exceeded for {name}")

        try:
            logger.info("Executing tool %s for specialist %s with args %s", name, specialist, kwargs)
            return await tool.run(**kwargs)
        except Exception as e:
            logger.exception("Tool %s failed", name)
            return ToolResult(content="", status="error", error=str(e))

    def _check_rate_limit(self, name: str) -> bool:
        import time

        now = time.time()
        timestamps = [t for t in self._usage.get(name, []) if now - t < 60]

        tool = self.get_tool(name)
        if tool and tool.schema.rate_limit and len(timestamps) >= tool.schema.rate_limit:
            self._usage[name] = timestamps
            return False

        timestamps.append(now)
        self._usage[name] = timestamps
        return True


# Global registry instance
registry = ToolRegistry()
