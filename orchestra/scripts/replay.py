"""Replay a completed Orchestra run with edited inputs (Task 41).

Usage:
    uv run python scripts/replay.py <task_id> --set task_description="New ask"
    uv run python scripts/replay.py <task_id> --set shared_context="Extra hint" --json

Loads the task's final checkpoint state, applies the edits, re-runs the graph
in a fresh checkpointer thread (the original stays intact) and prints the
divergence diff: which of plan / results / final_response changed.
"""
import argparse
import asyncio
import json
import os
import sys


def _parse_edits(pairs: list[str]) -> dict:
    edits = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--set expects field=value, got {pair!r}")
        field, value = pair.split("=", 1)
        edits[field] = value
    return edits


async def _run(task_id: str, edits: dict, as_json: bool) -> None:
    from graph.build import OrchestraGraph
    from graph.checkpointer import create_checkpointer
    from graph.replay import replay_task
    from llm.factory import build_provider

    ckpt_pool, checkpointer = await create_checkpointer(
        os.getenv("DATABASE_URL", "postgresql://orchestra:orchestra@localhost:5432/orchestra")
    )
    try:
        graph = OrchestraGraph(build_provider(), checkpointer=checkpointer)
        result = await replay_task(checkpointer, graph.workflow, task_id, edits)
    finally:
        await ckpt_pool.close()

    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return

    print(f"task:        {task_id}")
    print(f"edited:      {', '.join(result['edited_fields']) or '(nothing)'}")
    print(f"replay thread: {result['replay_thread_id']}")
    if not result["changed"]:
        print("divergence:  none - the replay produced identical outputs")
        return
    print(f"diverged:    {', '.join(result['changed_fields'])}")
    for field, diff in result["diffs"].items():
        print(f"\n--- {field} (original) ---")
        print(json.dumps(diff["original"], indent=2, default=str)[:1200])
        print(f"\n+++ {field} (replayed) +++")
        print(json.dumps(diff["replayed"], indent=2, default=str)[:1200])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay a run with edited inputs")
    parser.add_argument("task_id", help="task id whose checkpoint to replay")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="edit a state input, e.g. --set task_description='Summarize instead'",
    )
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    args = parser.parse_args()

    edits = _parse_edits(args.set)
    if not edits:
        raise SystemExit("Nothing to replay: pass at least one --set field=value")
    sys.exit(asyncio.run(_run(args.task_id, edits, args.json)))
