# TRD: Orchestra

## Open questions (carried from PRD.md, they change the choices below)
1. **Web search provider.** Assumed Tavily. If you cannot create an account, swap the `web_search` tool implementation; nothing else changes.
2. **Public deployment.** Assumed local Docker Compose only. If you want a public explorer link, the production row in the environments table becomes a single VM.
3. **UI framework.** Assumed Next.js for the trace explorer and review page. Tell me if you would rather use Streamlit; the API contract does not change.

## 1. Tech stack
| Layer | Choice | Reason |
|---|---|---|
| Language (backend) | Python 3.11 | Ecosystem for LangGraph, OpenAI and Anthropic SDKs |
| Web framework | FastAPI | Typed request/response models, SSE support |
| Orchestration | LangGraph with `PostgresSaver` checkpointer | Durable state machine, `interrupt()` for human pauses |
| Async execution | Celery with Redis as broker | Workers survive API restarts, spec requirement |
| Primary database | PostgreSQL 16 | Tasks, plans, tool calls, spans, approvals, checkpoints |
| Vector store | ChromaDB (server mode) | Long-term semantic memory |
| Cache / pub-sub | Redis 7 | Celery broker, live-update pub/sub. Not used for working memory |
| Observability | OpenTelemetry SDK with a custom Postgres span exporter | Explorer queries spans directly |
| Frontend | Next.js (App Router), TypeScript | Trace explorer and review page |
| Sandbox | Docker containers started per code-execution call | No network, resource limits |
| Package managers | `uv` (Python), `pnpm` (web) | Lockfiles, fast CI |
| Hosting | Local Docker Compose. Optional single VM with the same Compose file | Fits the 4 vCPU / 8 GB constraint |

## 2. Libraries and packages
**Version policy.** Versions below are floors. On Day 0 the exact versions resolve into `uv.lock` and `pnpm-lock.yaml` and get recorded in `docs/decisions.md`. Verify against PyPI and npm at install time, because I cannot check current releases from here. Where I wrote "latest stable", pin whatever resolves on Day 0.

### Backend
| Package | Version | Purpose |
|---|---|---|
| fastapi | >=0.115 | HTTP API |
| uvicorn[standard] | latest stable | ASGI server |
| pydantic, pydantic-settings | >=2.9 | Schemas, plan validation, config |
| langgraph | >=1.0 | Agent graph |
| langgraph-checkpoint-postgres | matching langgraph major | Durable checkpoints |
| psycopg[binary,pool] | >=3.2 | Postgres driver (also used by the checkpointer) |
| sqlalchemy | >=2.0 | Data access for app tables |
| alembic | latest stable | Migrations |
| celery[redis] | >=5.4 | Task queue |
| redis (redis-py) | >=5 | Pub/sub, rate-limit counters |
| chromadb | >=1.0 | Long-term memory |
| openai | latest stable | Chat, structured output, embeddings |
| anthropic | latest stable | Chat, tool use |
| tavily-python | latest stable | `web_search` tool |
| mcp (Python SDK) | latest stable | Expose Orchestra tools as an MCP server |
| httpx | latest stable | HTTP tool, outbound calls |
| docker (Docker SDK for Python) | latest stable | Sandbox lifecycle |
| opentelemetry-api, opentelemetry-sdk | >=1.27 | Tracing |
| tenacity | latest stable | Retry with backoff on provider errors |
| structlog | latest stable | Structured JSON logs |
| networkx | latest stable | DAG cycle and topological-order checks in plan validation |

### Backend dev and test
| Package | Purpose |
|---|---|
| pytest, pytest-asyncio, pytest-cov | Test runner, async tests, coverage |
| hypothesis | Property tests for plan validation |
| respx | Mock outbound HTTP |
| ruff | Lint and format |
| mypy | Static types (strict on `graph/`, `tools/`, `llm/`) |
| pre-commit | Local gate |

### Frontend
| Package | Purpose |
|---|---|
| next, react, typescript | App |
| @xyflow/react | Agent graph rendering in the explorer |
| @tanstack/react-query | Data fetching and polling |
| zod | Runtime validation of API responses |
| tailwindcss | Styling (tokens come from `design.md`) |
| playwright | UI e2e tests |

Exact UI kit (for example shadcn/ui) is decided after `design.md`.

## 3. APIs and third-party integrations
### External
| Service | Used for | Failure behavior |
|---|---|---|
| OpenAI API | Planning, specialists, reviewer, embeddings | Retry with backoff, then fall back to the alternate provider in `routing.yaml` |
| Anthropic API | Planning, specialists, reviewer | Same |
| Tavily | `web_search` tool | Tool returns a typed error, specialist may retry with a different query, then the subtask escalates |
| Mock approval webhook (local container) | Stand-in for sensitive outbound actions | None needed, it is local |

### Internal REST API (all under `/v1`)
| Method and path | Role | Purpose |
|---|---|---|
| `POST /tasks` | user | Submit task, returns `task_id` |
| `GET /tasks/{id}` | user | Status, plan, result, cost |
| `GET /tasks/{id}/events` | user | SSE stream of status and step events |
| `POST /tasks/{id}/cancel` | user | Cancel a run |
| `GET /tasks/{id}/trace` | user | Span tree with attributes |
| `POST /tasks/{id}/replay` | admin | Replay from a checkpoint, with optional input edits |
| `GET /approvals?status=pending` | reviewer | Queue |
| `GET /approvals/{id}` | reviewer | Full decision context |
| `POST /approvals/{id}/decision` | reviewer | approve, modify, reject, take_over |
| `POST /approvals/{id}/clarify` | reviewer | Ask the agent a question about the pending decision |
| `GET /users/{id}/memories` | user (self), admin | Memory dashboard |
| `DELETE /users/{id}/memories` | user (self), admin | Delete all of a user's memories |
| `GET /stats/cost` | admin | Cost and escalation aggregates |
| `POST /evals/runs` | admin | Start an eval run |

### MCP
- Orchestra exposes the `web_search`, `file_read` and `db_query` tools through an MCP server.
- Optional (N5): the registry can register tools from one external MCP server, under the same permission model.

## 4. Data models and schema
### Core Pydantic models (`graph/state.py`)
| Model | Fields |
|---|---|
| `Subtask` | `key`, `description`, `specialist` (enum), `inputs`, `depends_on` (list of keys), `expected_format`, `complexity` (low/med/high), `sensitive` (bool) |
| `Plan` | `version`, `subtasks`, `confidence` (0 to 1), `rationale`, `memory_ids_used` |
| `GraphState` | `task_id`, `user_id`, `request`, `plan`, `results` (by subtask key), `attempts` (by subtask key), `review_scores`, `errors`, `pending_approval_id`, `cost_usd` |

Validation rules: no cycles, every `depends_on` key exists, every specialist is in the whitelist, at most 12 subtasks, every subtask has an expected format.

### Tables (PostgreSQL)
| Table | Key columns |
|---|---|
| `users` | `id`, `name`, `role` (user/reviewer/admin), `api_key_hash`, `created_at` |
| `tasks` | `id`, `user_id`, `request`, `status` (queued/planning/running/awaiting_human/completed/failed/cancelled), `thread_id`, `result` (jsonb), `tokens_in`, `tokens_out`, `cost_usd`, `created_at`, `started_at`, `finished_at` |
| `plans` | `id`, `task_id`, `version`, `subtasks` (jsonb), `confidence`, `superseded_by` |
| `subtasks` | `id`, `task_id`, `plan_id`, `key`, `specialist`, `depends_on` (text[]), `status`, `attempts`, `output` (jsonb), `review_score` |
| `tool_calls` | `id`, `task_id`, `subtask_id`, `tool`, `args` (jsonb), `result` (jsonb), `status`, `latency_ms`, `error`, `created_at` |
| `llm_calls` | `id`, `span_id`, `provider`, `model`, `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms`, `prompt` (jsonb), `response` (jsonb) |
| `spans` | `trace_id`, `span_id`, `parent_span_id`, `task_id`, `name`, `agent`, `kind`, `status`, `start_ts`, `end_ts`, `attributes` (jsonb) |
| `approvals` | `id`, `task_id`, `subtask_id`, `level` (notify/approve_action/approve_plan/take_over), `trigger`, `context` (jsonb), `proposed_action` (jsonb), `status` (pending/approved/modified/rejected/taken_over), `decision` (jsonb), `reviewer_id`, `created_at`, `decided_at` |
| `memories` | `id`, `user_id`, `kind` (task_summary/approach/fact/preference), `content`, `chroma_id`, `importance`, `access_count`, `last_accessed_at`, `source_task_id`, `created_at` |
| `eval_runs` | `id`, `config` (jsonb), `git_sha`, `started_at`, `finished_at` |
| `eval_results` | `id`, `run_id`, `task_key`, `repeat`, `success`, `score`, `cost_usd`, `latency_ms`, `escalated`, `task_id` |

LangGraph's checkpoint tables are created and owned by `PostgresSaver`. App code never writes to them.

### ChromaDB
One collection per user, named `mem_{user_id}`. Each document carries `kind`, `memory_id`, `created_at`. Deleting a user's memories drops the collection and the matching `memories` rows in one transaction-plus-compensation routine, tested by `test_delete_user_removes_all_memories`.

### Retention
Full prompts and responses in `llm_calls` are kept 30 days in dev. Aggregates and spans without payloads are kept indefinitely.

## 5. Authentication and authorization
- **Authentication:** per-user API key in the `X-API-Key` header. Keys are 32 random bytes, shown once at creation, stored as SHA-256 hashes.
- **Roles:** `user` submits and reads their own tasks and memories. `reviewer` reads and decides approvals. `admin` runs evals, replays, and reads aggregates. Roles are checked in one FastAPI dependency, not per handler.
- **Data isolation:** every repository query takes `user_id` and filters by it. There is no query method that reads tasks without a user or admin context. Chroma isolation comes from one collection per user.
- **Web UI:** Next.js route handlers hold the API key in an httpOnly, same-site cookie and proxy calls. The browser never sees the key after login.
- **Tool permissions:** the registry maps each specialist to the tools it may call. Sensitive tools (file delete, outbound webhook) additionally require an approval record with status `approved` for that exact call.
- **Reviewer accountability:** every approval decision stores `reviewer_id` and the exact payload the reviewer saw.

## 6. Performance requirements
| Area | Target |
|---|---|
| `POST /tasks` p95 (enqueue only, no LLM in the request path) | under 200 ms |
| Task start latency (enqueue to first planning span) | under 2 s at idle |
| Concurrent tasks | 20 running at once on 4 vCPU / 8 GB, worker concurrency 8, LLM waits dominate |
| Crash recovery | Restarted worker resumes an interrupted run within 10 s |
| Approval pause | Unlimited duration, zero CPU while paused |
| Trace explorer load | Trace with 500 spans renders in under 2 s |
| `GET /tasks/{id}/trace` | p95 under 500 ms for 500 spans |
| SSE delivery | Event visible in the UI within 1 s of being written |
| Sandbox | Cold start under 3 s, hard timeout 30 s, 256 MB memory, 0.5 CPU |
| Memory retrieval | Under 300 ms for 10,000 memories per user |
| Cost guard | Each task has a max token and USD budget, the run stops and escalates when it is exceeded |

## 7. Security requirements
| Threat | Requirement |
|---|---|
| Prompt injection via tool output (web pages, files) | Tool output is passed to models inside a delimited data block, flagged when it contains instruction-like patterns, never allowed to change permissions, tested by the injection suite |
| Tool abuse | Least-privilege per specialist, rate limits per tool, sensitive tools gated by approval |
| Code execution escape | Docker container: no network, non-root user, read-only root filesystem, writable `/work` only, CPU, memory and time limits, container destroyed after each call |
| File tool traversal | Paths resolved against a per-task workspace, anything outside is rejected |
| SSRF via `http_call` | Domain allowlist, block private and link-local address ranges, no redirects to non-allowlisted hosts |
| SQL tool misuse | Read-only DB role, statement allowlist (SELECT only), row and time limits |
| Secret leakage | Secrets only in environment variables, never in prompts, traces or logs. Redaction filter on `llm_calls` for strings matching key patterns |
| Cross-user leakage | Isolation as in section 5, with a test that user B cannot retrieve user A's memories or tasks |
| Data deletion | `DELETE /users/{id}/memories` removes Chroma and Postgres rows, verified by test |
| Supply chain | Lockfiles committed, `pip-audit` and `pnpm audit` run in CI |
| Runaway cost | Per-task and per-day USD caps, enforced in `llm/provider.py` |

## 8. Deployment and environments
| Environment | Where | Provider | Data |
|---|---|---|---|
| Dev | Developer machine, `docker compose up` | Real models with cache-by-hash, or FakeProvider | Local volumes |
| CI (staging equivalent) | GitHub Actions, ephemeral Compose | FakeProvider only, no live keys | Ephemeral |
| Production (optional) | One VM (4 vCPU, 8 GB) running the same Compose file with a reverse proxy and TLS | Real models | Persistent volumes, nightly `pg_dump` |

Compose services: `api`, `worker`, `postgres`, `redis`, `chroma`, `web`, `mock-webhook`. The sandbox containers are started by the worker through the Docker socket, so the worker gets a restricted socket proxy in production instead of the raw socket.

Configuration: `.env` for secrets, `routing.yaml` for model routing, `escalation.yaml` for triggers and thresholds. `.env.example` lists every variable. The app fails at startup if a required variable is missing.

Migrations run automatically at API startup in dev and manually in production. The eval database is separate from the app database.

## 9. Testing approach
| Level | Scope | Tooling | Runs |
|---|---|---|---|
| Unit | Plan validation, permission checks, cost accounting, memory scoring, escalation mapping | pytest, hypothesis | Every commit |
| Integration | Graph with FakeProvider against real Postgres, Redis, Chroma: kill-worker resume, reviewer loop, approval pause and resume, tool logging, memory isolation | pytest with Compose services | Every PR |
| End to end | Demo scenario through the API and the web UI (submit, approve, view trace) | pytest, Playwright | Every PR (FakeProvider) |
| Live-model | Plan validity on 20 tasks, reviewer catch rate on rigged outputs | pytest marker `live` | Manual, before each phase exit |
| Security | 25+ injection, permission and isolation cases | `security/injection_suite` | Every PR (FakeProvider scripted attacks), manual with real models |
| Evals | 100 tasks, baseline, ablations, 3 repeats | `evals/run.py` | Manual, results committed as a report |

Rules: FakeProvider makes CI deterministic. A bug fix starts with a failing test. Coverage floor is 80% on `graph/`, `tools/`, `memory/`, `llm/`. The eval task set and graders are locked at the start of Phase 6, before any tuning, and change only through a documented decision.
