# Orchestra

A durable multi-agent orchestration platform: a supervisor plans, specialists
run in parallel with real tools, a reviewer gates every output, humans approve
sensitive steps, and long-term memory makes each run smarter than the last.

```
User ──▶ FastAPI ──▶ Celery (Redis) ──▶ LangGraph worker
                                          ├─ supervisor.plan   (memory-informed)
                                          ├─ plan_approval     (interrupt @ <0.6 conf)
                                          ├─ execute_subtask xN (parallel, sandboxed tools)
                                          ├─ review            (retry once, then escalate)
                                          ├─ action_approval   (interrupt @ sensitive tools)
                                          └─ synthesize        (stores a lesson)
```

Every super-step is checkpointed to Postgres (LangGraph `AsyncPostgresSaver`),
so a `SIGKILL`ed worker loses nothing: Celery redelivers the job and the graph
resumes from the last checkpoint without repeating finished work.

## Quickstart

```bash
docker compose up -d postgres redis
uv run uvicorn api.server:app --reload        # terminal 1: the API on :8000
uv run celery -A worker.celery_app worker --pool=threads --concurrency=4   # terminal 2

# then, from another shell:
uv run python scripts/demo.py                 # walks the whole platform
```

`LLM_PROVIDER` defaults to `fake` (deterministic, zero keys, what CI uses).
For real models:

```bash
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-or-...
```

Model selection lives entirely in `config/routing.yaml` (role → model, costs).
Secrets only ever enter through the environment.

### The demo

`uv run python scripts/demo.py --base-url http://localhost:8000` runs three
tasks end to end and prints what happened at each milestone:

1. **Parallel specialists + reviewer loop** — the plan fans out independent
   subtasks concurrently; a rigged reviewer rejection forces one retry.
2. **Memory-informed planning** — the same user runs a related task and the
   supervisor plans with the lessons extracted from run one.
3. **Human-in-the-loop** — a low-confidence plan pauses the run durably, the
   demo answers a clarifying question (`POST /approvals/{id}/clarify`),
   approves (`POST /approvals/{id}/decide`), and the run resumes to completion.

It finishes with the observability URLs: per-task trace explorer, cost
dashboard, approval queue and memory dashboard.

## What is verified (not claimed)

All numbers come from committed artifacts; nothing below is hand-written.

**Eval harness** (`evals/results.md`, reproduced by
`uv run python -m evals.report` over the locked 100-task set, 3 repeats):

| Config | Pass rate (mean) | Spread |
|---|---|---|
| full | 100.0% | 100.0% |
| no-reviewer / no-parallel / no-memory / no-hitl / cheap-only | 100.0% | 100.0% |

(Fake-provider dry-run: it validates the harness plumbing, not model quality.
Live OpenRouter numbers land in the same table via
`uv run python -m evals.run --provider openrouter`.)

**Injection suite** (`security/results.md`, reproduced by
`uv run python -m security.run_injection && uv run python -m security.report`):

| Suite | Pass rate |
|---|---|
| Undefended (obeys injected commands) | 0/25 |
| Defended (data framing + standing policy) | 25/25 |

Tool output is quarantined in an `UNTRUSTED DATA` frame with instruction-like
patterns flagged; specialists carry a standing security policy. The approval
gates remain authoritative for sensitive actions — the sanitizer is one layer,
not a guarantee.

**Test gates** (FakeProvider, no network): 156 unit tests, 10
integration/e2e tests against real Postgres + Redis, mypy and ruff clean.
CI runs all of it (`.github/workflows/ci.yml`).

**Clean-machine verification** (Phase 9): the image build, compose stack,
API health, demo end-to-end, eval dry-run and all four UI pages were
exercised the way a stranger would run them; the issues that surfaced are
fixed and recorded in `tasks/lessons.md`. Re-verify any time with
`bash scripts/clean_clone_check.sh`.

The judge is validated against 20 hand-labeled samples
(`evals/judge_samples.jsonl`) via `uv run python -m evals.validate_judge`;
the ≥ 0.8 agreement gate runs live and skips without a key.
Live-matrix spend is capped (`--budget-max`, default guidance $40) and
deduplicated through the `llm_cache` table; the routing experiment
(full vs cheap-only quality/cost) is part of `evals/results.md`.
Failure analysis method and live-run instructions: `evals/failures.md`.

## Durability, HITL and replay

- **Kill-resume:** `tests/integration/test_run_resumes_after_worker_kill.py`
  SIGKILLs the worker mid-review, restarts it, and asserts every subtask ran
  exactly once.
- **Durable pause:** `test_pause_survives_worker_restart.py` pauses at the
  plan gate, kills the worker, restarts, approves, and asserts the supervisor
  never re-planned.
- **Replay with divergence:** `POST /tasks/{id}/replay` re-runs a completed
  task with edited inputs into a fresh checkpoint thread and diffs
  plan/results/final_response. CLI: `uv run python scripts/replay.py <task_id>
  --set task_description='New ask'`. The original checkpoint is never touched.

## Tool safety

Every tool call flows through one audited path (`tools/execution.py`):
registry permission + rate-limit checks, the sensitive-tool approval gate
(`code_execute`, `http_get`, `file_write`), and a `tool_calls` audit row with
inputs, outputs, latency and status. File tools are jailed to a per-task
workspace (realpath + commonpath checks), HTTP is allowlisted per domain with
redirect re-validation and private-address blocking, SQL is read-only with a
statement allowlist, and code runs in a Docker sandbox with no network,
capped CPU/memory/PIDs and a read-only rootfs.

Tools are also exposed to external MCP clients (`mcp_server/server.py`):
`tools/list` and `tools/call` over stdio JSON-RPC, sensitive tools gated by
the same approval signatures.

## API surface

| Endpoint | Purpose |
|---|---|
| `POST /tasks` | Enqueue a run (202, Celery) |
| `GET /tasks` / `GET /tasks/{id}` | List / inspect runs |
| `GET /tasks/{id}/events` | SSE stream until terminal |
| `GET /tasks/{id}/trace` | Full span tree |
| `GET /tasks/{id}/cost` | Tokens, cost, latency rollup |
| `POST /tasks/{id}/replay` | Replay with edited inputs, divergence diff |
| `GET /approvals/pending` · `POST /approvals/{id}/decide` · `POST /approvals/{id}/clarify` | Human-in-the-loop |
| `GET/DELETE /users/{id}/memories` | Long-term memory (right to erasure) |
| `GET /stats/cost` | Fleet-wide cost + escalation rollup |
| `/explorer` · `/dashboard` · `/approvals/ui` · `/memory/ui` | Static UIs |

## Architecture

| Layer | Choice |
|---|---|
| Models | OpenRouter via httpx (`llm/provider.py`), role-routed by `config/routing.yaml` |
| Graph | LangGraph + `AsyncPostgresSaver` (psycopg3) checkpoints |
| Queue | Celery + Redis, late acks, redelivery on worker loss |
| Data | Postgres 16 + pgvector (memories: cosine top-k, HNSW) |
| API/UI | FastAPI serving static HTML/JS (no build step) |
| Observability | OpenTelemetry spans → Postgres exporter, per-call costs |

Deviations from the original TRD (Python 3.14, pgvector over ChromaDB,
Postgres-exporter over OTLP) are recorded in `docs/decisions.md`.

## Repo layout

```
api/          FastAPI app, routes, repository, run_metadata
agents/       supervisor, specialists (bounded tool loop), reviewer
graph/        LangGraph build, state, HITL gates, sanitize, replay
tools/        registry, audited execution, jailed builtins, docker sandbox
worker/       celery app + durable run/resume tasks
memory/       pgvector store + retrieval/extraction agents
llm/          provider ABC, fake, openrouter, embeddings, recording
evals/        locked 100-task set, graders, matrix runner, report
security/     25-case injection suite, runner, report
mcp_server/   stdio MCP server over the tool registry
migrations/   001–007 (applied automatically at startup)
web/          approval queue, explorer, dashboard, memory dashboard
```
