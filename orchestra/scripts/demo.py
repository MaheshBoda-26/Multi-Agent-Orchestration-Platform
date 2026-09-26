"""One-command Orchestra demo (Task 46).

Walks the whole platform against a live API + worker (default
http://localhost:8000, e.g. `docker compose up`):

1. parallel specialists (two independent subtasks fanned out concurrently)
2. a reviewer rejection forcing one retry, then acceptance
3. a second demo task reusing the first user's memories in planning
4. a low-confidence plan pausing for human approval, resolved via the API
5. trace, cost, replay and dashboard URLs to open in a browser

Defaults to the deterministic fake provider, so the demo runs with zero keys;
set LLM_PROVIDER=openrouter (+ OPENROUTER_API_KEY) before `docker compose up`
for the real thing.
"""
import argparse
import asyncio
import os
import sys
import time

import httpx

DEMO_USER = "demo-user"


async def _wait_terminal(
    client: httpx.AsyncClient, task_id: str, timeout: float = 120.0
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = (await client.get(f"/tasks/{task_id}")).json()
        if row.get("status") in {"completed", "failed", "cancelled"}:
            return row
        await asyncio.sleep(0.5)
    raise TimeoutError(f"task {task_id} never reached a terminal state")


async def _wait_status(
    client: httpx.AsyncClient, task_id: str, status: str, timeout: float = 60.0
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = (await client.get(f"/tasks/{task_id}")).json()
        if row.get("status") == status:
            return row
        if row.get("status") in {"failed", "cancelled"}:
            raise RuntimeError(f"task {task_id} ended as {row.get('status')!r}")
        await asyncio.sleep(0.5)
    raise TimeoutError(f"task {task_id} never reached {status!r}")


async def _wait_approval(client: httpx.AsyncClient, task_id: str) -> dict:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        approvals = (await client.get(f"/tasks/{task_id}/approvals")).json()
        if approvals:
            return approvals[0]
        await asyncio.sleep(0.5)
    raise TimeoutError(f"task {task_id} never produced an approval")


def _print_plan(row: dict) -> None:
    plan = row.get("plan") or []
    print(f"   plan: {len(plan)} subtasks, confidence tracked in the trace")
    for subtask in plan:
        print(f"   - [{subtask.get('specialist')}] {subtask.get('description')}")


async def main(base_url: str) -> int:
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        health = await client.get("/tasks?limit=1")
        health.raise_for_status()
        print(f"Orchestra demo against {base_url}\n")

        # --- 1. parallel specialists + reviewer rejection in one run ---------
        print("1) Parallel specialists with a reviewer loop")
        response = await client.post("/tasks", json={
            "task_description": (
                f"Demo run for user {DEMO_USER}: research Orchestra's architecture "
                "and write a short summary."
            ),
        })
        response.raise_for_status()
        task_id = response.json()["task_id"]
        print(f"   task {task_id}")
        row = await _wait_terminal(client, task_id)
        if row["status"] != "completed":
            print(f"   FAILED: {row.get('error')}")
            return 1
        _print_plan(row)
        retry_count = sum(
            1 for r in ((row.get("result") or {}).get("subtasks") or {}).values()
            if (r.get("retry_count") or 0) > 0
        )
        reviewer_spans = await _count_spans(client, task_id, "reviewer.review")
        print(
            f"   status: completed | subtasks retried by the reviewer: {retry_count} "
            f"| reviewer reviews: {reviewer_spans}"
        )

        # --- 2. memory-informed planning on a second run ----------------------
        print("\n2) Memory-informed planning (same user runs again)")
        response = await client.post("/tasks", json={
            "task_description": (
                f"Demo run for user {DEMO_USER}: write a follow-up analysis of "
                "Orchestra's durability guarantees."
            ),
        })
        response.raise_for_status()
        second_id = response.json()["task_id"]
        second_row = await _wait_terminal(client, second_id)
        print(f"   task {second_id}: {second_row['status']}")
        memories = (
            await client.get(f"/users/{DEMO_USER}/memories")
        ).json().get("memories", [])
        print(f"   long-term memories stored for {DEMO_USER}: {len(memories)}")

        # --- 3. human-in-the-loop: low-confidence plan pauses, human approves -
        print("\n3) Human-in-the-loop: low-confidence plan pauses the run")
        response = await client.post("/tasks", json={
            "task_description": (
                f"Demo HITL for user {DEMO_USER}: plan something unusual and "
                "novel that the supervisor is unsure about."
            ),
        })
        response.raise_for_status()
        hitl_id = response.json()["task_id"]
        await _wait_status(client, hitl_id, "awaiting_human")
        approval = await _wait_approval(client, hitl_id)
        print(f"   paused at trigger: {approval['trigger']}")
        context = approval.get("context") or {}
        print(f"   plan confidence was: {context.get('plan_confidence')}")

        clarify = await client.post(
            f"/approvals/{approval['id']}/clarify",
            json={"question": "Why is this plan low confidence?"},
        )
        if clarify.status_code == 200:
            print(f"   clarify answer: {clarify.json()['answer'][:110]}")

        decide = await client.post(
            f"/approvals/{approval['id']}/decide",
            json={"action": "approve"},
        )
        decide.raise_for_status()
        row = await _wait_terminal(client, hitl_id)
        print(f"   after approval: {row['status']}")

        # --- 4. observability: traces, costs, replay, dashboards --------------
        print("\n4) Observability")
        cost = (await client.get(f"/tasks/{task_id}/cost")).json()
        print(
            f"   task {task_id}: {cost['prompt_tokens']} prompt + "
            f"{cost['completion_tokens']} completion tokens, "
            f"{cost['latency_ms']} ms"
        )
        replay = await client.post(
            f"/tasks/{task_id}/replay",
            json={"edits": {"task_description": "Replay: what if the ask had changed?"}},
        )
        if replay.status_code == 200:
            body = replay.json()
            print(
                f"   replay diverged fields: {body['changed_fields'] or 'none'} "
                f"(thread {body['replay_thread_id'][:18]}…)"
            )
        else:
            print(f"   replay unavailable: HTTP {replay.status_code}")

        print("\nOpen in a browser:")
        for path in (
            f"/tasks/{task_id}/explorer",
            "/dashboard",
            "/approvals/ui",
            "/memory/ui",
        ):
            print(f"   {base_url}{path}")
        print("\nDemo complete.")
        return 0


async def _count_spans(client: httpx.AsyncClient, task_id: str, name: str) -> int:
    trace = (await client.get(f"/tasks/{task_id}/trace")).json()

    def walk(nodes: list) -> int:
        return sum(
            1 + walk(node.get("children") or []) for node in nodes if node.get("name") == name
        ) + sum(walk(node.get("children") or []) for node in nodes)

    return walk(trace.get("roots") or [])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Orchestra demo")
    parser.add_argument(
        "--base-url", default=os.environ.get("ORCHESTRA_BASE_URL", "http://localhost:8000")
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.base_url)))
