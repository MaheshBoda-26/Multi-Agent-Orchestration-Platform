import json

import pytest

from graph.build import OrchestraGraph, MAX_SUBTASK_ATTEMPTS
from graph.validate import validate_plan
from llm.fake import FakeProvider


def _plan(tasks, confidence=0.9):
    return json.dumps({"tasks": tasks, "reasoning": "test plan", "confidence": confidence})


def _review(decision, scores=None):
    scores = scores or {"correctness": 0.9, "completeness": 0.9, "format": 0.9, "sources": 0.8}
    return json.dumps({
        "scores": scores,
        "feedback": "test feedback",
        "decision": decision,
        "retry_instructions": "do better",
    })


BASE_STATE = {
    "task_id": "task-1",
    "task_description": "Compare databases and write a recommendation",
    "plan": None,
    "results": {},
    "attempts": {},
    "review_feedback": {},
    "shared_context": "",
    "final_response": None,
}


class RecordingGraph(OrchestraGraph):
    """Records which subtasks actually reached the executor, in order."""

    def __init__(self, *args, **kwargs):
        self.execution_order = []
        super().__init__(*args, **kwargs)

    async def node_execute_subtask(self, payload):
        self.execution_order.append(payload["subtask"]["id"])
        return await super().node_execute_subtask(payload)


# ------------------------------------------------------------- plan validator

def test_plan_rejects_cycles():
    errors = validate_plan([
        {"id": "a", "description": "a", "specialist": "writer", "dependencies": ["b"]},
        {"id": "b", "description": "b", "specialist": "writer", "dependencies": ["a"]},
    ])
    assert any("cycle" in e for e in errors)


def test_plan_rejects_unknown_specialist():
    errors = validate_plan([
        {"id": "a", "description": "a", "specialist": "lawyer", "dependencies": []},
    ])
    assert any("unknown specialist" in e for e in errors)


def test_plan_rejects_missing_dependency_and_accepts_valid_dag():
    bad = validate_plan([
        {"id": "a", "description": "a", "specialist": "writer", "dependencies": ["ghost"]},
    ])
    assert any("unknown subtask" in e for e in bad)

    good = validate_plan([
        {"id": "a", "description": "a", "specialist": "researcher", "dependencies": []},
        {"id": "b", "description": "b", "specialist": "writer", "dependencies": ["a"]},
    ])
    assert good == []


# --------------------------------------------------------------- graph flows

@pytest.mark.asyncio
async def test_graph_runs_end_to_end_with_fake_provider():
    graph = RecordingGraph(FakeProvider())
    final = await graph.workflow.ainvoke(BASE_STATE)

    assert final["final_response"]
    assert final["results"]["t1"].status == "accepted"
    assert final["results"]["t2"].status == "accepted"
    assert final["attempts"] == {"t1": 1, "t2": 1}
    assert sorted(graph.execution_order) == ["t1", "t2"]


@pytest.mark.asyncio
async def test_dependent_subtasks_run_once_after_dependencies_are_accepted():
    provider = FakeProvider()
    provider.set_scripted_response("Orchestra Supervisor", _plan([
        {"id": "t1", "description": "research a", "specialist": "researcher", "dependencies": []},
        {"id": "t2", "description": "research b", "specialist": "researcher", "dependencies": []},
        {"id": "t3", "description": "analyse", "specialist": "data_analyst", "dependencies": ["t1", "t2"]},
        {"id": "t4", "description": "write", "specialist": "writer", "dependencies": ["t3"]},
    ]))
    graph = RecordingGraph(provider)

    calls = []
    for name, agent in graph.specialists.items():
        original = agent.run

        async def wrapped(task_description, context, _name=name, _original=original):
            calls.append(_name)
            return await _original(task_description, context)

        agent.run = wrapped

    final = await graph.workflow.ainvoke(BASE_STATE)

    assert sorted(final["results"]) == ["t1", "t2", "t3", "t4"]
    assert all(r.status == "accepted" for r in final["results"].values())
    # Every subtask ran exactly once, and dependents only after their deps were accepted.
    assert graph.execution_order[2:] == ["t3", "t4"]
    assert sorted(graph.execution_order[:2]) == ["t1", "t2"]
    assert calls.count("researcher") == 2
    assert calls.count("data_analyst") == 1
    assert final["final_response"]


@pytest.mark.asyncio
async def test_retry_stops_at_cap_and_escalates_instead_of_looping():
    provider = FakeProvider()
    provider.set_scripted_response("Orchestra Supervisor", _plan([
        {"id": "t1", "description": "write it", "specialist": "writer", "dependencies": []},
    ]))
    provider.set_scripted_response("quality reviewer evaluating", _review(
        "retry",
        scores={"correctness": 0.2, "completeness": 0.2, "format": 0.2, "sources": 0.1},
    ))
    graph = RecordingGraph(provider)

    final = await graph.workflow.ainvoke(BASE_STATE)

    assert graph.execution_order == ["t1"] * MAX_SUBTASK_ATTEMPTS
    assert final["results"]["t1"].status == "escalate"
    assert final["attempts"]["t1"] == MAX_SUBTASK_ATTEMPTS
    # The run still delivers a final response rather than hanging.
    assert final["final_response"]


@pytest.mark.asyncio
async def test_low_confidence_plan_does_not_interrupt_without_checkpointer():
    provider = FakeProvider()
    provider.set_scripted_response("Orchestra Supervisor", _plan([
        {"id": "t1", "description": "write it", "specialist": "writer", "dependencies": []},
    ], confidence=0.1))
    graph = RecordingGraph(provider, hitl_enabled=False)

    final = await graph.workflow.ainvoke(BASE_STATE)
    assert final["results"]["t1"].status == "accepted"
