import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api import repository
from api.routes import (
    init_approval_table, get_pending_approvals,
    get_approval, resolve_approval, get_task_approvals,
    ApprovalRequest, ApprovalDecision,
)
from llm.fake import FakeProvider
from migrations import run_migrations
from worker.tasks import run_task, resume_task

logger = logging.getLogger(__name__)

app = FastAPI(title="Orchestra Multi-Agent Orchestration Platform")

# Approval page assets (approval.js) served from web/static.
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Database pool (created on startup)
pool: Optional[asyncpg.Pool] = None

# Server-sent-event polling. A tick count keeps the stream from hanging forever
# on a stuck run; the row itself is the source of truth, so clients can also
# poll GET /tasks/{id} at any time.
SSE_POLL_SECONDS = 0.5
SSE_MAX_TICKS = 7200  # ~1 hour


@app.on_event("startup")
async def startup() -> None:
    global pool
    database_url = os.getenv(
        "DATABASE_URL", "postgresql://orchestra:orchestra@localhost:5432/orchestra"
    )
    pool = await asyncpg.create_pool(database_url)
    await run_migrations(pool)
    await init_approval_table(pool)


@app.on_event("shutdown")
async def shutdown() -> None:
    if pool:
        await pool.close()


# --- Task endpoints ---------------------------------------------------------

class TaskRequest(BaseModel):
    task_description: str
    user_id: Optional[str] = None


class TaskResponse(BaseModel):
    task_id: str
    status: str


@app.post("/tasks", response_model=TaskResponse, status_code=202)
async def create_task(request: TaskRequest):
    """Enqueue a task on Celery and return immediately (FastAPI never blocks)."""
    task_id = uuid.uuid4()
    await repository.create_task(pool, task_id, request.task_description, request.user_id)
    run_task.delay(str(task_id), request.task_description)
    return TaskResponse(task_id=str(task_id), status="queued")


@app.get("/tasks")
async def list_tasks(limit: int = 20) -> Dict[str, Any]:
    """Most recent tasks first, for the explorer's task list."""
    limit = max(1, min(limit, 100))
    async with _db_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, request, status, error, created_at, finished_at
            FROM tasks ORDER BY created_at DESC LIMIT $1
            """,
            limit,
        )
    return {
        "tasks": [
            {
                "task_id": str(row["id"]),
                "request": row["request"],
                "status": row["status"],
                "error": row["error"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
            }
            for row in rows
        ]
    }


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    row = await _get_task_or_404(task_id)
    return row


@app.get("/tasks/{task_id}/events")
async def get_task_events(task_id: str):
    """SSE stream of status changes until the task reaches a terminal state."""
    await _get_task_or_404(task_id)
    task_uuid = uuid.UUID(task_id)

    async def event_generator():
        last_status = None
        for _ in range(SSE_MAX_TICKS):
            row = await repository.get_task(pool, task_uuid)
            if row is None:
                break
            if row["status"] != last_status:
                last_status = row["status"]
                yield _sse("status", {"task_id": task_id, "status": last_status})
            if last_status in repository.TERMINAL_STATUSES:
                yield _sse("done", {
                    "task_id": task_id,
                    "status": last_status,
                    "result": row.get("result"),
                    "error": row.get("error"),
                })
                break
            await asyncio.sleep(SSE_POLL_SECONDS)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _sse(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


# --- Trace and cost endpoints -------------------------------------------------

def _db_pool() -> asyncpg.Pool:
    assert pool is not None, "database pool is not initialized"
    return pool


@app.get("/tasks/{task_id}/trace")
async def get_task_trace(task_id: str) -> Dict[str, Any]:
    """Span tree for a run: every agent, tool and model call."""
    await _get_task_or_404(task_id)
    async with _db_pool().acquire() as conn:
        trace_rows = await conn.fetch(
            "SELECT DISTINCT trace_id FROM spans WHERE attributes ->> 'task_id' = $1",
            task_id,
        )
        if not trace_rows:
            return {"task_id": task_id, "roots": []}
        trace_ids = [row["trace_id"] for row in trace_rows]
        rows = await conn.fetch(
            """
            SELECT trace_id, span_id, parent_span_id, name, kind, status,
                   start_time, end_time, attributes
            FROM spans
            WHERE trace_id = ANY($1::varchar[])
            ORDER BY start_time ASC
            """,
            trace_ids,
        )
    return {"task_id": task_id, "roots": _span_tree([dict(row) for row in rows])}


@app.get("/tasks/{task_id}/cost")
async def get_task_cost(task_id: str) -> Dict[str, Any]:
    """Per-run token, cost and latency rollup from run_metadata."""
    await _get_task_or_404(task_id)
    async with _db_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM run_metadata WHERE task_id = $1 ORDER BY started_at DESC LIMIT 1",
            uuid.UUID(task_id),
        )
    if row is None:
        raise HTTPException(status_code=404, detail="No run metadata for task")
    breakdown = row["model_breakdown"]
    if isinstance(breakdown, str):
        breakdown = json.loads(breakdown)
    return {
        "task_id": task_id,
        "status": row["status"],
        "prompt_tokens": row["total_prompt_tokens"],
        "completion_tokens": row["total_completion_tokens"],
        "cost_usd": float(row["total_cost_usd"]),
        "latency_ms": row["latency_ms"],
        "model_breakdown": breakdown or {},
    }


class ReplayRequest(BaseModel):
    edits: Dict[str, Any]


@app.post("/tasks/{task_id}/replay")
async def replay_task_endpoint(task_id: str, request: ReplayRequest):
    """Replay a completed run with edited inputs; returns the divergence diff.

    The original checkpoint is never modified: the replay runs in a fresh
    checkpointer thread seeded with the edited state.
    """
    await _get_task_or_404(task_id)
    from graph.build import OrchestraGraph
    from graph.checkpointer import create_checkpointer
    from graph.replay import replay_task

    ckpt_pool, checkpointer = await create_checkpointer(os.getenv(
        "DATABASE_URL", "postgresql://orchestra:orchestra@localhost:5432/orchestra"
    ))
    try:
        graph = OrchestraGraph(FakeProvider(), checkpointer=checkpointer)
        return await replay_task(
            checkpointer, graph.workflow, task_id, request.edits
        )
    except KeyError as exc:
        # KeyError is a LookupError, so this must come first.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        await ckpt_pool.close()


def _span_tree(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        attributes = row.get("attributes")
        if isinstance(attributes, str):
            try:
                attributes = json.loads(attributes)
            except ValueError:
                attributes = {}
        nodes[row["span_id"]] = {
            **row,
            "attributes": attributes,
            "start_time": row["start_time"].isoformat() if row.get("start_time") else None,
            "end_time": row["end_time"].isoformat() if row.get("end_time") else None,
            "children": [],
        }
    roots: List[Dict[str, Any]] = []
    for node in nodes.values():
        parent = node.get("parent_span_id")
        if parent and parent in nodes:
            nodes[parent]["children"].append(node)
        else:
            roots.append(node)
    return roots


async def _get_task_or_404(task_id: str) -> Dict[str, Any]:
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    row = await repository.get_task(pool, task_uuid)
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


# --- Approval endpoints -----------------------------------------------------

class ClarifyQuestion(BaseModel):
    question: str


@app.get("/approvals/pending", response_model=List[ApprovalRequest])
async def list_pending_approvals():
    return await get_pending_approvals(pool)


# NOTE: declared before /approvals/{approval_id} so the literal path wins the
# route match; otherwise the UI page 404s as an unknown approval id.
@app.get("/approvals/ui", response_class=HTMLResponse)
async def approval_ui():
    with open("web/approval_page.html") as f:
        return HTMLResponse(content=f.read())


@app.get("/approvals/{approval_id}", response_model=ApprovalRequest)
async def get_approval_details(approval_id: str):
    approval = await get_approval(pool, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@app.post("/approvals/{approval_id}/decide")
async def decide_approval(approval_id: str, decision: ApprovalDecision):
    """Record a human decision and hand the task back to a worker.

    The approvals row is the durable audit record; the worker replays the
    paused interrupt node with the decision via ``Command(resume=...)``.
    """
    approval = await get_approval(pool, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="Approval already resolved")

    resolved = await resolve_approval(pool, approval_id, decision)
    # A worker applies the decision; retries land on the same durable queue.
    resume_task.delay(approval.task_id, approval_id)
    logger.info(
        "Approval %s decided with %s for task %s; resume enqueued",
        approval_id, decision.action, approval.task_id,
    )
    return resolved


@app.post("/approvals/{approval_id}/clarify")
async def clarify_approval(approval_id: str, question: ClarifyQuestion):
    """Answer a human's question from the checkpoint, without resuming.

    The paused graph's state holds the plan, results and the pending approval
    payload; a cheap LLM call answers from that context only. The run stays
    paused either way.
    """
    approval = await get_approval(pool, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="Approval already resolved")

    try:
        answer = await _clarify_from_checkpoint(approval, question.question)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"approval_id": approval_id, "question": question.question, "answer": answer}


async def _clarify_from_checkpoint(approval: ApprovalRequest, question: str) -> str:
    """Read-only Q&A over the paused run's checkpointed state."""
    from graph.checkpointer import create_checkpointer

    ckpt_pool, checkpointer = await create_checkpointer(os.getenv(
        "DATABASE_URL", "postgresql://orchestra:orchestra@localhost:5432/orchestra"
    ))
    try:
        snapshot = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": approval.task_id}}
        )
    finally:
        await ckpt_pool.close()
    if snapshot is None:
        raise LookupError("No checkpoint exists for this task")

    # CheckpointTuple channel values: this langgraph version keeps them in
    # checkpoint["channel_values"] (graph.replay.load_checkpoint_values is
    # version-tolerant for other shapes).
    from graph.replay import load_checkpoint_values
    state: Dict[str, Any] = load_checkpoint_values(snapshot)
    summary = {
        "task_description": state.get("task_description"),
        "plan": state.get("plan"),
        "results": {
            sid: r.model_dump() if hasattr(r, "model_dump") else r
            for sid, r in (state.get("results") or {}).items()
        },
        "pending_approval": approval.model_dump(),
    }
    prompt = (
        "You are answering a human reviewer's question about a paused "
        "multi-agent run. Use only the JSON state below; if it does not "
        "contain the answer, say so.\n\nState:\n"
        f"{json.dumps(summary, indent=2, default=str)}\n\n"
        f"Question: {question}\n\nAnswer concisely:"
    )
    response = await FakeProvider().complete(prompt)
    return response.content


@app.get("/tasks/{task_id}/approvals", response_model=List[ApprovalRequest])
async def get_task_approvals_endpoint(task_id: str):
    return await get_task_approvals(pool, task_id)


# --- Memory endpoints (Phase 5) ---------------------------------------------

@app.get("/users/{user_id}/memories")
async def list_memories(user_id: str) -> Dict[str, Any]:
    """A user's stored lessons, newest first."""
    from memory.store import list_user_memories

    records = await list_user_memories(_db_pool(), user_id)
    return {
        "user_id": user_id,
        "memories": [record.model_dump(mode="json") for record in records],
    }


@app.delete("/users/{user_id}/memories")
async def delete_memories(user_id: str) -> Dict[str, Any]:
    """Right-to-erasure: removes every vector row and metadata for a user."""
    from memory.store import delete_user_memories

    deleted = await delete_user_memories(_db_pool(), user_id)
    return {"user_id": user_id, "deleted": deleted}


@app.get("/memory/ui", response_class=HTMLResponse)
async def memory_ui():
    with open("web/memory.html") as f:
        return HTMLResponse(content=f.read())


# --- Stats, dashboards and the trace explorer (Phase 8) ----------------------

@app.get("/stats/cost")
async def stats_cost() -> Dict[str, Any]:
    """Fleet-wide cost, latency and escalation rollup for the dashboard."""
    async with _db_pool().acquire() as conn:
        totals = await conn.fetchrow(
            """
            SELECT COUNT(*) AS runs,
                   COALESCE(SUM(total_prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(total_completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(total_cost_usd), 0) AS cost_usd,
                   COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
            FROM run_metadata
            """
        )
        by_status = await conn.fetch(
            "SELECT status, COUNT(*) AS runs FROM run_metadata GROUP BY status"
        )
        breakdown_rows = await conn.fetch(
            "SELECT model_breakdown FROM run_metadata WHERE model_breakdown IS NOT NULL"
        )
        approvals = await conn.fetch(
            """
            SELECT trigger, status, COUNT(*) AS count
            FROM approvals GROUP BY trigger, status
            """
        )

    models: Dict[str, Dict[str, float]] = {}
    for row in breakdown_rows:
        breakdown = row["model_breakdown"]
        if isinstance(breakdown, str):
            breakdown = json.loads(breakdown)
        for model, stats in (breakdown or {}).items():
            bucket = models.setdefault(
                model, {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
            )
            bucket["prompt_tokens"] += int(stats.get("prompt_tokens", 0) or 0)
            bucket["completion_tokens"] += int(stats.get("completion_tokens", 0) or 0)
            bucket["cost_usd"] += float(stats.get("cost_usd", 0) or 0)

    escalations: Dict[str, Dict[str, int]] = {}
    for row in approvals:
        entry = escalations.setdefault(row["trigger"], {})
        entry[row["status"]] = int(row["count"])

    return {
        "runs": int(totals["runs"]),
        "prompt_tokens": int(totals["prompt_tokens"]),
        "completion_tokens": int(totals["completion_tokens"]),
        "cost_usd": float(totals["cost_usd"]),
        "avg_latency_ms": int(totals["avg_latency_ms"]),
        "runs_by_status": {row["status"]: int(row["runs"]) for row in by_status},
        "models": models,
        "escalations": escalations,
    }


# NOTE: literal /explorer is declared before /tasks/{task_id}/explorer and both
# before any /tasks/{task_id} sibling that could shadow them.
@app.get("/explorer", response_class=HTMLResponse)
async def explorer_index():
    with open("web/explorer.html") as f:
        return HTMLResponse(content=f.read())


@app.get("/tasks/{task_id}/explorer", response_class=HTMLResponse)
async def explorer_task(task_id: str):
    await _get_task_or_404(task_id)
    with open("web/explorer.html") as f:
        return HTMLResponse(content=f.read())


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_ui():
    with open("web/dashboard.html") as f:
        return HTMLResponse(content=f.read())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
