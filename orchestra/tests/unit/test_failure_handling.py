import json

import pytest

from graph.build import MAX_SUBTASK_ATTEMPTS, OrchestraGraph
from llm.fake import FakeProvider

BASE_STATE = {
    "task_id": "task-1",
    "task_description": "research then write",
    "plan": None,
    "results": {},
    "attempts": {},
    "review_feedback": {},
    "shared_context": "",
    "final_response": None,
}

PLAN = json.dumps({
    "tasks": [
        {"id": "t1", "description": "gather info", "specialist": "researcher", "dependencies": []},
        {"id": "t2", "description": "write it", "specialist": "writer", "dependencies": ["t1"]},
    ],
    "reasoning": "research first",
    "confidence": 0.9,
})


@pytest.mark.asyncio
async def test_specialist_failure_is_retried_then_accepted():
    provider = FakeProvider()
    provider.set_scripted_response("Orchestra Supervisor", PLAN)
    graph = OrchestraGraph(provider)

    original = graph.specialists["researcher"].run
    calls = {"count": 0}

    async def flaky(task_description, context, executor=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient tool failure")
        return await original(task_description, context, executor=executor)

    graph.specialists["researcher"].run = flaky

    final = await graph.workflow.ainvoke(BASE_STATE)

    assert calls["count"] == 2, "the failed subtask should retry once"
    assert final["results"]["t1"].status == "accepted"
    assert final["attempts"]["t1"] == 2
    assert final["results"]["t2"].status == "accepted"


@pytest.mark.asyncio
async def test_second_failure_escalates_and_run_still_synthesizes():
    provider = FakeProvider()
    provider.set_scripted_response("Orchestra Supervisor", PLAN)
    graph = OrchestraGraph(provider)

    calls = {"count": 0}

    async def always_fail(task_description, context, executor=None):
        calls["count"] += 1
        raise RuntimeError("permanent failure")

    graph.specialists["researcher"].run = always_fail

    final = await graph.workflow.ainvoke(BASE_STATE)

    assert calls["count"] == MAX_SUBTASK_ATTEMPTS
    assert final["results"]["t1"].status == "escalate"
    assert final["final_response"], "the run still delivers a result"
