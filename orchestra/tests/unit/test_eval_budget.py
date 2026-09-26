"""Budget guard: charging, cap trip, and matrix abort behavior."""
import pytest

from evals.budget import Budget, BudgetExceeded, estimate_cost
from evals.run import run_config
from evals.build_task_set import build_task_set
from llm.fake import FakeProvider


def test_budget_charges_and_trips_with_actionable_message():
    budget = Budget(1.0)
    budget.charge(0.4, "task-1")
    budget.charge(0.5, "task-2")
    assert budget.remaining_usd == pytest.approx(0.1)

    with pytest.raises(BudgetExceeded) as excinfo:
        budget.charge(0.2, "task-3")
    assert "task-3" in str(excinfo.value)
    assert "$1.1000" in str(excinfo.value) and "cap $1.00" in str(excinfo.value)


def test_budget_rejects_nonpositive_cap():
    with pytest.raises(ValueError):
        Budget(0)


def test_estimate_cost_uses_per_million_prices():
    # gpt-4o-mini: $0.15 prompt / $0.60 completion per 1M tokens.
    cost = estimate_cost(1_000_000, 500_000, (0.15, 0.60))
    assert cost == pytest.approx(0.15 + 0.30)


@pytest.mark.asyncio
async def test_matrix_config_aborts_when_budget_trips(tmp_path, monkeypatch):
    monkeypatch.setattr("evals.run.RESULTS_DIR", tmp_path)

    # Price fake responses as if they were 1M-token calls, through a
    # routing-aware wrapper so the budget charges them: the second task must
    # trip the $1 cap and abort the config with partial results.
    class RoutingAware:
        def __init__(self, inner):
            self._inner = inner

        def model_for(self, role=None, override=None):
            return "openai/gpt-4o-mini"

        def __getattr__(self, name):
            return getattr(self._inner, name)

    class PricedFake(FakeProvider):
        async def complete(self, prompt, **kwargs):
            response = await super().complete(prompt, **kwargs)
            response.tokens_prompt = 4_000_000  # $0.60/call at gpt-4o-mini prices
            response.tokens_completion = 0
            return response

    provider = RoutingAware(PricedFake())
    summary = await run_config(
        "full", repeat=0, provider=provider,
        tasks=build_task_set()[:4], budget=Budget(1.0),
    )
    assert summary["aborted"] is not None
    assert "budget exceeded" in summary["aborted"].lower()
    assert summary["tasks"] == 1, "abort before recording the charge that trips the cap"
    assert summary["budget_spent_usd"] == pytest.approx(1.2), "the tripping charge is still accounted"


@pytest.mark.asyncio
async def test_config_completes_within_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("evals.run.RESULTS_DIR", tmp_path)
    summary = await run_config(
        "full", repeat=0, provider=FakeProvider(),
        tasks=build_task_set()[:5], budget=Budget(40.0),
    )
    assert summary["aborted"] is None
    assert summary["tasks"] == 5
    assert summary["budget_spent_usd"] == 0.0, "non-routing fakes are never priced"
