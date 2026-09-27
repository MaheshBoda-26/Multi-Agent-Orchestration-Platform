# Orchestra — Multi-Agent Orchestration Platform

A production-grade multi-agent orchestration platform: a **supervisor** plans,
**specialists** run in parallel with real, sandboxed tools, a **reviewer** gates
every output against a rubric, **humans approve** sensitive or low-confidence
steps, and **long-term memory** makes each run smarter than the last.

Every run is durable (a killed worker loses nothing), observable (full span
trace with per-step cost and latency), and reproducible (a locked 100-task eval
harness with ablations, baselines, and variance).

Built as an eval-backed portfolio project. Discipline: **nothing in this README
is claimed that isn't verified by a committed test or artifact.**

---

## What it does

```
User ──▶ FastAPI ──▶ Celery (Redis) ──▶ LangGraph worker
                                          ├─ supervisor.plan      (memory-informed)
                                          ├─ plan_approval        (interrupt @ <0.6 conf)
                                          ├─ execute_subtask xN   (parallel, sandboxed tools)
                                          ├─ review               (retry once, then escalate)
                                          ├─ action_approval      (interrupt @ sensitive tools)
                                          └─ synthesize           (stores a lesson)
```

1. **A task comes in** through `POST /tasks` and is queued on Celery.
2. **The supervisor plans** — the request is decomposed into a validated DAG of
   subtasks (cycle check, unknown-specialist check, ≤12 subtasks), informed by
   lessons retrieved from previous runs for that user.
3. **Specialists execute in parallel** — research, data-analysis, writer, and
   code-executor agents work their subtasks through a bounded tool-calling loop
   (web search, jailed file I/O, Docker-sandboxed code, read-only SQL,
   allowlisted HTTP). Independent subtasks fan out concurrently; dependent ones
   run in topological order. Failures retry once with a different approach,
   then escalate to a human.
4. **The reviewer gates everything** — each result is scored on a rubric
   (correctness, completeness, format, sources); weak output goes back to the
   specialist with feedback, capped, then escalates.
5. **Humans stay in charge** — low-confidence plans and sensitive tool calls
   (code execution, external HTTP, file writes) pause the graph durably. You
   can approve, modify, reject, take over, or ask a clarifying question first.
6. **The run synthesizes a response** and extracts a lesson into long-term
   memory, so the next related task plans smarter.

Every super-step is checkpointed to Postgres (LangGraph `AsyncPostgresSaver`),
so a `SIGKILL`ed worker loses nothing: Celery redelivers the job and the graph
resumes from the last checkpoint without repeating finished work.

## The pillars

| Pillar | What it means | Where to look |
|---|---|---|
| **Durable execution** | Kill the worker mid-run; it resumes from checkpoint with no repeated completed steps | `tests/integration/test_run_resumes_after_worker_kill.py` |
| **Human-in-the-loop** | Four escalation levels (Notify → Approve action → Approve plan → Take over); pauses survive restarts; no approval timeouts | `tests/integration/test_pause_survives_worker_restart.py` |
| **Real tools, safely jailed** | File tools locked to a per-task workspace (`realpath` + `commonpath`), HTTP domain-allowlisted with private-address blocking, SQL read-only with a statement allowlist, code in a no-network Docker sandbox | `tools/execution.py`, `tools/builtin/` |
| **Reviewer loop** | Rigged bad output is caught, sent back with feedback, fixed — and the whole loop is visible in the trace | Phase 3 integration tests |
| **Long-term memory** | pgvector cosine retrieval scoped per user; lessons injected into planning with source ids; full right-to-erasure endpoint | `memory/`, `GET/DELETE /users/{id}/memories` |
| **Replay** | Re-run any completed task with edited inputs into a fresh checkpoint thread and diff plan/results against the original | `POST /tasks/{id}/replay`, `scripts/replay.py` |
| **Prompt-injection defense** | Tool output quarantined as UNTRUSTED DATA with instruction-like patterns flagged; 25-case suite run defended and undefended | `security/`, `security/results.md` |
| **Observability** | OpenTelemetry spans → Postgres exporter; per-task trace tree and cost/token/latency rollups | `GET /tasks/{id}/trace`, `GET /tasks/{id}/cost` |
| **MCP** | All tools exposed to external MCP clients over stdio JSON-RPC, sensitive tools gated by the same approval signatures | `mcp_server/server.py` |

## Quickstart

```bash
docker compose up -d postgres redis
uv run uvicorn api.server:app --reload                                # API on :8000
uv run celery -A worker.celery_app worker --pool=threads --concurrency=4   # worker

# from another shell — walks the whole platform in three tasks:
uv run python scripts/demo.py
```

`LLM_PROVIDER` defaults to `fake` — deterministic, zero API keys, what CI uses.
For real models:

```bash
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-or-...
```

Model selection lives entirely in `config/routing.yaml` (role → model, costs).
The demo runs a parallel-specialist task, a reviewer-rejection retry, a
memory-informed follow-up, and a durable human-approval pause — then prints
the trace-explorer, dashboard, approval-queue, and memory-dashboard URLs.

## What is verified (not claimed)

All numbers come from committed artifacts; nothing below is hand-written.

**Test gates** — **156 unit tests pass** (FakeProvider, no network) plus
integration/e2e tests against real Postgres + Redis, with `mypy` and `ruff`
clean. CI (`.github/workflows/ci.yml` inside `orchestra/`) runs lint, type
check, unit tests, and the integration suite on every push.

**Eval harness** (`evals/results.md`, reproduced by
`uv run python -m evals.report`): the locked 100-task set, 6 configurations
(full / no-reviewer / no-parallel / no-memory / no-hitl / cheap-only), 3
repeats, single-agent baseline, judge validated against 20 hand-labeled
samples. Current table is a **fake-provider dry run** — it proves the harness
plumbing end to end (all configs 100%, spread 0); live OpenRouter numbers land
in the same table via `uv run python -m evals.run --provider openrouter`
(budget-capped and deduplicated through the `llm_cache` table).

**Injection suite** (`security/results.md`):

| Suite | Pass rate |
|---|---|
| Undefended (obeys injected commands) | 0/25 |
| Defended (data framing + standing policy) | 25/25 |

(Fake-provider baseline: the undefended stand-in obeys injected commands, the
defended run refuses them. Live OpenRouter numbers land in the same table with
`--provider openrouter`.)

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
| `/explorer` · `/dashboard` · `/approvals/ui` · `/memory/ui` | UIs (trace explorer, cost dashboard, approval queue, memory) |

## Architecture & stack

| Layer | Choice |
|---|---|
| Models | OpenRouter via httpx (`llm/provider.py`), role-routed by `config/routing.yaml` |
| Graph | LangGraph + `AsyncPostgresSaver` (psycopg3) checkpoints, `interrupt()` for HITL |
| Queue | Celery + Redis, late acks, redelivery on worker loss |
| Data | Postgres 16 + pgvector (memories: cosine top-k, HNSW) |
| API/UI | FastAPI serving static HTML/JS (no build step) |
| Observability | OpenTelemetry spans → custom Postgres exporter, per-call costs |
| Sandbox | Docker SDK: no network, capped CPU/memory/PIDs, read-only rootfs |

## Repository layout

```
orchestra/
  api/          FastAPI app, routes, repository, run_metadata
  agents/       supervisor, specialists (bounded tool loop), reviewer
  graph/        LangGraph build, state, HITL gates, sanitize, replay
  tools/        registry, audited execution, jailed builtins, docker sandbox
  worker/       celery app + durable run/resume tasks
  memory/       pgvector store + retrieval/extraction
  llm/          provider ABC, fake, openrouter, embeddings
  evals/        locked 100-task set, graders, matrix runner, report
  security/     25-case injection suite, runner, report
  mcp_server/   stdio MCP server over the tool registry
  migrations/   001–007 (applied automatically at startup)
  web/          explorer, dashboard, approvals, memory dashboards
  docs/         decisions log, architecture, plans
design.md       Apple-style design-system spec for the web UIs
```

## Documentation map

| Doc | Contents |
|---|---|
| [`orchestra/README.md`](orchestra/README.md) | Deep-dive: durability, HITL, replay, tool safety, full quickstart |
| [`orchestra/docs/architecture.md`](orchestra/docs/architecture.md) | Architecture reference |
| [`orchestra/docs/decisions.md`](orchestra/docs/decisions.md) | Append-only decision log with reasons |
| [`orchestra/docs/plans/2026-09-26-next-build-roadmap.md`](orchestra/docs/plans/2026-09-26-next-build-roadmap.md) | The task-by-task build plan (51 tasks, 8 phases) |
| [`orchestra/evals/results.md`](orchestra/evals/results.md) | Eval matrix (reproducible in one command) |
| [`orchestra/security/results.md`](orchestra/security/results.md) | Injection-suite results |
| [`design.md`](design.md) | "Cupertino Precision Minimalism" design system for the UIs |

## Honest limitations

- The eval and injection numbers currently committed come from the
  deterministic fake provider. The harness, cache, budget guard, and judge
  gate are all real; the **live-model** runs are the remaining step before the
  results describe model quality rather than plumbing.
- Tool-output sanitization is one heuristic layer — the approval gates remain
  authoritative for sensitive actions.
- File tools are jailed to per-task workspaces, not a full OS sandbox; the
  code-execution sandbox is the security boundary for arbitrary code.
