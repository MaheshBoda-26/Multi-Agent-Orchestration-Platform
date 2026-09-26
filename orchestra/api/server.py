import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from api import repository
from api.routes import (
    init_approval_table, get_pending_approvals,
    get_approval, resolve_approval, get_task_approvals,
    ApprovalRequest, ApprovalDecision,
)
from graph.build import OrchestraGraph
from llm.factory import build_provider
from migrations import run_migrations

logger = logging.getLogger(__name__)

app = FastAPI(title="Orchestra Multi-Agent Orchestration Platform")

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


class TaskResponse(BaseModel):
    task_id: str
    status: str


@app.post("/tasks", response_model=TaskResponse, status_code=202)
async def create_task(request: TaskRequest, background_tasks: BackgroundTasks):
    """Enqueue a task and return immediately; the run happens in the background."""
    task_id = uuid.uuid4()
    await repository.create_task(pool, task_id, request.task_description)
    background_tasks.add_task(run_task, str(task_id), request.task_description)
    return TaskResponse(task_id=str(task_id), status="queued")


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
    approval = await get_approval(pool, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="Approval already resolved")

    resolved = await resolve_approval(pool, approval_id, decision)

    # Resuming a paused graph needs a LangGraph checkpointer, which lands with
    # the durability phase. Until then the decision is recorded durably (the
    # approvals row is the audit record) and the task is not silently resumed.
    logger.info(
        "Approval %s decided with %s for task %s; graph resume pending durability phase",
        approval_id, decision.action, approval.task_id,
    )
    return resolved


@app.get("/tasks/{task_id}/approvals", response_model=List[ApprovalRequest])
async def get_task_approvals_endpoint(task_id: str):
    return await get_task_approvals(pool, task_id)


# --- Task execution ---------------------------------------------------------

async def run_task(task_id: str, description: str) -> None:
    task_uuid = uuid.UUID(task_id)
    try:
        provider = build_provider()
        graph = OrchestraGraph(provider)

        await repository.set_task_status(pool, task_uuid, "running")

        state: Dict[str, Any] = {
            "task_id": task_id,
            "task_description": description,
            "plan": None,
            "results": {},
            "attempts": {},
            "review_feedback": {},
            "shared_context": "",
            "final_response": None,
        }
        final_state = await graph.workflow.ainvoke(state)

        plan = final_state.get("plan") or []
        if plan:
            await repository.save_task_plan(pool, task_uuid, plan)

        results: Dict[str, Any] = final_state.get("results") or {}
        await repository.complete_task(pool, task_uuid, {
            "final_response": final_state.get("final_response"),
            "subtasks": {
                key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
                for key, value in results.items()
            },
        })
    except Exception as exc:
        logger.exception("Task %s failed", task_id)
        await repository.fail_task(pool, task_uuid, str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
