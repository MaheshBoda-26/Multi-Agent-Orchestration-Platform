"""Single-agent baseline (Task 35).

Same tools and model as the full platform, but one agent does everything:
no supervisor plan, no specialists, no reviewer, no memory. The eval report
compares Orchestra's configs against this row.
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from evals.build_task_set import EvalTask, load_task_set
from evals.graders import DeterministicGrader, GradeResult
from llm.factory import build_provider

RESULTS_DIR = Path(__file__).resolve().parent / "output"


async def run_baseline(
    tasks: Optional[List[EvalTask]] = None,
    provider: Any = None,
    repeat: int = 0,
) -> Dict[str, Any]:
    tasks = tasks or load_task_set()
    provider = provider or build_provider()
    grader = DeterministicGrader([], 1)

    grades: List[Dict[str, Any]] = []
    total_cost = 0.0
    for task in tasks:
        started = time.monotonic()
        try:
            response = await provider.complete(
                f"You are a single agent with all tools available.\n"
                f"Task: {task.instruction}",
                role="specialist",
            )
            grade = await grader.grade(task.id, task.instruction, response.content)
            total_cost += getattr(response, "cost", 0.0) or 0.0
        except Exception as exc:  # noqa: BLE001
            grade = GradeResult(
                task_id=task.id, passed=False, score=0.0,
                deterministic_passed=False, reason=f"baseline failed: {exc}",
            )
        grade.latency_ms = int((time.monotonic() - started) * 1000)
        grades.append(grade.model_dump(mode="json"))

    summary = {
        "config": "baseline",
        "repeat": repeat,
        "tasks": len(grades),
        "passed": sum(1 for g in grades if g["passed"]),
        "mean_score": sum(g["score"] for g in grades) / len(grades) if grades else 0.0,
        "cost_usd": total_cost,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"baseline-r{repeat}.json").write_text(
        json.dumps({"summary": summary, "grades": grades}, indent=2)
    )
    return summary


if __name__ == "__main__":
    print(asyncio.run(run_baseline()))
