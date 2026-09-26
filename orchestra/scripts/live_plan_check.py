"""Live plan-validity check: run sample tasks through real planning.

Usage: .venv/bin/python scripts/live_plan_check.py --provider openrouter --limit 20

Writes evals/output/plan_validity.json with the validity rate and failures.
Phase 2 exit criterion: at least 95% of 20 tasks produce a valid plan.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.supervisor import SupervisorAgent  # noqa: E402
from graph.validate import validate_plan  # noqa: E402
from llm.factory import build_provider  # noqa: E402

SAMPLE_TASKS = [
    "Compare pgvector, ChromaDB and Qdrant for a 10M-document RAG workload and write a two-page recommendation.",
    "Research the current state of open-weight LLMs and summarize the top five by benchmark score.",
    "Analyze monthly sales data and produce a trend summary with three actionable insights.",
    "Write and execute Python code to parse a CSV of user signups and report weekly growth.",
    "Summarize the key arguments for and against remote work, citing at least four sources.",
    "Build a checklist for launching a production API, ordered by risk.",
    "Estimate the cost of running a 24/7 GPU inference service and show the assumptions.",
    "Compare three project management methodologies for a five-person startup.",
    "Research vector database indexing strategies and recommend one for low-latency search.",
    "Turn a rough product idea into a one-page spec with acceptance criteria.",
    "Analyze the tradeoffs of microservices versus a modular monolith for a small team.",
    "Write a Python script that detects duplicate rows in a CSV and reports counts.",
    "Survey the latest developments in agent evaluation and list five takeaways.",
    "Draft a technical blog post explaining checkpointing in workflow engines.",
    "Research rate-limiting strategies and recommend one for a public REST API.",
    "Compute summary statistics for a provided dataset and flag outliers.",
    "Compare two deployment options (single VM vs containers) for a demo app.",
    "Write a runbook for recovering from a database outage, step by step.",
    "Research prompt-injection defenses and rank them by implementation cost.",
    "Produce a 10-question interview guide for a backend engineer role.",
]


async def run(provider_name: str, limit: int) -> int:
    os.environ["LLM_PROVIDER"] = provider_name
    provider = build_provider()
    supervisor = SupervisorAgent(provider)

    results = []
    for task in SAMPLE_TASKS[:limit]:
        try:
            plan = await supervisor.create_plan(task)
            errors = validate_plan([t.model_dump() for t in plan.tasks])
        except Exception as exc:  # noqa: BLE001 - reported per task
            errors = [f"exception: {exc}"]
        results.append({"task": task, "valid": not errors, "errors": errors})

    valid = sum(1 for r in results if r["valid"])
    rate = valid / len(results) if results else 0.0
    report = {
        "provider": provider_name,
        "count": len(results),
        "valid": valid,
        "rate": rate,
        "results": results,
    }
    output = ROOT / "evals" / "output" / "plan_validity.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"plan validity: {valid}/{len(results)} ({rate:.0%})")
    for result in results:
        if not result["valid"]:
            print(f"  INVALID: {result['task'][:60]} -> {result['errors']}")
    return 0 if rate >= 0.95 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="openrouter")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.provider, args.limit)))
