# Orchestra: Next-Build Roadmap — Implementation Plan

> **For the executing agent:** Follow this plan task-by-task, test-first (write failing test → run it → minimal implementation → run it → commit). One phase = one branch = one PR. Every changed line traces to a task number.

**Goal:** Take Orchestra from its audited walking skeleton to the Phase-8 exit criteria in `orchestra/files/phases.md`: durable runs that survive worker kills, real tools behind a Docker sandbox, a reviewer loop with Postgres-backed tracing, durable four-level human-in-the-loop, pgvector long-term memory, a reproducible 100-task eval harness, an injection suite, replay, and a demo-ready explorer served by FastAPI.

**Current state (verified 2026-09-26):** `pytest tests` = 31 pass / 2 skip (Postgres-dependent). Audit commits already fixed: dict-state reducers, single-dispatch scheduling, review retry cap, Postgres task persistence + real SSE, workspace-jail/SSRF hardening, synchronous span exporter, real lint/type/CI gates. Still missing: LangGraph checkpointer, Celery worker, `run_metadata` lifecycle, real LLM provider, tool execution loop (specialists never call tools today), traces/costs wiring, HITL resume, pgvector memory, evals, injection suite, explorer UI, README.

**Architecture locked by user (2026-09-26):** OpenRouter via httpx behind `llm/provider.py`; pgvector in Postgres (not ChromaDB); FastAPI-served static UI (not Next.js); full roadmap detailed. These supersede TRD/rules on OpenAI+Anthropic and Chroma, todo D4/D8, and the 5a plan's asyncpg-based `PostgresSaver` sketch (real `AsyncPostgresSaver` takes a psycopg3 pool).

**Tech Stack:** Python 3.14 (recorded deviation) + uv, FastAPI + asyncpg, LangGraph + AsyncPostgresSaver (psycopg3), Celery + Redis, Postgres 16 + pgvector, OpenTelemetry SDK + custom Postgres span exporter, Docker SDK sandbox, OpenRouter via httpx, pytest/pytest-asyncio.

**Repo conventions:** phase branches `phase-N-slug`; commits in existing style (`feat:`, `fix:`, `chore:`, `test:`); async tests need `@pytest.mark.asyncio` (asyncio_mode=strict); DB tests reuse the `postgres_pool` fixture (auto-skip); live-model tests marked `live`; container tests marked `integration`; update `docs/decisions.md` and `tasks/lessons.md` at every phase exit; secrets only via env.

---

## Phase 0 — Documentation discovery (make-plan)

**Sources consulted**

| Source | Governs | Precedence notes |
|---|---|---|
| `orchestra/files/phases.md` | Phase 0–8 goals, exit criteria, cut order | Backbone of this plan |
| `orchestra/files/todo.md` | Locked decisions D1–D8, exact test names, definition of done | Test names are reused verbatim |
| `orchestra/files/architecture.md` | Flows A–D, folder layout, stack table | Celery + checkpointer mandatory |
| `orchestra/files/TRD.md` | REST `/v1` surface, tables, Pydantic models, security reqs | Some choices superseded (see below) |
| `orchestra/files/rules.md` | Approved libraries, error-handling table, AI boundaries | No custom approval queue, no OTLP exporter, no direct provider SDK in graph |
| `orchestra/PRD.md` | M1–M16 must-haves, success metrics | Outcomes to preserve |
| `docs/superpowers/specs/2026-09-25-phase-5-complete-platform-design.md` | Newer accepted decisions: OpenRouter, pgvector, 5 pillars, two UI views | Wins over TRD on conflict |
| `docs/superpowers/plans/2026-09-25-phase-5a-durability.md` | Task sketch for durability | API corrected (`AsyncPostgresSaver`, psycopg) |
| `docs/decisions.md` | Recorded deviations: Python 3.14, Postgres 16, worker absent, in-process sandbox | Extend, don’t contradict silently |

*(gsd-ultraplan-phase is a Claude Code cloud offload skill; not applicable in this environment — planning stays local. plan-writing suggests repo-root filenames; writing-plans’ `docs/plans/` convention wins, consistent with the existing superpowers plans.)*

**Allowed APIs (verified; do not invent beyond these)**

- LangGraph: `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`; `AsyncPostgresSaver(pool)` where pool is `psycopg_pool.AsyncConnectionPool` (**not** asyncpg); `await saver.setup()`; `builder.compile(checkpointer=saver)`; resume `await graph.ainvoke(None, {"configurable": {"thread_id": task_id}})`; `Command(resume=value)`; `interrupt(payload)`; `Send(node, payload)`.
- Celery: `Celery("orchestra", broker=...)`; `task_acks_late=True`; `task_reject_on_worker_lost=True`; `worker_prefetch_multiplier=1`; eager mode for tests via `task_always_eager=True`.
- OpenRouter: `POST https://openrouter.ai/api/v1/chat/completions`, OpenAI-compatible body, `Authorization: Bearer $OPENROUTER_API_KEY`; no reliable `json_schema` support across models → prompt-constrained JSON + `model_validate_json` + one retry (tenacity).
- pgvector: `CREATE EXTENSION IF NOT EXISTS vector`; `embedding vector(1536)`; cosine `ORDER BY embedding <=> $1::vector`; HNSW index. Postgres image must be `pgvector/pgvector:pg16`.
- OTel: sync `SpanExporter.export` (already implemented in `observability/exporter.py`) + `BatchSpanProcessor` + `TracerProvider`.
- Docker SDK: `containers.run(..., network_disabled=True, mem_limit="256m", nano_cpus=500_000_000, pids_limit=64, read_only=True, tmpfs={"/work": "rw,size=64m"})`; `container.wait(timeout=...)`, `container.kill()` on timeout, `container.logs()`.
- Existing modules to extend: `graph/build.py`, `graph/state.py`, `graph/hitl.py`, `agents/*`, `tools/registry.py`, `tools/permissions.py`, `tools/builtin/*`, `api/server.py`, `api/repository.py`, `api/routes.py`, `migrations/runner.py`, `observability/*`, `llm/*`, `worker/` (new).

**Anti-pattern guards (reject on sight)**

- Never hand the asyncpg pool to the checkpointer; wrong driver.
- Never call `interrupt()` inside a node that also calls an LLM (the node replays on resume — you pay twice). Approval lives in its own node.
- No `operator.add` on dict state channels (caused the original total failure); use `merge_dicts`.
- No OTLP HTTP exporter in app code (D6: custom Postgres exporter only); `observability/tracing.py`’s OTLP manager is deleted.
- No Chroma/`chromadb` references after Phase 5; no `task_costs` table (superseded by `run_metadata` + spans).
- No direct provider SDK calls in `agents/` or `graph/`; everything goes through `llm/provider.py`.
- No hard-coded model names outside `config/routing.yaml`.
- No secrets in repo; no raw Docker socket in production worker (socket proxy there); no approval timeout (rules.md).
- No new abstraction until two callers exist.

---

## Phase 1 — Durability: finish the Phase 1 exit (branch `phase-1-durability`)

> Exit criteria (phases.md): a task runs end to end with FakeProvider; killing the worker mid-run and restarting resumes from the last checkpoint with no repeated completed steps; the four Phase 1 tests in todo.md pass.
> The 5a plan’s migration + runner + `test_run_metadata.py` already exist and pass — do not redo them; build the missing lifecycle.

### Task 1: Durability dependencies, compose worker, decisions entry

**Files:** `pyproject.toml`, `docker-compose.yml`, `.env.example`, `docs/decisions.md`
**Steps**
1. Add deps: `uv add "celery[redis]" langgraph-checkpoint-postgres "psycopg[binary,pool]" pydantic-settings`
2. Compose edits: postgres image → `pgvector/pgvector:pg16` (adopt now; memory phase needs it and data is disposable); remove the `chromadb` service + volume and `CHROMA_*` api env; add the worker service (celery -A worker.celery_app worker, concurrency 2, depends_on postgres+redis healthy).
3. `.env.example`: add `OPENROUTER_API_KEY=`, `TAVILY_API_KEY=`, `CELERY_BROKER_URL=redis://localhost:6379/0`, `WORKSPACES_ROOT=./workspaces`.
4. Append a decisions entry: checkpointer driver choice, pgvector image, worker restored.
**Verify:** `uv run pytest tests/unit -q` → 31 passed; `docker compose config --quiet` exits 0.
**Commit:** `chore: add durability dependencies, pgvector image and a celery worker service`

### Task 2: Checkpointer module

**Files:** Create `graph/checkpointer.py`; Test `tests/graph/__init__.py`, `tests/graph/test_checkpointer.py`; Modify `graph/build.py`
Test asserts `create_checkpointer()` returns an `AsyncPostgresSaver` and `checkpoints`/`checkpoint_blobs` tables exist (gated by `postgres_pool`).
Implementation: `AsyncConnectionPool(conninfo=dsn, min_size=1, max_size=4, open=False)` → `await pool.open()` → `AsyncPostgresSaver(pool)` → `await saver.setup()`.
`graph/build.py`: `__init__(self, llm, hitl_enabled=None, checkpointer=None)`; `hitl_enabled` defaults to `bool(checkpointer)`; `builder.compile(checkpointer=self.checkpointer)`.
**Commit:** `feat: wire the LangGraph postgres checkpointer into the graph`

### Task 3: `run_metadata` lifecycle

**Files:** Create `api/run_metadata.py`; Test `tests/migrations/test_run_metadata_lifecycle.py`
Functions: `start_run(pool, run_id, task_id, task_description)`, `complete_run(pool, run_id, *, prompt_tokens, completion_tokens, cost_usd, latency_ms, model_breakdown)`, `fail_run(pool, run_id, error)`, `mark_paused(pool, run_id)`, `latest_run_id(pool, task_id)`.
**Commit:** `feat: add run_metadata lifecycle for task analytics`

### Task 4: Celery app + durable `run_task`

**Files:** Create `worker/__init__.py`, `worker/celery_app.py`, `worker/tasks.py`; Modify `llm/fake.py`
Celery config: `task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`, `task_track_started=True`.
`run_task` (sync entrypoint running `asyncio.run`): create asyncpg pool, run migrations, load task row, create checkpointer, build graph with it, set status running; if a checkpoint exists → `ainvoke(None, config)` (crash redelivery / HITL resume), else `start_run` + fresh invoke; on success `save_task_plan` + `complete_task` + `complete_run`; on failure `fail_task` + `fail_run`; always close pools.
FakeProvider hooks: `FAKE_DELAY_SECONDS` sleep, `FAKE_COMPLETION_LOG` append per call.
Unit test `tests/unit/test_worker_config.py` asserts acks-late and prefetch settings.
**Commit:** `feat: add the celery worker and durable graph execution task`

### Task 5: API enqueues jobs (remove BackgroundTasks)

**Files:** Modify `api/server.py`; Test `tests/integration/test_api_celery_roundtrip.py` (marked `integration`)
`create_task` calls `run_task.delay(...)`; drop in-request execution. Roundtrip test polls until terminal.
**Commit:** `feat: enqueue graph runs on celery instead of FastAPI background tasks`

### Task 6: Kill/resume proof + durability doctor

**Files:** Test `tests/integration/test_run_resumes_after_worker_kill.py`; Create `scripts/test_durability.py`
Test kills a worker mid-run (SIGKILL), restarts, asserts completed, no repeated subtasks, run_metadata latency > 0. Script loops 20× and reports pass rate.
**Commit:** `test: prove runs resume after a worker kill`

### ✅ Checkpoint 1 (Phase 1 exit — review with human before Phase 2)
- [ ] `test_run_resumes_after_worker_kill` passes; each of the four todo.md Phase-1 tests exists and passes
- [ ] `docker compose up` brings api + worker + postgres + redis healthy
- [ ] `POST /tasks` → `GET /tasks/{id}` reaches `completed`; SSE emits `status` then `done`
- [ ] `run_metadata` row matches the run; `docs/decisions.md` + `tasks/lessons.md` updated

---

## Phase 2 — Tools and specialists (branch `phase-2-tools`)

> Exit: ≥95% of 20 live tasks produce a schema-valid plan; all tool-safety tests pass (permission block, rate limit, workspace jail, sandbox no-network + timeout); a parallel run is measurably faster than sequential.

### Task 7: Tool bootstrap + per-task workspace
Create `tools/bootstrap.py`: `build_tool_registry(task_id, *, search_backend=None)` registering web_search, http_get, file_read, file_write, code_execute, db_query with per-task workspace root; mark sensitive tools. Test `tests/unit/test_tool_bootstrap.py`.
**Commit:** `feat: register builtin tools per task with a jailed workspace`

### Task 8: `tool_calls` audit table
Create `migrations/003_tool_calls.sql` (arguments JSONB, result JSONB, status, error, latency_ms, sensitive, created_at, index on task_id), `tools/execution.py` `execute_tool(...)` + `log_tool_call(...)`. Test asserts every call logged with inputs/outputs/latency/status.
**Commit:** `feat: log every tool call with inputs, outputs, latency and status`

### Task 9: Specialist tool-calling loop
Modify `agents/specialists.py`: `ToolCall`, `SpecialistTurn` models; `run(..., executor=None, max_iterations=5)` loop: final_answer → return; tool_call → execute via executor → observation appended; unknown tool → feedback; cap → partial. Update `FakeProvider.DEFAULT_RESPONSES["Role:"]`. Test `tests/unit/test_specialist_tools.py`.
**Commit:** `feat: give specialists a bounded tool-calling loop`

### Task 10: Real web search (Tavily) with deterministic fallback
`TavilySearchTool` via `tavily-python` in `asyncio.to_thread`; missing key → clear error; simulated backend stays default for FakeProvider. Test mocks client.
**Commit:** `feat: add tavily web search with a simulated test backend`

### Task 11: Read-only SQL tool
Create `tools/builtin/db_tools.py`: read-only connection + statement allowlist + row cap + statement timeout. Tests reject DML/DDL/multi-statement.
**Commit:** `feat: add a read-only SQL tool with a statement allowlist`

### Task 12: Docker sandbox replaces the in-process executor
Rewrite `tools/builtin/sandbox.py`, create `tools/sandbox_runner.py`: docker SDK, no network, cpu/mem/pids limits, read-only rootfs, per-task workspace at /work, timeout kill. Unit test asserts flags + kill; integration test asserts no network and `print(2+2)`→4.
**Commit:** `feat: execute code in a real docker sandbox with no network`

### Task 13: Failure handling + parallelism proof
`route_next_subtasks`: error results retried once (cap 2) then escalate. Unit `test_second_failure_on_subtask_escalates`; integration `test_parallel_independent_subtasks_run_concurrently` (0.3s delay × 4 subtasks, wall < 1.0s).
**Commit:** `fix: retry failed subtasks once, then escalate; prove parallel fan-out`

### Task 14: Live plan-validity run (20 tasks)
`scripts/live_plan_check.py --provider openrouter --limit 20` writes `evals/output/plan_validity.json`; `tests/live/test_live_plan_validity.py` asserts ≥0.95 (marked `live`).
**Commit:** `test: measure live plan validity on 20 sample tasks`

### ✅ Checkpoint 2 (Phase 2 exit)
- [ ] Registry permission, rate-limit, jail and sandbox tests pass; sandbox has no network + timeout
- [ ] Parallel test beats sequential wall clock; 20 live tasks ≥95% schema-valid
- [ ] No secrets committed; decisions/lessons updated

---

## Phase 3 — Reviewer loop and tracing (branch `phase-3-observability`)

> Exit: a rigged bad specialist output is caught, sent back, fixed; the trace shows the full loop with per-step cost and latency.

### Task 15: Spans migration + tracing setup
`migrations/004_spans.sql` (DDL from exporter, moved out of runtime), `observability/setup.py configure_tracing(pool)` idempotent; delete OTLP `observability/tracing.py`; wire into api + worker. Test `tests/unit/test_tracing_setup.py`.
**Commit:** `feat: persist spans through a postgres migration and tracing setup`

### Task 16: Instrument graph, tools, LLM
`observability/spans.py` helper; `llm/recording.py` `RecordingLLMProvider` (span per call + RunRecorder tokens/cost); instrument supervisor/specialists/tools/reviewer; persist totals to run_metadata. Test `test_trace_contains_span_per_agent_tool_and_memory_call` with in-memory exporter; integration `test_spans_persisted`.
**Commit:** `feat: trace supervisor, specialists, tools, reviewer and llm calls`

### Task 17: Trace endpoint + cost rollup
`GET /tasks/{id}/trace` span tree; `GET /tasks/{id}/cost` run_metadata totals + model_breakdown; assert totals == sum of spans. Integration test.
**Commit:** `feat: expose a task trace tree and cost rollup`

### Task 18: Rigged reviewer loop proof
Integration test: bad output → retry → accept, ≥2 specialist spans, reviewer span, latency > 0.
**Commit:** `test: prove a bad output is caught, retried and traced`

### ✅ Checkpoint 3 (Phase 3 exit)
- [ ] Trace contains every step with cost/latency; totals match `run_metadata`
- [ ] Reviewer rejection → retry → accept demonstrated end-to-end

---

## Phase 4 — Human-in-the-loop (branch `phase-4-hitl`)

> Exit: a sensitive step pauses indefinitely, survives a worker restart, and all four decisions resume correctly.

### Task 19: `config/escalation.yaml` + loader
YAML triggers/levels; `graph/escalation.py` loader; parity test with `ESCALATION_TRIGGERS`.
**Commit:** `feat: drive escalation triggers from config/escalation.yaml`

### Task 20: Replay-safe approval nodes
`graph/approval_nodes.py`; `pending_approvals` dict channel; plan gate after supervisor (dedicated node, no LLM inside); sensitive-tool gate via signature-keyed approvals; `hitl_enabled` default on with checkpointer. Unit tests with `InMemorySaver`: low-confidence pause, sensitive tool pause.
**Commit:** `feat: pause for plan and sensitive-action approval at dedicated nodes`

### Task 21: Decision → resume via the worker
`POST /approvals/{id}/decide` → persist + `resume_task.delay`; `resume_task` invokes `Command(resume=...)`; `clarify` answers from checkpoint context without resuming. Unit test all four decisions.
**Commit:** `feat: resume paused graphs from approval decisions`

### Task 22: Second-failure escalation via HITL
Escalate status with HITL → approval gate second_failure. Test.
**Commit:** `feat: escalate repeated subtask failures to a human`

### Task 23: Approval page upgrade
Context panel, four buttons, clarify chat, 3s polling. Verify in Preview.
**Commit:** `feat: flesh out the approval page with context and clarify chat`

### Task 24: Durable pause proof
Integration: pause → SIGKILL worker → restart → decide → completes.
**Commit:** `test: prove a paused run survives a worker restart`

### ✅ Checkpoint 4 (Phase 4 exit)
- [ ] All four decisions resume correctly; pause survives restart; sensitive tools gated; no approval timeout anywhere

---

## Phase 5 — Long-term memory with pgvector (branch `phase-5-memory`)

> Exit: on a repeated task family, planning with memory is measurably better (numbers land in Phase 6); deleting a user’s memories removes all vector rows and metadata, proven by test.

### Task 25: Memories migration
`migrations/005_memories.sql`: vector extension, memories table (user_id, kind, content, embedding vector(1536), importance, access_count, last_accessed_at, source_task_id), btree user_id, HNSW cosine. Extend migration test.
**Commit:** `feat: add the pgvector memories migration`

### Task 26: Embeddings interface
`llm/embeddings.py`: `EmbeddingProvider`, `OpenAIEmbeddingProvider` (text-embedding-3-small, httpx+retry), `FakeEmbedding` deterministic. Test.
**Commit:** `feat: add an embeddings interface with a deterministic fake`

### Task 27: Store/retrieve rewrite on pgvector
Rewrite `memory/store.py` + `retrieve.py`, drop Chroma; cosine top-k scoped to user; delete removes rows. Tests: per-user scoping, delete removes all.
**Commit:** `feat: store and retrieve memories with pgvector`

### Task 28: Wire extraction and retrieval into the run
Post-completion extraction; supervisor accepts memory context; `Plan.memory_ids_used`; span attrs record ids. Tests: extracted after task, similar task retrieves past plan.
**Commit:** `feat: inject retrieved memories into planning and record their ids`

### Task 29: Memory API + dashboard
`GET/DELETE /users/{id}/memories`; `web/memory.html`.
**Commit:** `feat: expose and delete user memories; add a memory dashboard`

### Task 30: Importance scoring (stretch = cut first)
access_count, recency half-life blended into ranking; consolidation/expiry left out.
**Commit:** `feat: score memory importance by access and recency`

### ✅ Checkpoint 5 (Phase 5 exit)
- [ ] Extraction, retrieval, per-user scoping, deletion all tested; memory ids visible in traces; Chroma fully gone (`rg -i chroma` empty)

---

## Phase 6 — Evaluation harness (branch `phase-6-evals`) — highest-value phase

> Lock the task set and metrics **before** tuning. Exit: one command reproduces a results table with variance; no number anywhere unless it is in that table.

### Task 32: Task set + graders
`evals/build_task_set.py` → `evals/tasks/task_set.jsonl` (100 tasks, 4×25, repeated-family flags); `evals/graders.py` deterministic + LLM judge.
**Commit:** `feat: lock a 100-task eval set with deterministic graders`

### Task 33: Judge validation
20 hand-labeled samples; agreement % + gate `--min-agreement 0.8`.
**Commit:** `feat: validate the llm judge against 20 hand-labeled samples`

### Task 34: Runner + configs + cache
`evals/run.py`, `evals/configs/*.yaml` (Full/No-reviewer/No-parallel/No-memory/No-HITL/Cheap-only), `evals/cache.py` + `migrations/006_llm_cache.sql`, `migrations/007_eval_tables.sql`; 3 repeats; fake dry-run for CI.
**Commit:** `feat: run the eval matrix with caching and repeats`

### Task 35: Single-agent baseline
`evals/baseline.py` same tools/model, one agent.
**Commit:** `feat: add a single-agent baseline to the harness`

### Task 36: Report
`evals/report.py` → `evals/results.md` with mean ± spread; one command.
**Commit:** `feat: generate the results table with one command`

### Task 37: Routing experiment (cut candidate #4)
`config/routing.yaml` variants; cost saved vs quality delta.
**Commit:** `feat: compare cheap-only and role-routed model routing`

### Task 38: Failure analysis
`evals/failures.md` 10 worst; fix top cause; re-run.
**Commit:** `fix: address the top recurrent eval failure cause`

### ✅ Checkpoint 6 (Phase 6 exit)
- [ ] `evals/results.md` reproducible via one command, includes variance and judge agreement
- [ ] Never-cut claim true: README numbers will come only from this table

---

## Phase 7 — Security and replay (branch `phase-7-security`)

> Exit: injection pass rate reported undefended and defended; a replayed run with one edited input shows a divergence diff.

### Task 39: Injection suite
`security/injection_suite/cases.yaml` (≥25 cases, 4 classes), `security/run_injection.py`, baseline report.
**Commit:** `test: add a 25-case prompt-injection suite with a baseline`

### Task 40: Defenses + before/after report
`graph/sanitize.py` data-framing + instruction-like flagging; prompt hardening; `security/report.py`.
**Commit:** `feat: defend tool output and report injection pass rates`

### Task 41: Replay with divergence diff
`graph/replay.py`, `POST /tasks/{id}/replay`, `scripts/replay.py`; test divergence.
**Commit:** `feat: replay a run from a checkpoint with an edited input`

### Task 42: MCP server (consumer = cut candidate #5)
`mcp_server/server.py` exposes tools; test lists schemas.
**Commit:** `feat: expose orchestra tools over MCP`

### ✅ Checkpoint 7 (Phase 7 exit)
- [ ] Injection pass rates recorded before/after; replay diff demonstrated

---

## Phase 8 — Explorer UI, polish, ship (branch `phase-8-ship`)

> Exit: a stranger can clone, run one command, and see the whole system work; README and video match the running system.

### Task 44: Trace explorer (static)
`web/explorer.html` + `web/static/explorer.js` + css; `/explorer`, `/tasks/{id}/explorer`; tree, status colors, node detail. Verify with Preview.
**Commit:** `feat: add a static trace explorer`

### Task 45: Cost dashboard
`web/dashboard.html`; `GET /stats/cost`.
**Commit:** `feat: add a cost and escalation dashboard`

### Task 46: Demo script
`scripts/demo.py`: parallel specialists → reviewer rejection → memory-informed plan → human approval → trace URLs.
**Commit:** `feat: add a one-command scripted demo`

### Task 47: E2E + CI
`tests/e2e/test_demo_path.py`; CI integration + e2e jobs.
**Commit:** `test: run the demo path end-to-end in CI`

### Task 48: README + docs
README rewrite from real results; `docs/architecture.md`, `docs/api.md`.
**Commit:** `docs: write the README and API/architecture docs from real results`

### Task 49: Clean-machine verification + demo video
Clone to temp dir, compose up, demo + eval dry-run; record gotchas; video per script.
**Commit:** `docs: verify the clean-clone quickstart and record the demo`

### Task 50 (cut candidate #2): single-VM deploy — only after everything above is green.

### Task 51: Final verification phase (make-plan)
- [ ] Gates: ruff, mypy, unit, integration, e2e
- [ ] Grep anti-patterns (`chroma|OTLPSpanExporter|operator.add|task_costs`)
- [ ] Phase exit criteria re-checked with evidence; README numbers trace to evals; todo.md definition of done checked
**Commit:** `chore: final verification notes and decisions update`

---

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Celery/psycopg on Python 3.14 | High | Task 1 verifies install + worker boot immediately; fallback pin `celery>=5.5` |
| Checkpointer API mismatch (asyncpg vs psycopg) | High | Task 2 test asserts real table creation; only `AsyncPostgresSaver` documented as allowed |
| Interrupt replay re-calling LLMs | Medium | Dedicated approval nodes; signature-keyed approvals; documented replay cost |
| Docker unavailable in dev/CI | Medium | Unit tests mock the SDK; container test marked `integration`; skipped when absent |
| Eval cost overrun ($30–60 budget) | High | Prompt-hash cache; FakeProvider dry-runs; cheap judge after validation |
| LLM judge bias | Medium | 20 hand-labeled samples; publish agreement; deterministic checks first |
| pgvector volume recreate | Medium | Adopt pgvector image in Phase 1 (disposable data), decisions entry |
| Scope creep | Medium | One phase = one branch = one PR; every change maps to a task; cut list applied in order |
| Flaky plans | Medium | Tighten schema/prompt first; few-shot from memory; never add another agent (rules.md) |

## Cut order if behind (from phases.md)
1. Memory consolidation/expiry (Task 30) → 2. VM deploy (Task 50) → 3. cost dashboard aggregates (Task 45, keep per-task cost) → 4. routing experiment (Task 37) → 5. MCP consumer (Task 42, keep server).
**Never cut:** durable resume, reviewer loop, four HITL levels, eval harness, injection suite.

## Open questions (answer before their phase)
1. **Tavily vs built-in search:** simulated backend default for FakeProvider runs, Tavily when `TAVILY_API_KEY` set — confirm.
2. **Approval scope:** per tool-call signature; no “approve for the rest of this run” (default: no; can add in Phase 4).
3. **Repeated-family memory metric:** Phase 6 measures plan-with-memory vs without via success-rate deltas — confirm that satisfies Phase 5 exit.
