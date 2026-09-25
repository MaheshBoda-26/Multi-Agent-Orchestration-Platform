# rules.md: Orchestra

## 1. What we use
- **Python 3.11**, type hints everywhere, `uv` for dependency management.
- **Pydantic v2** for every data boundary: API request/response, graph state, tool schemas, plan schema.
- **LangGraph** with the Postgres checkpointer as the only mechanism for run state and human pauses. `interrupt()` for all human-in-the-loop pauses, not a custom polling loop.
- **FastAPI** with dependency-injected auth and DB sessions. Routes stay thin; logic lives in `graph/`, `agents/`, `tools/`, `memory/`.
- **Celery + Redis** strictly as broker and pub/sub. Late acknowledgement on, so a killed worker's job is redelivered.
- **One provider interface** (`llm/provider.py`) for all model calls. Model names and roles live in `routing.yaml`, never hard-coded in agent code.
- **Structured output** (Pydantic schema passed to the model) for every plan, review score, and escalation decision. No parsing free-text into structure.
- **One tool registry** as the only path to the outside world (web, filesystem, code execution, DB, HTTP). No specialist calls a tool library directly.
- **OpenTelemetry spans** around every graph node, tool call, and LLM call. No `print`-based debugging in committed code; use `structlog`.
- **Alembic** for every schema change. No hand-edited tables.
- **Docker Compose** as the only supported way to run the full stack locally and in production.
- **Tests before implementation** for every item in `tasks/todo.md` that has a listed test.

## 2. What we avoid
- No custom polling or a hand-rolled approval queue table with manual state machines. LangGraph's checkpointer and `interrupt()` already do this; rebuilding it is wasted effort and a bug source.
- No Redis-backed working memory. Graph state in Postgres is the single source of truth for an in-flight task.
- No direct provider SDK calls from `agents/` or `graph/`. Everything routes through `llm/provider.py` so tests can swap in `FakeProvider` and costs are always recorded.
- No unstructured "ask the model and regex the answer" parsing. Use structured output.
- No specialist with unrestricted tool access. Every tool call is checked against `tools/permissions.py`.
- No raw Docker socket exposed to the worker in production; use a restricted socket proxy.
- No network access from the code-execution sandbox.
- No secrets in code, prompts, fixtures, or committed `.env` files. Only `.env.example` is committed.
- No new agent added to fix a flaky plan or a bad output. Fix the schema, the prompt, or the retry policy first.
- No feature added that is not on the `phases.md` list for the current or a past phase.
- No abstraction introduced before it has two concrete call sites.
- No global mutable state in the graph or the API process. State is either in `GraphState` (checkpointed) or in Postgres.
- No blocking LLM or tool calls inside the FastAPI request path. The API enqueues and reads; it never runs an agent step synchronously.
- No hard-coded model name in `agents/`, `graph/`, or `tools/`. Read it from `routing.yaml` through the provider.
- No skipping the injection suite or the kill-worker test before a phase is marked done.
- No committing a result to the README that `evals/run.py` cannot reproduce.
- No mixing UI state management approaches in `web/`; use React Query for server state, no ad hoc `useEffect` fetching.

## 3. Libraries
Full list with purpose is in `TRD.md` section 2. This is the approval list; anything not here needs a `docs/decisions.md` entry before use.

**Approved (backend):** fastapi, uvicorn, pydantic, pydantic-settings, langgraph, langgraph-checkpoint-postgres, psycopg, sqlalchemy, alembic, celery, redis, chromadb, openai, anthropic, tavily-python, mcp, httpx, docker (SDK), opentelemetry-api, opentelemetry-sdk, tenacity, structlog, networkx.

**Approved (backend dev/test):** pytest, pytest-asyncio, pytest-cov, hypothesis, respx, ruff, mypy, pre-commit.

**Approved (frontend):** next, react, typescript, @xyflow/react, @tanstack/react-query, zod, tailwindcss, playwright.

**Version pins:** exact versions are locked in `uv.lock` and `pnpm-lock.yaml` at Phase 0 and recorded in `docs/decisions.md`. `langgraph` and `langgraph-checkpoint-postgres` must stay on matching major versions. Bumping any pinned library is a decisions.md entry, not a drive-by edit.

**Not approved without a decisions.md entry:** any second web framework, any second ORM, any second queue system, any additional vector store, any UI state library beyond React Query, LangChain's higher-level agent abstractions (LangGraph is used directly; do not add the separate `langchain` agent executor on top).

## 4. Error handling rules
| Layer | Rule |
|---|---|
| Tool calls | Every call is wrapped; exceptions become a typed `ToolError` result, never raised into the graph. Logged to `tool_calls` with status and message |
| LLM calls | `tenacity` retry with backoff on transient errors (timeouts, 429, 5xx), max 3 attempts, then fall back to the alternate provider per `routing.yaml`, then fail the subtask |
| Plan validation | A structurally invalid plan triggers a regeneration with the validator's error appended to the prompt, up to 2 times, then escalates to human (Approve plan) |
| Specialist failure | First failure retries with a prompt variant or an alternate tool. Second failure marks the subtask `failed` and escalates per `escalation.yaml` |
| Reviewer rejection | Output returns to the specialist with the reviewer's specific feedback, capped at 2 retries, then escalates |
| Sandbox errors | Timeout, OOM, and non-zero exit are distinct `ToolError` reasons surfaced to the specialist and logged |
| Budget exceeded | The provider layer raises `BudgetExceeded`; the node catches it, marks the task `awaiting_human` with trigger `budget`, and pauses |
| Human-gate timeout | No automatic timeout; a pending approval waits indefinitely. A daily job flags approvals pending over 24 hours (log only, no auto-decision) |
| API layer | FastAPI exception handlers map domain errors to typed HTTP responses (`4xx` for validation and auth, `5xx` only for genuine faults) with a stable error `code` field. No raw stack traces returned to the client |
| Frontend | React Query error boundaries per view. A failed fetch shows a retry action, never a blank screen. SSE disconnect triggers automatic reconnect with backoff |
| Logging | `structlog` JSON logs with `task_id`, `subtask_id`, `trace_id` on every log line. No `print`. Secrets redacted by a logging processor before write |
| Uncaught exceptions in a node | Caught at the graph boundary, recorded as an `errors` entry in `GraphState`, span marked error, task escalated rather than left in an unknown state |

## 5. Boundaries of AI (what Cursor / Claude may do)
### Can change autonomously (with tests)
- Implementation inside `graph/nodes/`, `agents/specialists/`, `tools/builtin/`, `memory/`, `observability/`, `evals/`, `web/` components, as long as the change is scoped to one `tasks/todo.md` item and its own tests pass.
- Test files anywhere under `tests/`.
- Documentation inside `docs/decisions.md` (append-only entries) and code comments.

### Needs human review before merge
- Any change to `graph/state.py`, `graph/build.py`, or `graph/validate.py` (the state schema and graph shape are load-bearing).
- Any change to `tools/permissions.py`, `security/`, or anything affecting the sandbox's network or filesystem isolation.
- Any change to `llm/provider.py` retry, fallback, or budget logic.
- Any change to `escalation.yaml` mapping or approval levels.
- Any new external dependency not already on the approved list.
- Any change to `db/migrations/`.
- Any change to what data is written to or deleted from `memories`.

### Must not touch
- `.env`, real API keys, and any credentials, in any file.
- `docker-compose.yml` production overrides and deployment secrets.
- The `evals/tasks/` locked task set and `evals/graders/` once locked at the start of Phase 6, except through a `docs/decisions.md` entry describing why.
- Git history rewriting (no force-push to shared branches).
- Anything under `web/` that changes the color palette, typography, or spacing tokens without `design.md` being updated first.

### Process
- One phase or `todo.md` item per branch and PR. A diff that touches files outside the stated scope is rejected and re-scoped.
- Every PR description states which `todo.md` item it closes and which tests prove it.
- A correction from the user gets a new line in `tasks/lessons.md` before the next prompt to Cursor.
