import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from graph.build import OrchestraGraph
from llm.fake import FakeProvider
from tools.execution import ApprovalRequired, tool_signature
from tools.registry import ToolResult

BASE = {
    "task_id": "approval-task",
    "task_description": "do the thing",
    "plan": None,
    "plan_confidence": 1.0,
    "results": {},
    "attempts": {},
    "review_feedback": {},
    "shared_context": "",
    "final_response": None,
}


def _plan(tasks, confidence=0.9):
    return json.dumps({"tasks": tasks, "reasoning": "plan", "confidence": confidence})


def _turn(answer=None, tool=None, arguments=None):
    payload = {"thought": "ok"}
    if tool:
        payload["tool_call"] = {"tool": tool, "arguments": arguments or {}}
    if answer:
        payload["final_answer"] = answer
    return json.dumps(payload)


DEFAULT_TASKS = [
    {"id": "t1", "description": "gather", "specialist": "researcher", "dependencies": []},
]


class SpecialistTurnProvider(FakeProvider):
    """Sequences specialist turns while delegating planner/reviewer prompts."""

    def __init__(self, turns):
        super().__init__()
        self._turns = list(turns)

    async def complete_structured(self, prompt, response_model, **kwargs):
        delegated = (
            "Orchestra Supervisor" in prompt
            or "quality reviewer" in prompt
            or "Synthesize the final response" in prompt
        )
        if delegated:
            return await super().complete_structured(prompt, response_model, **kwargs)
        return response_model.model_validate(self._turns.pop(0))


def _graph(provider, executor=None, thread="t-1"):
    graph = OrchestraGraph(provider, checkpointer=InMemorySaver(), tool_executor=executor)
    config = {"configurable": {"thread_id": thread}}
    return graph, config


@pytest.mark.asyncio
async def test_low_confidence_plan_pauses_for_approval():
    provider = FakeProvider()
    provider.set_scripted_response("Orchestra Supervisor", _plan(DEFAULT_TASKS, confidence=0.2))
    graph, config = _graph(provider)

    first = await graph.workflow.ainvoke(BASE, config)

    interrupts = first.get("__interrupt__")
    assert interrupts, "low-confidence plan must pause"
    payload = interrupts[0].value
    assert payload["escalation_level"] == "approve_plan"
    assert payload["trigger"] == "low_confidence_plan"

    final = await graph.workflow.ainvoke(Command(resume={"action": "approve"}), config)
    assert final["final_response"]
    assert final["results"]["t1"].status == "accepted"


@pytest.mark.asyncio
async def test_human_can_modify_the_plan_before_execution():
    provider = FakeProvider()
    provider.set_scripted_response("Orchestra Supervisor", _plan(DEFAULT_TASKS, confidence=0.2))
    graph, config = _graph(provider, thread="t-modify")

    await graph.workflow.ainvoke(BASE, config)
    modified = [{"id": "m1", "description": "human edited", "specialist": "writer", "dependencies": []}]
    final = await graph.workflow.ainvoke(
        Command(resume={"action": "modify", "plan": modified}), config
    )

    assert sorted(final["results"]) == ["m1"]
    assert final["results"]["m1"].status == "accepted"


@pytest.mark.asyncio
async def test_rejecting_or_taking_over_ends_the_run_cleanly():
    for action, expected in (("reject", "rejected"), ("take_over", "took over")):
        provider = FakeProvider()
        provider.set_scripted_response(
            "Orchestra Supervisor", _plan(DEFAULT_TASKS, confidence=0.2)
        )
        graph, config = _graph(provider, thread=f"t-{action}")

        await graph.workflow.ainvoke(BASE, config)
        final = await graph.workflow.ainvoke(Command(resume={"action": action}), config)

        assert expected in (final["final_response"] or "").lower()
        assert not final.get("results")


TOOL_CALL = {"thought": "use the tool", "tool_call": {"tool": "file_write", "arguments": {"path": "x.txt", "content": "hi"}}}


@pytest.mark.asyncio
async def test_sensitive_tool_requires_approval_then_executes():
    provider = SpecialistTurnProvider([TOOL_CALL, TOOL_CALL, {"final_answer": "written"}])
    provider.set_scripted_response("Orchestra Supervisor", _plan(DEFAULT_TASKS))

    calls = []

    async def executor(**kwargs):
        calls.append(kwargs)
        signature = tool_signature(
            kwargs["subtask_id"], kwargs["tool_name"], kwargs["arguments"]
        )
        if kwargs.get("approved_signature") != signature:
            raise ApprovalRequired(kwargs["tool_name"], kwargs["arguments"], signature)
        return ToolResult(content="written to x.txt")

    graph, config = _graph(provider, executor=executor, thread="t-sensitive")

    first = await graph.workflow.ainvoke(BASE, config)

    interrupts = first.get("__interrupt__")
    assert interrupts, "sensitive tool must pause for approval"
    payload = interrupts[0].value
    assert payload["escalation_level"] == "approve_action"
    assert payload["context"]["tool_name"] == "file_write"
    assert len(calls) == 1, "the tool did not run before approval"

    final = await graph.workflow.ainvoke(Command(resume={"action": "approve"}), config)

    assert final["results"]["t1"].status == "accepted"
    assert final["results"]["t1"].content == "written"
    assert len(calls) == 2, "the approved call ran exactly once"


@pytest.mark.asyncio
async def test_rejected_sensitive_tool_is_reported_not_executed():
    provider = SpecialistTurnProvider([
        TOOL_CALL, TOOL_CALL, {"final_answer": "could not write"}
    ])
    provider.set_scripted_response("Orchestra Supervisor", _plan(DEFAULT_TASKS))

    calls = []

    async def executor(**kwargs):
        calls.append(kwargs)
        return ToolResult(content="should not happen")

    graph, config = _graph(provider, executor=executor, thread="t-reject-tool")

    await graph.workflow.ainvoke(BASE, config)
    final = await graph.workflow.ainvoke(Command(resume={"action": "reject"}), config)

    assert final["results"]["t1"].content == "could not write"
    assert len(calls) == 1, "the rejected tool must not be handed to the executor again"


@pytest.mark.asyncio
async def test_repeated_failure_asks_a_human():
    provider = FakeProvider()
    provider.set_scripted_response("Orchestra Supervisor", _plan(DEFAULT_TASKS))
    graph, config = _graph(provider, thread="t-failure")

    async def always_fail(task_description, context, executor=None):
        raise RuntimeError("boom")

    graph.specialists["researcher"].run = always_fail

    first = await graph.workflow.ainvoke(BASE, config)

    interrupts = first.get("__interrupt__")
    assert interrupts, "a twice-failed subtask must ask a human"
    payload = interrupts[0].value
    assert payload["trigger"] == "second_failure"
    assert payload["context"]["subtask_id"] == "t1"

    final = await graph.workflow.ainvoke(Command(resume={"action": "approve"}), config)
    assert final["results"]["t1"].status == "accepted"
    assert final["final_response"]
