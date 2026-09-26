# Architecture

Orchestra turns one user request into a planned, parallel, reviewed, and
human-governed multi-agent run — durably. This document explains how the
pieces fit and why each choice was made; every claim names its proof.

## System diagram

```
                 ┌───────────────────────────────────────────────────────┐
                 │                     FastAPI (api/)                    │
 Browser ───────▶│ POST /tasks → tasks row → run_task.delay()            │
                 │ GET  /tasks/{id} · /trace · /cost · /replay           │
                 │ GET  /stats/cost · approvals · memories · static UIs  │
                 └───────────────┬───────────────────────────────────────┘
                                 │ Celery (Redis broker, late acks)
                                 ▼
                 ┌───────────────────────────────────────────────────────┐
                 │                Worker (worker/tasks.py)               │
                 │  _run_graph: checkpointer + registry + executor       │
                 │  pause? → persist approvals → awaiting_human          │
                 └───────────────┬───────────────────────────────────────┘
                                 ▼
     ┌──────────────────────── LangGraph (graph/build.py) ────────────────────┐
     │ supervisor.plan ─▶ plan_approval ─▶ dispatch ⇄ execute_subtask (parallel Send)
     │                                            │                           │
     │                                            ▼                           │
     │                                        review ─▶ action_approval /     │
     │                   failure_approval / dispatch … until synthesize       │
     └────────────────────────────────────────────────────────────────────────┘
        │                │                    │                 │
        ▼                ▼                    ▼                 ▼
  AsyncPostgresSaver  tools/execution   llm/ (OpenRouter)   memory/ (pgvector)
  (every super-step)  (audit + gates)   via recording       lessons in/out
```

## The four flows

### 1. Submit → run
`POST /tasks` writes the task row and enqueues `orchestra.run_task` on Celery
(202 immediately; FastAPI never blocks). The worker builds a fresh tool
registry (jailed workspace per task), wraps the provider in
`RecordingLLMProvider`, and invokes the graph with `durability="sync"` —
every super-step commits to the checkpointer before the next begins. On
completion: plan + result persisted, `run_metadata` totals written.

### 2. HITL pause → resume
Approval `interrupt()` calls live in **dedicated gate nodes** that never call
an LLM or a tool (`graph/approval_nodes.py`), so a resume replays only the
cheap gate. When the graph stops on an interrupt, the worker persists the
payload as an approvals row (idempotent on `{task_id}:{signature}`), marks the
task `awaiting_human`, and exits — the pause is durable, with no timeout.
`POST /approvals/{id}/decide` records the resolution and enqueues
`orchestra.resume_task`, which invokes `Command(resume=decision)`.
`/clarify` answers questions from the checkpointed state without resuming.
*Proof:* `tests/integration/test_pause_survives_worker_restart.py` — pause,
SIGKILL, restart, decide, complete, supervisor planned exactly once.

### 3. Crash → checkpoint resume
`task_acks_late=True` + `task_reject_on_worker_lost=True` mean a SIGKILLed
worker's message is redelivered; `run_task` finds the existing checkpoint
thread and invokes with `None` to continue from the last committed super-step.
*Proof:* `tests/integration/test_run_resumes_after_worker_kill.py` — worker
killed mid-review; after restart each subtask ran exactly once.

### 4. Replay with divergence
`graph/replay.py` loads the final checkpoint's channel values, applies edited
inputs, and re-invokes the graph into a fresh `replay-<uuid>` thread; the
original is never touched. Exposed at `POST /tasks/{id}/replay` and
`scripts/replay.py`. *Proof:* `tests/integration/test_replay_divergence.py` —
edited description moves the plan; no-edit replay is identical; original
checkpoint unchanged.

## Stack decisions

| Layer | Choice | Why |
|---|---|---|
| Models | OpenRouter via httpx behind `llm/provider.py` | One audited seam; every model name lives in `config/routing.yaml` |
| Durability | LangGraph `AsyncPostgresSaver` (psycopg3 pool) | Postgres-native checkpoints; survives any process death |
| Queue | Celery + Redis, late acks, prefetch 1 | At-least-once redelivery is the resume trigger |
| Data | Postgres 16 + pgvector | One database for tasks, traces, approvals, memory; no extra service |
| Memory | cosine top-k + importance/recency blend | Relevant lessons without a vector-only DB |
| UI | FastAPI-served static HTML/JS | No build step; the whole UI is reviewable |
| Observability | OTel spans → custom Postgres exporter | Traces and costs queryable with the rest of the data |

Deviations from the original TRD (Python 3.14, pgvector over ChromaDB, the
Postgres exporter over OTLP) are recorded in `docs/decisions.md`.

## Security layers (defense in depth)

1. **Workspace jail** — file tools resolve paths with realpath + commonpath;
   symlinks and prefix-siblings cannot escape (`tools/builtin/file_tools.py`).
2. **HTTP allowlist + SSRF guards** — domain allowlist, scheme checks,
   per-hop re-validation, private/loopback address blocking (`web_tools.py`).
3. **Read-only SQL** — statement allowlist, row cap, statement timeout.
4. **Docker sandbox** — no network, CPU/mem/PID caps, read-only rootfs,
   tmpfs workspace, timeout kill (`tools/builtin/sandbox.py`).
5. **Sensitive-tool approval gate** — `code_execute`, `http_get`, `file_write`
   require a human-approved signature (`tools/execution.py`).
6. **Prompt-injection defenses** — every tool result is framed as
   `UNTRUSTED DATA` with instruction-like patterns flagged, plus a standing
   security policy in specialist prompts (`graph/sanitize.py`). Heuristic
   layer only; approval gates stay authoritative. Suite: `security/results.md`.
7. **Audited tool calls** — every call lands in `tool_calls` with arguments,
   result, latency, status.

## Where the guarantees live

| Guarantee | Code | Proven by |
|---|---|---|
| No lost work on crash | `worker/tasks.py`, checkpointer | kill/resume integration test |
| Pauses survive restarts | approval nodes + approvals rows | pause-survives-restart test |
| Bounded agent loops | `MAX_TOOL_ITERATIONS=5`, review retry cap | unit tests |
| Per-user memory + erasure | `memory/store.py`, DELETE endpoint | memory tests |
| Reproducible numbers | `evals/run.py` + `results.md` | eval harness tests |
| Cost containment | budget guard + LLM cache | `tests/unit/test_eval_budget.py` |
