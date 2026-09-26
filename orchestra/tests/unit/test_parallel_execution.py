import json
import time

import pytest

from agents.reviewer import ReviewResult, ReviewScore
from graph.build import OrchestraGraph
from llm.fake import FakeProvider

PLAN = json.dumps({
    "tasks": [
        {"id": f"t{i}", "description": f"independent task {i}",
         "specialist": "researcher", "dependencies": []}
        for i in range(1, 5)
    ],
    "reasoning": "four independent lookups",
    "confidence": 0.9,
})

BASE_STATE = {
    "task_id": "task-1",
    "task_description": "four parallel lookups",
    "plan": None,
    "results": {},
    "attempts": {},
    "review_feedback": {},
    "shared_context": "",
    "final_response": None,
}


@pytest.mark.asyncio
async def test_parallel_independent_subtasks_run_concurrently(monkeypatch):
    monkeypatch.setenv("FAKE_DELAY_SECONDS", "0.2")
    provider = FakeProvider()
    provider.set_scripted_response("Orchestra Supervisor", PLAN)
    graph = OrchestraGraph(provider)

    # Reviewers must not add their own delay to the measurement.
    async def instant_accept(task_description, specialist_output, specialist_role):
        return ReviewResult(
            scores=ReviewScore(correctness=1.0, completeness=1.0, format=1.0, sources=1.0),
            feedback="ok",
            decision="accept",
        )

    graph.reviewer.review = instant_accept

    active = 0
    max_active = 0
    for agent in graph.specialists.values():
        original = agent.run

        async def wrapped(task_description, context, executor=None, _original=original):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                return await _original(task_description, context, executor=executor)
            finally:
                active -= 1

        agent.run = wrapped

    start = time.monotonic()
    final = await graph.workflow.ainvoke(BASE_STATE)
    elapsed = time.monotonic() - start

    assert sorted(final["results"]) == ["t1", "t2", "t3", "t4"]
    assert all(result.status == "accepted" for result in final["results"].values())
    assert max_active == 4, "all four independent subtasks must overlap"
    # plan (0.2) + one parallel batch (0.2) + synthesize (0.2) ≈ 0.6s;
    # sequential execution would need at least 4 * 0.2 + 0.4 = 1.2s.
    assert elapsed < 1.0, f"parallel run took {elapsed:.2f}s"
