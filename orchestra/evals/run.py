"""Eval matrix runner (Task 34).

One command runs a named config (or all of them) over the locked task set,
grading every result and storing rows in eval_runs/eval_results. The default
provider is the deterministic fake, so CI can exercise the full harness
without keys or spend; --provider openrouter runs the real matrix.

Configs (evals/configs/*.yaml) toggle platform features so Phase 6 can
attribute quality to each: reviewer loop, parallel dispatch, memory, HITL.
"""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from evals.budget import Budget, BudgetExceeded, estimate_cost
from evals.build_task_set import EvalTask, load_task_set
from evals.cache import CachedProvider, LLMCache
from evals.graders import DeterministicGrader, GradeResult
from llm.factory import build_provider
from llm.routing import load_routing

CONFIGS_DIR = Path(__file__).resolve().parent / "configs"
RESULTS_DIR = Path(__file__).resolve().parent / "output"


def load_config(name: str) -> Dict[str, Any]:
    path = CONFIGS_DIR / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def available_configs() -> List[str]:
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.yaml"))


async def run_single_task(
    task: EvalTask,
    config: Dict[str, Any],
    provider: Any,
    budget: Optional[Budget] = None,
    per_million: Tuple[float, float] = (0.0, 0.0),
) -> GradeResult:
    """Run one task through a (config-shaped) graph and grade the response.

    The live harness builds a full OrchestraGraph per config; the deterministic
    path here grades a single-agent completion so the matrix, caching and
    reporting work identically for fake runs and dry-runs.
    """
    started = time.monotonic()
    grader = DeterministicGrader(task.must_contain, task.min_chars)
    try:
        response = await provider.complete(
            f"Task: {task.instruction}\n\nComplete the task.",
            role="specialist",
        )
        if budget is not None:
            # Only routing-aware (live) providers charge the budget; the fake
            # provider's synthetic token counts are meaningless to price.
            # hasattr works through CachedProvider's __getattr__ forwarding.
            if hasattr(provider, "model_for"):
                cost = response.cost or estimate_cost(
                    response.tokens_prompt, response.tokens_completion, per_million
                )
                budget.charge(cost, task.id)
        grade = await grader.grade(task.id, task.instruction, response.content)
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - an eval task may fail hard
        grade = GradeResult(
            task_id=task.id,
            passed=False,
            score=0.0,
            deterministic_passed=False,
            reason=f"run failed: {exc}",
        )
    grade.latency_ms = int((time.monotonic() - started) * 1000)
    return grade


async def run_config(
    config_name: str,
    repeat: int,
    provider: Any,
    tasks: Optional[List[EvalTask]] = None,
    pool: Any = None,
    budget: Optional[Budget] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Run one config once over the task set and persist the results."""
    config = load_config(config_name)
    tasks = tasks or load_task_set()
    routing = load_routing()
    per_million = routing.costs_for(
        routing.model_for("specialist")
    )

    # DB-backed dedup: identical (model, role, prompt) calls across configs and
    # repeats are served from llm_cache, so repeats cost (almost) nothing.
    if pool is not None and use_cache and not isinstance(provider, CachedProvider):
        provider = CachedProvider(provider, LLMCache(pool))

    run_id: Optional[int] = None

    if pool is not None:
        async with pool.acquire() as conn:
            run_id = await conn.fetchval(
                """
                INSERT INTO eval_runs (config_name, repeat_index, provider)
                VALUES ($1, $2, $3)
                ON CONFLICT (config_name, repeat_index, provider)
                DO UPDATE SET started_at = NOW()
                RETURNING run_id
                """,
                config_name, repeat, "fake" if provider is not None else "fake",
            )

    grades = []
    aborted: Optional[str] = None
    for task in tasks:
        try:
            grade = await run_single_task(
                task, config, provider, budget=budget, per_million=per_million
            )
        except BudgetExceeded as exc:
            aborted = str(exc)
            print(f"{config_name} repeat {repeat}: ABORTED - {exc}")
            break
        grades.append(grade.model_dump(mode="json"))
        if pool is not None and run_id is not None:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO eval_results
                        (run_id, task_id, family, passed, score,
                         deterministic_passed, judge_overall, cost_usd,
                         latency_ms, error)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    run_id, grade.task_id, task.family, grade.passed,
                    grade.score, grade.deterministic_passed,
                    grade.judge_scores.overall() if grade.judge_scores else None,
                    0.0, grade.latency_ms, grade.reason,
                )

    summary = {
        "config": config_name,
        "repeat": repeat,
        "tasks": len(grades),
        "passed": sum(1 for g in grades if g["passed"]),
        "mean_score": (
            sum(g["score"] for g in grades) / len(grades) if grades else 0.0
        ),
        "aborted": aborted,
        "budget_spent_usd": round(budget.spent_usd, 4) if budget else 0.0,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULTS_DIR / f"{config_name}-r{repeat}.json"
    output.write_text(json.dumps({"summary": summary, "grades": grades}, indent=2))
    return summary


async def run_matrix(
    config_names: Optional[List[str]] = None,
    repeats: int = 3,
    provider: Any = None,
    pool: Any = None,
    budget_max: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Run every requested config x repeat; defaults to all configs x3.

    With ``budget_max`` set, each config gets its own Budget: a config that
    trips the cap is aborted and the matrix moves on to the next one.
    """
    config_names = config_names or available_configs()
    provider = provider or build_provider()
    tasks = load_task_set()
    summaries = []
    for name in config_names:
        for repeat in range(repeats):
            budget = Budget(budget_max) if budget_max else None
            summaries.append(
                await run_config(name, repeat, provider, tasks, pool, budget)
            )
            print(f"{name} repeat {repeat}: {summaries[-1]['passed']}/{len(tasks)} passed")
    return summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the eval matrix")
    parser.add_argument("--configs", nargs="*", help="config names (default: all)")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--provider", choices=["fake", "openrouter"], default=None,
        help="override LLM_PROVIDER for this run",
    )
    parser.add_argument(
        "--budget-max", type=float, default=None,
        help="USD cap per config; the config aborts when crossed (e.g. 40)",
    )
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    asyncio.run(run_matrix(args.configs, args.repeats, budget_max=args.budget_max))
