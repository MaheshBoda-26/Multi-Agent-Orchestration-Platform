from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncpg
import uuid
import json
import os

from api.routes import (
    init_approval_table, create_approval_request, get_pending_approvals,
    get_approval, resolve_approval, get_task_approvals,
    ApprovalRequest, ApprovalDecision
)
from graph.build import OrchestraGraph
from graph.state import GraphState
from llm.fake import FakeProvider

app = FastAPI(title="Orchestra Multi-Agent Orchestration Platform")

# Database pool
pool: Optional[asyncpg.Pool] = None

# In-memory task store for demo
active_tasks: Dict[str, Dict[str, Any]] = {}

@app.on_event("startup")
async def startup():
    global pool
    database_url = os.getenv("DATABASE_URL", "postgresql://orchestra:orchestra@localhost:5432/orchestra")
    pool = await asyncpg.create_pool(database_url)
    await init_approval_table(pool)

@app.on_event("shutdown")
async def shutdown():
    if pool:
        await pool.close()

# --- Task Endpoints ---

class TaskRequest(BaseModel):
    task_description: str

class TaskResponse(BaseModel):
    task_id: str
    status: str

@app.post("/tasks", response_model=TaskResponse)
async def create_task(request: TaskRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    active_tasks[task_id] = {"status": "running", "description": request.task_description}
    
    # Run task in background
    background_tasks.add_task(run_task, task_id, request.task_description)
    
    return TaskResponse(task_id=task_id, status="running")

@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in active_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return active_tasks[task_id]

@app.get("/tasks/{task_id}/events")
async def get_task_events(task_id: str):
    # SSE endpoint for real-time updates
    if task_id not in active_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    async def event_generator():
        # Simplified - in production would use actual event queue
        yield f"data: {json.dumps({'status': active_tasks[task_id]['status']})}\n\n"
    
    from fastapi.responses import StreamingResponse
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Approval Endpoints ---

@app.get("/approvals/pending", response_model=List[ApprovalRequest])
async def list_pending_approvals():
    return await get_pending_approvals(pool)

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
    
    # If this approval was blocking a task, we need to resume it
    # In a real implementation, this would signal the waiting graph
    if approval.task_id in active_tasks:
        active_tasks[approval.task_id]["human_response"] = decision.model_dump()
        active_tasks[approval.task_id]["waiting_for_approval"] = False
    
    return resolved

@app.get("/tasks/{task_id}/approvals", response_model=List[ApprovalRequest])
async def get_task_approvals_endpoint(task_id: str):
    return await get_task_approvals(pool, task_id)

# --- Approval Web UI ---

@app.get("/approvals/ui", response_class=HTMLResponse)
async def approval_ui():
    with open("web/approval_page.html", "r") as f:
        return HTMLResponse(content=f.read())

# --- Task Execution ---

async def run_task(task_id: str, description: str):
    try:
        llm = FakeProvider()
        graph = OrchestraGraph(llm)
        
        # Initial state
        state = {
            "task_id": task_id,
            "task_description": description,
            "plan": None,
            "results": {},
            "shared_context": "",
            "final_response": None,
        }
        
        active_tasks[task_id]["status"] = "planning"
        
        # Execute graph (this will handle interrupts internally)
        # For now, we'll simulate the flow
        final_state = await graph.workflow.ainvoke(state)
        
        active_tasks[task_id]["status"] = "completed"
        active_tasks[task_id]["result"] = final_state.get("final_response")
        
    except Exception as e:
        active_tasks[task_id]["status"] = "failed"
        active_tasks[task_id]["error"] = str(e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
