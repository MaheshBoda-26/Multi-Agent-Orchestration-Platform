"""Specialist agents.

Each specialist runs a bounded LLM loop: the model either requests a tool from
its allowlist (executed through the audited executor) or returns a final
answer. The loop is capped so a confused model can never spin forever.
"""
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from graph.sanitize import defense_system_note, sanitize_tool_output
from llm.provider import LLMProvider
from tools.registry import ToolResult

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5


class ToolCall(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class SpecialistTurn(BaseModel):
    thought: str = ""
    tool_call: Optional[ToolCall] = None
    final_answer: Optional[str] = None


ToolExecutor = Callable[[ToolCall], Awaitable[ToolResult]]


class AgentConfig(BaseModel):
    name: str
    role: str
    instructions: str
    allowed_tools: List[str]
    model_override: Optional[str] = None


class SpecialistAgent:
    """A specialized agent with a specific role and set of tools."""

    def __init__(self, config: AgentConfig, llm: LLMProvider):
        self.config = config
        self.llm = llm

    def _tool_menu(self) -> str:
        if not self.config.allowed_tools:
            return "(no tools)"
        return "\n".join(f"- {name}" for name in self.config.allowed_tools)

    def _build_prompt(
        self,
        task_description: str,
        context: str,
        observations: List[str],
    ) -> str:
        prompt = (
            f"Role: {self.config.role}\n"
            f"Instructions: {self.config.instructions}\n\n"
            f"{defense_system_note()}\n\n"
            f"Available tools:\n{self._tool_menu()}\n\n"
            f"Context: {context}\n"
            f"Task: {task_description}\n"
        )
        if observations:
            prompt += "\nTool observations so far:\n" + "\n".join(observations) + "\n"
        prompt += (
            "\nRespond with JSON matching the SpecialistTurn schema: either a "
            "tool_call (tool plus arguments) or a final_answer containing your "
            "complete output."
        )
        return prompt

    async def run(
        self,
        task_description: str,
        context: str,
        executor: Optional[ToolExecutor] = None,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> str:
        observations: List[str] = []
        for _ in range(max_iterations):
            turn = await self.llm.complete_structured(
                self._build_prompt(task_description, context, observations),
                SpecialistTurn,
                role="specialist",
                model=self.config.model_override,
            )
            if turn.final_answer:
                return turn.final_answer
            if turn.tool_call is None:
                return turn.thought or "No output produced."
            observations.append(await self._invoke(executor, turn.tool_call))
        logger.warning(
            "Specialist %s hit the %s-iteration tool cap", self.config.name, max_iterations
        )
        return observations[-1] if observations else "No output produced."

    async def _invoke(
        self, executor: Optional[ToolExecutor], tool_call: ToolCall
    ) -> str:
        if executor is None:
            return f"Tool {tool_call.tool} is not available in this run."
        result = await executor(tool_call)
        body = result.content if result.status == "success" else (result.error or "")
        status = f"Tool {tool_call.tool} -> {result.status}\n"
        if result.status != "success":
            # Errors are system-generated; keep them legible, unframed.
            return (status + body).strip()
        sanitized = sanitize_tool_output(tool_call.tool, body)
        if sanitized["flagged"]:
            logger.warning(
                "Tool %s returned instruction-like content: %s",
                tool_call.tool,
                "; ".join(sanitized["suspicious"][:3]),
            )
        return (status + sanitized["content"]).strip()


# Definitions for the 4 required specialists
SPECIALIST_CONFIGS = {
    "researcher": AgentConfig(
        name="researcher",
        role="Expert Researcher",
        instructions="Find accurate, up-to-date information using web search and HTTP tools. Synthesize findings into a structured report with sources.",
        allowed_tools=["web_search", "http_get", "file_read"]
    ),
    "data_analyst": AgentConfig(
        name="data_analyst",
        role="Data Analysis Specialist",
        instructions="Analyze provided datasets or files. Use the code executor to perform calculations, generate statistics, and create data summaries.",
        allowed_tools=["code_execute", "file_read", "file_write"]
    ),
    "writer": AgentConfig(
        name="writer",
        role="Professional Content Writer",
        instructions="Transform technical findings or analysis into polished, high-quality documents. Ensure clarity, correct tone, and proper formatting.",
        allowed_tools=["file_read", "file_write"]
    ),
    "code_executor": AgentConfig(
        name="code_executor",
        role="Software Engineering Agent",
        instructions="Write and execute Python code to solve technical problems or automate tasks. Verify your code works before submitting.",
        allowed_tools=["code_execute", "file_read", "file_write"]
    )
}
