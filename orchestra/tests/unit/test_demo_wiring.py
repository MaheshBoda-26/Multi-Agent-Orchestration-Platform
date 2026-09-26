"""Regression tests for the clean-machine demo fixes (Phase 9, Task 49)."""
import json

from llm.fake import FakeProvider
from worker.tasks import initial_state


def test_initial_state_carries_user_id():
    state = initial_state("tid", "desc", "demo-user")
    assert state["user_id"] == "demo-user"
    assert state["task_description"] == "desc"
    # Memory scoping depends on this reaching the graph.
    assert "plan" in state and "results" in state


def test_fake_plan_path_only_applies_to_marked_tasks(tmp_path, monkeypatch):
    """One worker serves mixed traffic: [HITL-DEMO] plans low-confidence,
    everything else keeps the default confident plan."""
    monkeypatch.setenv("FAKE_PLAN_PATH", str(tmp_path / "plan.json"))
    (tmp_path / "plan.json").write_text(json.dumps({
        "tasks": [{"id": "t1", "description": "x", "specialist": "researcher",
                   "dependencies": []}],
        "reasoning": "r", "confidence": 0.35,
    }))

    provider = FakeProvider()

    marked_plan = json.loads(
        provider._find_matching_response(
            "You are the Orchestra Supervisor.\nTask: [HITL-DEMO] uncertain ask\n"
        )
    )
    assert marked_plan["confidence"] == 0.35, "marked task uses the scripted plan"

    default_plan = json.loads(
        provider._find_matching_response(
            "You are the Orchestra Supervisor.\nTask: ordinary request\n"
        )
    )
    assert default_plan["confidence"] == 0.9, "unmarked tasks keep the default plan"


def test_fake_plan_path_default_plan_still_intact(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PLAN_PATH", str(tmp_path / "plan.json"))
    (tmp_path / "plan.json").write_text(
        json.dumps({"tasks": [], "reasoning": "r", "confidence": 0.2})
    )
    provider = FakeProvider()
    assert "Orchestra Supervisor" in provider.default_responses
    assert "[HITL-DEMO]" in provider.default_responses
    assert list(provider.default_responses)[0] == "[HITL-DEMO]", (
        "marker must be matched first"
    )
