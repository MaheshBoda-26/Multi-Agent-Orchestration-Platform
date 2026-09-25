# phases.md: Orchestra

Timeline: 4 weeks at ~50 h/week (~28 working days). Detailed day-by-day tasks and test lists are in `tasks/todo.md`; this file is the phase-level contract.

## Phase 0: Foundations
**Goal.** A working skeleton that runs and tests itself, before any agent logic exists.
**Tasks.**
- Repo, `uv` project, ruff, mypy, pytest, pre-commit
- CI (lint, types, unit tests) on every PR
- `docker-compose.yml`: Postgres, Redis, Chroma, API, worker, with health checks
- `llm/provider.py` interface plus `FakeProvider`
- `.env.example`, `docs/decisions.md`, `tasks/lessons.md` created
**Dependencies.** None.
**Definition of done.** `docker compose up` reports all services healthy. CI is green on an empty test suite. A `FakeProvider` unit test passes.

## Phase 1: Walking skeleton
**Goal.** One task runs end to end and survives a crash.
**Tasks.**
- `graph/state.py`: `Task`, `Subtask`, `Plan`, `GraphState`
- Plan validator: cycle check, unknown-specialist check, topological order
- Supervisor node with structured-output planning (FakeProvider in tests)
- One stub specialist; graph wired: intake → plan → execute → synthesize → deliver
- Postgres checkpointer wired in; Celery task wraps the graph run
- API: `POST /tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/events` (SSE)
**Dependencies.** Phase 0.
**Definition of done.** A task runs end to end with `FakeProvider`. Killing the worker mid-run and restarting it resumes from the last checkpoint with no repeated completed steps. The four Phase 1 tests in `todo.md` pass.

## Phase 2: Tools and specialists
**Goal.** Real work happens safely, in parallel where possible.
**Tasks.**
- Tool registry: schemas, per-specialist permissions, rate limits, full call logging
- Tools: web search, file read/write (jailed workspace), sandboxed code exec, read-only DB query, allowlisted HTTP call
- Four specialists: research, data analysis, writer, code executor
- Parallel fan-out for independent subtasks, sequential for dependent ones
- Failure handling: retry with a different approach, cap at 2 attempts, then escalate
- 20-task live-model run to measure plan validity
**Dependencies.** Phase 1 (graph, state, checkpointing).
**Definition of done.** ≥95% of 20 live sample tasks produce a schema-valid plan. All tool-safety tests pass (permission block, rate limit, workspace jail, sandbox no-network and timeout). A parallel run is measurably faster than the same run made sequential.

## Phase 3: Reviewer loop and tracing
**Goal.** Bad output gets caught, and every decision is observable.
**Tasks.**
- Reviewer agent with a scored rubric (correctness, completeness, format, sources)
- Conditional edges: accept, retry-with-feedback (capped), escalate
- OpenTelemetry spans on supervisor, specialists, tool calls, reviewer, LLM calls
- Postgres span exporter; `GET /tasks/{id}/trace`
- Per-task cost, token, and latency rollup
**Dependencies.** Phase 2 (specialists and tool calls to instrument).
**Definition of done.** A rigged bad specialist output is caught, sent back, and fixed. The trace for that run shows the full loop with per-step cost and latency.

## Phase 4: Human-in-the-loop
**Goal.** Risky or low-confidence steps pause for a real person, durably.
**Tasks.**
- Escalation triggers and the four levels (Notify, Approve action, Approve plan, Take over) in `escalation.yaml`
- `interrupt()` at decision points with full packaged context
- `approvals` table and API: list pending, get context, decide, clarify
- Sensitive-tool flag enforced in the registry
- Minimal review page: queue, context, decision buttons, clarification chat
**Dependencies.** Phase 3 (reviewer and tracing feed the approval context).
**Definition of done.** A sensitive tool call pauses indefinitely, survives a worker restart, and each of the four decisions (approve, modify, reject, take over) resumes the run correctly.

## Phase 5: Long-term memory
**Goal.** The system reuses what worked before, per user, and can forget on request.
**Tasks.**
- Post-task extraction (request, approach, tools used, outcome, facts, preferences) into Chroma plus Postgres metadata
- Retrieval at planning time, injected into the planning prompt with source ids
- Importance scoring (access count, recency)
- Memory dashboard and per-user delete endpoint
- Trace spans record which memories were retrieved and used
**Dependencies.** Phase 1 (planning node to inject into), Phase 3 (tracing to record retrieval).
**Definition of done.** On a repeated task family, a plan produced with memory available is measurably different from one without it (validated with numbers in Phase 6). Deleting a user's memories removes both the Chroma collection and the Postgres rows, verified by test.

## Phase 6: Evaluation harness
**Goal.** Every claim about the system becomes a reproducible number. Highest-value phase for the resume.
**Tasks.**
- Lock a 100-task set across 4 categories, including a repeated-family subset, before any tuning
- Deterministic graders plus an LLM judge validated against 20 hand-labeled samples
- Single-agent baseline using the same tools and model
- Ablations: no reviewer, no memory, no parallelism, no plan approval
- 3 repeats per configuration; report mean and spread for success rate, cost, latency, escalation rate
- Model-routing experiment (cheap model for easy subtasks, strong model for planning and review)
- `evals/report.py` generates the results table from one command
- Failure analysis on the 10 worst cases, fix the top recurring cause
**Dependencies.** Phases 1 to 5 all feed the eval (planning, tools, reviewer, HITL, memory).
**Definition of done.** The results table is reproducible with one command and includes variance. No number is used anywhere (README, resume) that is not in this table.

## Phase 7: Security and replay
**Goal.** The tool layer resists adversarial input, and any run can be inspected and re-run with changes.
**Tasks.**
- 25+ case injection suite: malicious tool content, instruction-override attempts, exfiltration, cross-user leakage
- Defenses: data/instruction separation for tool output, least privilege, sensitive-action approval; report pass rate before and after defenses
- Replay: load a checkpoint, edit an input, re-execute, diff against the original run
- MCP: expose Orchestra's tools as an MCP server; optionally consume one external MCP server
**Dependencies.** Phase 2 (tools to attack), Phase 4 (approval gate as a defense), Phase 6 (eval infra reused for the injection suite runner).
**Definition of done.** Injection suite pass rate is reported for both an undefended and a defended configuration. A replayed run with one edited input shows a clear divergence diff from the original.

## Phase 8: Explorer UI, polish, and ship
**Goal.** A stranger can clone the repo and see the whole system work in one command.
**Tasks.**
- Trace explorer (Next.js): agent tree, status colors, node detail with prompt/response/cost/latency
- Cost dashboard: per task type, per agent, escalation trend
- Scripted demo: parallel specialists, a reviewer rejection, a memory-informed plan, a human approval, the trace shown
- E2E tests over the demo path in CI (FakeProvider)
- README: pitch, architecture diagram, results table, quickstart, honest limitations
- 4 to 5 minute demo video
- Clean-machine verification of `docker compose up` plus the demo script
- Optional: single-VM deployment with a public explorer link
**Dependencies.** All prior phases; this phase packages and presents them.
**Definition of done.** A clean clone plus one command reproduces the demo and the eval results table. The README and video match what the running system actually does.

## Cut order if behind schedule
1. Memory consolidation and expiry (inside Phase 5)
2. Public VM deployment (inside Phase 8)
3. Cost dashboard aggregates, keep per-task cost (inside Phase 8)
4. Model-routing experiment (inside Phase 6)
5. External MCP consumer, keep the MCP server (inside Phase 7)

Never cut: durable resume (Phase 1), the reviewer loop (Phase 3), the four HITL levels (Phase 4), the eval harness (Phase 6), the injection suite (Phase 7).
