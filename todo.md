# Orchestra: Multi-Agent Orchestration Platform — Build Plan

Target: production-grade, eval-backed portfolio project for AI Engineer roles.
Budget: ~50 h/week, 4 weeks (≈28 working days). Copy this file to `tasks/todo.md`.

## Rules of engagement (Karpathy-style)
- Write the failing test first, then the minimum code that passes it.
- One phase = one branch = one PR. Every changed line traces to a task below.
- No abstraction until it has two users. No feature not listed here.
- If a phase misses its exit criteria, cut scope from a later phase (see Cut List), never weaken the criteria.
- After any correction or bug root cause, add a rule to `tasks/lessons.md`.
- Assumptions and tradeoffs go in `docs/decisions.md` as they are made.

## Locked decisions (revisit only with a written reason)
| # | Decision | Reason |
|---|---|---|
| D1 | Python 3.11, `uv`, Pydantic v2, FastAPI | Standard, typed |
| D2 | LangGraph with `PostgresSaver` checkpointer; `interrupt()` for human-in-the-loop | Durable pause/resume without a custom queue |
| D3 | Celery + Redis only as task broker and pub/sub for live UI. No Redis working memory | Graph state in Postgres already covers it |
| D4 | ChromaDB for long-term memory, Postgres for metadata | Matches spec |
| D5 | Provider interface `llm/provider.py` + `routing.yaml`; a `FakeProvider` for tests | Model-agnostic, deterministic CI |
| D6 | OpenTelemetry spans, custom exporter writing to Postgres (JSONB) | Explorer UI can query it directly |
| D7 | Code execution in a Docker container: no network, CPU/mem/time limits, read-only FS except `/work` | Real sandbox |
| D8 | UI: Next.js trace explorer + plain approval page | Fits existing stack |

## Repo layout
```
orchestra/
  api/            FastAPI routes, schemas
  graph/          state.py, build.py, nodes/
  agents/         supervisor.py, reviewer.py, specialists/
  tools/          registry.py, permissions.py, builtin/
  llm/            provider.py, fake.py, routing.yaml
  memory/         store.py, extract.py, retrieve.py
  observability/  tracing.py, exporter.py, cost.py
  evals/          tasks/, graders/, run.py, report.py
  security/       injection_suite/
  web/            Next.js app (trace explorer, approvals)
  tests/          unit/, integration/, e2e/
  docs/           decisions.md, architecture.md
  tasks/          todo.md, lessons.md
  docker-compose.yml
```

---

## Phase 0 — Foundations (Day 0, ~4 h)
- [ ] Create repo, `uv init`, ruff + mypy + pytest config, pre-commit
- [ ] CI (GitHub Actions): lint, type-check, unit tests on every PR
- [ ] `docker-compose.yml`: Postgres, Redis, ChromaDB, API, worker (health checks on all)
- [ ] `.env.example`, secrets never committed
- [ ] `llm/provider.py`: `complete()`, `complete_structured(schema)`, token + cost accounting; `FakeProvider` returning scripted outputs
- [ ] `docs/decisions.md`, `tasks/lessons.md` created

**Exit:** `docker compose up` healthy; CI green on an empty test; FakeProvider unit test passes.

## Phase 1 — Walking skeleton (Days 1–2)
Tests first:
- [ ] `test_plan_rejects_cycles`
- [ ] `test_plan_rejects_unknown_specialist`
- [ ] `test_plan_topological_order`
- [ ] `test_run_resumes_after_worker_kill` (integration)

Build:
- [ ] `graph/state.py`: `Task`, `Subtask`, `Plan`, `GraphState` (results by subtask id, errors, retry counts, confidence)
- [ ] Plan validator (DAG check, schema, specialist whitelist)
- [ ] Supervisor node with structured-output planning
- [ ] One stub specialist; nodes: intake → plan → execute → synthesize → deliver
- [ ] Compile graph with Postgres checkpointer
- [ ] Celery task wraps graph run; API: `POST /tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/events` (SSE)

**Exit:** a task runs end to end with FakeProvider; killing the worker mid-run and restarting resumes from the checkpoint with no repeated completed steps.

## Phase 2 — Tools and specialists (Days 3–6)
Tests first:
- [ ] `test_registry_blocks_unpermitted_tool`
- [ ] `test_rate_limit_enforced`
- [ ] `test_every_call_logged_with_inputs_outputs_latency_status`
- [ ] `test_file_tool_cannot_escape_workspace`
- [ ] `test_sandbox_no_network_and_timeout`
- [ ] `test_parallel_independent_subtasks_run_concurrently`

Build:
- [ ] Tool registry: name, description, JSON schemas, allowed specialists, rate limit; `tool_calls` table
- [ ] Tools: web search, file read/write (jailed workspace), sandboxed code exec, read-only DB query, HTTP call (domain allowlist)
- [ ] Specialists: research, data analysis, writer, code executor (each with its own tool permissions and prompt)
- [ ] Parallel fan-out for independent subtasks (LangGraph `Send`), sequential for dependent ones
- [ ] Failure handling: retry with a different approach (prompt variant + tool hint), max 2 attempts, then mark `escalate`
- [ ] Run 20 sample tasks against real models; log plan validity rate

**Exit:** ≥95% of 20 sample tasks yield valid plans; all tool-safety tests pass; a parallel run measurably beats sequential wall-clock.

## Phase 3 — Reviewer loop and tracing (Days 7–9)
Tests first:
- [ ] `test_reviewer_rejects_deliberately_bad_output`
- [ ] `test_rejection_routes_back_with_feedback_and_caps_at_N`
- [ ] `test_trace_contains_span_per_agent_tool_and_memory_call`

Build:
- [ ] Reviewer agent with a scored rubric (correctness, completeness, format, sources); threshold in config
- [ ] Conditional edges: accept / retry with feedback / escalate
- [ ] OTel instrumentation: spans for supervisor, specialists, tool calls, reviewer, LLM calls (attrs: agent, model, tokens, cost, prompt/response refs)
- [ ] Custom exporter → Postgres `spans` table; `GET /tasks/{id}/trace`
- [ ] Per-task cost/token/latency rollup

**Exit:** a rigged bad specialist output is caught, sent back, fixed, and the trace shows the full loop with costs.

## Phase 4 — Human-in-the-loop (Days 10–12)
Tests first:
- [ ] `test_low_confidence_plan_pauses_for_approval`
- [ ] `test_second_failure_on_subtask_escalates`
- [ ] `test_sensitive_tool_requires_approval`
- [ ] `test_approve_reject_modify_takeover_each_resume_correctly`
- [ ] `test_pause_survives_worker_restart`

Build:
- [ ] Escalation triggers → levels: Notify, Approve action, Approve plan, Take over (mapping table in config)
- [ ] `interrupt()` at decision points with packaged context (task, plan, completed steps, proposed action, reasoning)
- [ ] `approvals` table; API: list pending, decide (approve / modify / reject / take over), clarify (ask the agent a question before deciding)
- [ ] Sensitive-tool flag in registry (delete, external send, payments)
- [ ] Minimal web page: queue, context, buttons, clarification chat

**Exit:** a sensitive step pauses indefinitely, survives a restart, and resumes correctly on each of the four decisions.

## Phase 5 — Long-term memory (Days 13–15)
Tests first:
- [ ] `test_memory_extracted_after_task`
- [ ] `test_similar_task_retrieves_past_plan`
- [ ] `test_memory_scoped_per_user`
- [ ] `test_delete_user_removes_all_memories`

Build:
- [ ] Post-task extraction: request, approach, tools used, outcome, facts, observed preferences → embed → Chroma + Postgres metadata
- [ ] Retrieval at planning: similar tasks, what worked / failed, user preferences; injected into the planning prompt with source ids
- [ ] Importance score (access count, recency); `GET /users/{id}/memories`; `DELETE /users/{id}/memories`
- [ ] Trace spans record which memories were retrieved and used

**Exit:** on a repeated task family, planning with memory beats planning without it on the eval subset (measured in Phase 6).
Stretch (cut first): consolidation and expiry.

## Phase 6 — Evaluation harness (Days 16–20) — the highest-value phase
Lock the task set and metrics **before** tuning.
- [ ] Task set: 100 tasks, 4 categories × 25 (research+summary, data analysis, code, mixed multi-step), with a subset marked repeated-family for memory tests
- [ ] Graders: deterministic checks where possible; LLM-judge with a fixed rubric; validate the judge against 20 hand-labeled samples and report agreement
- [ ] Baselines: single-agent with the same tools and model
- [ ] Ablations: no reviewer, no memory, no parallelism, no plan approval
- [ ] Each configuration run 3× → mean ± spread for success rate, cost, latency, escalation rate
- [ ] Routing experiment: cheap model for easy subtasks and strong model for planning and review; report cost saved and quality change
- [ ] `evals/report.py` generates the markdown results table; one command reproduces it
- [ ] Failure analysis: categorize the 10 worst failures and fix the top cause

**Exit:** reproducible results table with variance. Do not claim any number that is not in this table.

## Phase 7 — Security and replay (Days 21–23)
- [ ] Injection suite (≥25 cases): malicious web content, tool outputs that try to change instructions, exfiltration attempts, cross-user memory leakage
- [ ] Defenses: treat tool output as data, strip/flag instruction-like content, least-privilege permissions, sensitive-action approval; report pass rate before and after
- [ ] Replay: load a past run, step through, edit an input at any step, re-execute from that checkpoint, diff against the original
- [ ] MCP: expose one specialist's tools as an MCP server; consume one external MCP server through the registry

**Exit:** injection suite pass rate reported; a replayed run with an edited input shows a divergence diff.

## Phase 8 — Explorer UI, polish, ship (Days 24–28)
- [ ] Trace explorer (Next.js): tree/graph of agents, status colors (success / warning / failure / escalated), node detail with prompt, response, tools, latency, cost
- [ ] Cost dashboard: cost per task type, per agent, escalation trend
- [ ] Demo script: research task with parallel specialists, reviewer rejection, memory-informed plan, human approval, trace shown
- [ ] E2E tests covering the demo path; CI runs them with FakeProvider
- [ ] README: one-paragraph pitch, architecture diagram, results table, quickstart, limitations honestly stated
- [ ] 4–5 minute demo video
- [ ] Clean-machine test of `docker compose up` + demo script
- [ ] Optional: deploy to a VM with a public explorer link
- [ ] Buffer day for overruns

**Exit:** a stranger can clone, run one command, and see the demo.

---

## Cut list (in order, if behind)
1. Memory consolidation and expiry
2. Cloud deployment
3. Cost dashboard aggregates (keep per-task cost)
4. Routing experiment
5. MCP consumer (keep the server)
Never cut: durable resume, reviewer loop, HITL levels, eval harness, injection suite.

## Risk register
| Risk | Mitigation |
|---|---|
| Flaky plans | Tighten schema and prompt first; add few-shot from memory; never add another agent as a fix |
| Eval cost overrun | Cache LLM calls by hash in dev; cheap model for the judge only after validating agreement |
| LLM-judge bias | Hand-label 20 samples, publish agreement, use deterministic checks where possible |
| Scope creep from Cursor | One file per prompt, test first, list allowed files, reject unrelated diffs |
| Burnout at 50 h/week | Fixed stop time daily, one lighter day per week, keep applications moving in parallel |

## Definition of done
- [ ] All phase exit criteria met
- [ ] CI green (lint, types, unit, integration, e2e)
- [ ] Results table, injection results, and demo in README
- [ ] `docs/decisions.md` complete
- [ ] Demo video recorded
