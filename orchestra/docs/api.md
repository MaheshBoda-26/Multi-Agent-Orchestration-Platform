# API reference

Base URL: `http://localhost:8000` (compose) or wherever `uvicorn api.server:app`
runs. JSON in / JSON out. A static UI exists for the human flows:
`/approvals/ui`, `/explorer`, `/dashboard`, `/memory/ui`.

## Tasks

### `POST /tasks` — enqueue a run
```json
// request
{"task_description": "Compare pgvector and Qdrant for RAG.", "user_id": "user-42"}
// 202
{"task_id": "6d3b…", "status": "queued"}
```
`user_id` is optional; when present it scopes long-term memory. The run is
executed by a Celery worker; poll `GET /tasks/{id}` or stream `/events`.

### `GET /tasks?limit=20` — recent tasks (explorer feed)
```json
{"tasks": [{"task_id": "6d3b…", "request": "Compare…", "status": "completed",
            "error": null, "created_at": "…", "finished_at": "…"}]}
```

### `GET /tasks/{id}` — full task row
```json
{"task_id": "6d3b…", "user_id": "user-42", "request": "Compare…",
 "status": "completed", "plan": [{"id": "t1", "specialist": "researcher", …}],
 "result": {"final_response": "…", "subtasks": {"t1": {"status": "accepted", …}}},
 "error": null, "created_at": "…", "started_at": "…", "finished_at": "…"}
```

### `GET /tasks/{id}/events` — SSE stream
Emits `event: status` on every status change until a terminal status, then
`event: done` with the result and closes.

### `GET /tasks/{id}/trace` — span tree
```json
{"task_id": "6d3b…", "roots": [{"name": "task.run", "children": [
  {"name": "supervisor.plan", "attributes": {"task_id": "6d3b…"}, "children": [
    {"name": "memory.retrieve", …}, {"name": "llm.complete_structured", …}]},
  {"name": "specialist.run", …}, {"name": "reviewer.review", …},
  {"name": "synthesize", …}]}]}
```

### `GET /tasks/{id}/cost` — run rollup
```json
{"task_id": "6d3b…", "status": "completed", "prompt_tokens": 1401,
 "completion_tokens": 290, "cost_usd": 0.0, "latency_ms": 53,
 "model_breakdown": {"openai/gpt-4o-mini": {"prompt_tokens": 1401, …}}}
```
404 when no run metadata exists yet.

### `POST /tasks/{id}/replay` — replay with edited inputs
```json
// request — field names are graph-state fields; unknown fields → 422
{"edits": {"task_description": "What if the ask had changed?"}}
// 200
{"original_thread_id": "6d3b…", "replay_thread_id": "replay-9297…",
 "edited_fields": ["task_description"], "changed": true,
 "changed_fields": ["plan"],
 "diffs": {"plan": {"original": […], "replayed": […]}}}
```
404 when no checkpoint exists. The original checkpoint is never modified.

## Human approvals

### `GET /approvals/pending`
```json
[{"id": "6d3b…:ab12cd34", "task_id": "6d3b…", "escalation_level": "approve_plan",
  "trigger": "low_confidence_plan",
  "context": {"plan_confidence": 0.35, "plan": […], "task_description": "…"},
  "proposed_action": "Execute plan with 2 subtasks", "status": "pending",
  "created_at": "…", "resolved_at": null, "resolution": null}]
```

### `POST /approvals/{id}/decide` — resolve + resume the worker
```json
// request — action: approve | modify | reject | take_over
{"action": "approve"}
// 200: the updated approval (status no longer pending)
```
Sensitive-action decisions may carry `modified_arguments`.

### `POST /approvals/{id}/clarify` — answer questions without resuming
```json
// request
{"question": "Why is this plan low confidence?"}
// 200
{"approval_id": "…", "question": "…", "answer": "…"}
```
409 when the approval is already resolved.

## Memory (per user, pgvector)

### `GET /users/{user_id}/memories`
```json
{"user_id": "user-42", "memories": [{"id": 7, "kind": "task_lesson",
  "content": "Request: … Approach: … Facts: …", "importance": 0.5,
  "access_count": 1, "source_task_id": "6d3b…", "created_at": "…"}]}
```

### `DELETE /users/{user_id}/memories` — right to erasure
```json
{"user_id": "user-42", "deleted": 2}
```
Removes every vector row and metadata for the user.

## Stats

### `GET /stats/cost` — fleet-wide rollup (dashboard)
```json
{"runs": 12, "prompt_tokens": 20341, "completion_tokens": 4102,
 "cost_usd": 0.0, "avg_latency_ms": 61,
 "runs_by_status": {"completed": 8, "running": 2, "awaiting_human": 2},
 "models": {"openai/gpt-4o-mini": {"prompt_tokens": 20341, …}},
 "escalations": {"low_confidence_plan": {"pending": 30, "modify": 15}}}
```

## Errors

| Status | Meaning |
|---|---|
| 404 | Task/approval/checkpoint not found (bad uuid included) |
| 409 | Approval already resolved (decide/clarify) |
| 422 | Unknown replay edit field, or malformed body |
| 500 | Worker-side failure; details in `tasks.error` and worker logs |
