from typing import Any, Dict, List

import pytest

from agents.specialists import SPECIALIST_CONFIGS, SpecialistAgent
from llm.fake import FakeProvider
from tools.registry import ToolResult


class ScriptedTurnProvider(FakeProvider):
    """Returns scripted SpecialistTurns in order and records every prompt."""

    def __init__(self, turns: List[Dict[str, Any]]):
        super().__init__()
        self._turns = list(turns)
        self.prompts: List[str] = []

    async def complete_structured(self, prompt: str, response_model: Any, **kwargs: Any) -> Any:
        self.prompts.append(prompt)
        return response_model.model_validate(self._turns.pop(0))


def _agent(provider: FakeProvider) -> SpecialistAgent:
    return SpecialistAgent(SPECIALIST_CONFIGS["researcher"], provider)


@pytest.mark.asyncio
async def test_tool_call_executes_and_result_is_fed_back():
    provider = ScriptedTurnProvider([
        {"thought": "read it", "tool_call": {"tool": "file_read", "arguments": {"path": "a.txt"}}},
        {"thought": "done", "final_answer": "final content"},
    ])
    calls = []

    async def executor(tool_call):
        calls.append(tool_call)
        return ToolResult(content="file body", status="success")

    result = await _agent(provider).run("read a.txt", "ctx", executor=executor)

    assert result == "final content"
    assert [call.tool for call in calls] == ["file_read"]
    assert calls[0].arguments == {"path": "a.txt"}
    assert "file body" in provider.prompts[1]


@pytest.mark.asyncio
async def test_failed_tool_feeds_error_back_and_loop_continues():
    provider = ScriptedTurnProvider([
        {"tool_call": {"tool": "ghost", "arguments": {}}},
        {"final_answer": "recovered"},
    ])

    async def executor(tool_call):
        return ToolResult(content="", status="error", error="Tool ghost not found")

    result = await _agent(provider).run("x", "", executor=executor)

    assert result == "recovered"
    assert "Tool ghost not found" in provider.prompts[1]


@pytest.mark.asyncio
async def test_loop_cap_returns_partial_output():
    provider = ScriptedTurnProvider([
        {"tool_call": {"tool": "file_read", "arguments": {"path": "a"}}}
        for _ in range(3)
    ])
    calls = []

    async def executor(tool_call):
        calls.append(tool_call)
        return ToolResult(content="observation data", status="success")

    result = await _agent(provider).run("x", "", executor=executor, max_iterations=2)

    assert len(calls) == 2
    assert "observation data" in result


@pytest.mark.asyncio
async def test_missing_executor_degrades_gracefully():
    provider = ScriptedTurnProvider([
        {"tool_call": {"tool": "file_read", "arguments": {}}},
        {"final_answer": "finished without tools"},
    ])

    result = await _agent(provider).run("x", "")

    assert result == "finished without tools"
    assert "not available" in provider.prompts[1]
