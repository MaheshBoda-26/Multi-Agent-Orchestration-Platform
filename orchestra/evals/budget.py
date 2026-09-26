"""Budget guard for the eval matrix (Phase 9).

Live OpenRouter runs are priced from ``config/routing.yaml`` (the only pricing
source). The budget charges every response's token usage before the next task
starts and aborts the current config with a clear error once the running total
crosses the cap, so a runaway matrix can never overspend.
"""
from typing import Dict, Tuple


class BudgetExceeded(RuntimeError):
    """The running eval cost crossed the configured cap."""


class Budget:
    """Accumulates USD spend and trips a cap with an actionable message."""

    def __init__(self, max_usd: float) -> None:
        if max_usd <= 0:
            raise ValueError("budget cap must be positive")
        self.max_usd = max_usd
        self.spent_usd = 0.0

    def charge(self, cost_usd: float, label: str = "") -> None:
        """Add one response's cost; raises BudgetExceeded past the cap."""
        self.spent_usd += float(cost_usd or 0.0)
        if self.spent_usd > self.max_usd:
            raise BudgetExceeded(
                f"Eval budget exceeded: ${self.spent_usd:.4f} spent, cap "
                f"${self.max_usd:.2f}. Last charged item: {label or 'unknown'}. "
                "Re-run with a higher --budget-max only after reviewing the spend."
            )

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.max_usd - self.spent_usd)


def estimate_cost(
    tokens_prompt: int, tokens_completion: int, per_million: Tuple[float, float]
) -> float:
    """USD cost for one response at routing.yaml per-million prices."""
    prompt_price, completion_price = per_million
    return (tokens_prompt * prompt_price + tokens_completion * completion_price) / 1_000_000


def budget_from_routing(max_usd: float, routing_costs: Dict[str, Tuple[float, float]]) -> "Budget":
    """A Budget priced against routing.yaml costs (kept for wiring clarity)."""
    del routing_costs  # pricing happens per response via estimate_cost
    return Budget(max_usd)
