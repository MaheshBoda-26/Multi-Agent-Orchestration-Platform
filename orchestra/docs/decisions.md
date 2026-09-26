# Decisions

Append-only log. One entry per decision, with the reason. See `rules.md`
section 3 for which changes require an entry here.

## 2026-09-26 — Audit fixes (state, scheduling, persistence, security, tooling)

**Context.** An audit of the running code found the walking skeleton could not
complete a single run (`operator.add` on a dict state channel raised
`TypeError`), dependent subtasks were never scheduled, the API kept task state
in memory, tool output could escape the workspace jail or be pointed at
internal addresses, the span exporter did not implement OpenTelemetry's
synchronous interface, and lint/type/CI tooling was configured but empty.

**Decisions**

- **State channels use an explicit merge reducer.** `merge_dicts` replaces
  `operator.add` for the `results`, `attempts` and `review_feedback` channels.
  Dicts cannot be added, and parallel `Send` branches must merge rather than
  overwrite.
- **Scheduling moved into a single `dispatch` node.** Nodes fan in to
  `dispatch`, which schedules one batch of ready subtasks per super-step. This
  prevents two parallel branches from scheduling the same subtask and makes
  the retry path terminate: a retry is only scheduled while attempts are below
  `MAX_SUBTASK_ATTEMPTS = 2`, otherwise the subtask is marked `escalate` and
  the run still synthesizes a result.
- **Review runs per batch, not per branch.** `review` receives the merged state
  after all parallel executes of a step finish, so it reviews each unreviewed
  result against its own subtask instead of guessing from dict ordering.
- **Plan validation is a first-class module** (`graph/validate.py`): ids unique,
  dependencies exist, no cycles (Kahn), specialist whitelist, description
  present, at most 12 subtasks. An invalid plan triggers exactly one
  regeneration, then the run fails loudly instead of executing garbage.
- **HITL is gated behind `hitl_enabled`.** `interrupt()` needs a checkpointer to
  pause and resume, so nodes only raise for a human when the flag is set. The
  durability phase flips it on; the flag prevents a broken "pause" today.
- **Task state lives in Postgres.** `migrations/` holds plain SQL migrations
  with a small runner (Alembic is not in the dependency set yet), and
  `api/repository.py` owns task rows. The API no longer keeps `active_tasks` in
  memory; SSE streams status changes by reading those rows.
- **Provider selection is explicit.** `llm/factory.py` reads `LLM_PROVIDER`
  (default `fake`). Selecting an unimplemented provider fails at call time
  rather than silently faking a run.
- **Workspace jail uses `realpath` + `commonpath`.** A sibling directory that
  merely shares a name prefix, and symlinks that point outside the workspace,
  are rejected.
- **`http_get` validates every hop.** Scheme allowlist, host allowlist, and a
  DNS check that rejects private, loopback, link-local and reserved addresses,
  with redirects followed manually for at most 3 hops.
- **Span exporter is synchronous with its own event loop.** OpenTelemetry calls
  `SpanExporter.export` synchronously, so the asyncpg writes run on a dedicated
  thread loop. Trace and span ids are written as hex strings and timestamps as
  timezone-aware UTC.
- **Timestamps are timezone-aware everywhere.** `datetime.utcnow()` was
  replaced with `datetime.now(timezone.utc)`; asyncpg rejects naive datetimes
  on `TIMESTAMPTZ` columns.
- **Tooling is real.** `ruff.toml` enables error-class rules (E4/E7/E9/F/B) and
  defers pure style families to a later pass; `mypy.ini` checks the app tree
  with stricter settings on `graph/`, `tools/` and `llm/`; pre-commit and
  GitHub Actions run lint, types and tests.

**Deviations recorded**

- **Python 3.14, not 3.11.** The environment and `.python-version` are 3.14;
  `pyproject.toml` requires >= 3.14. PEP 649 lazy annotations are in effect.
- **Postgres 16 image** in compose (TRD said 15 originally, then 16).
- **Chroma publishes host port 8001.** It previously collided with the API on
  8000; inside the compose network it still listens on 8000.
- **The Celery worker service is removed** until `worker/` and the `celery`
  dependency exist. The old service pointed at a module that did not exist and
  crashed the stack on startup.
- **The code-execution tool is still the in-process simulation.** It is not a
  security boundary; the Docker sandbox remains required before any real model
  reaches it.

## 2026-09-26 — Durability phase entry

**Context.** The next build milestone is the Phase 1 exit (durable runs), per
`files/phases.md`. It needs a checkpointer, a real worker and run analytics.

**Decisions**

- **Checkpointer driver is psycopg3, not asyncpg.** `AsyncPostgresSaver` takes a
  `psycopg_pool.AsyncConnectionPool`; the app's asyncpg pool cannot be reused
  for it. `graph/checkpointer.py` owns a small psycopg pool alongside the
  asyncpg pool.
- **Celery worker restored to compose.** `worker/celery_app.py` + `worker/tasks.py`
  now exist, with `task_acks_late` and `worker_prefetch_multiplier=1`, so a
  killed worker's job is redelivered and resumed from the LangGraph checkpoint.
- **Postgres image is `pgvector/pgvector:pg16`.** Adopted now (data is
  disposable) because the memory phase (005) needs the `vector` extension; it is
  the same Postgres otherwise.
- **ChromaDB service removed.** Superseded by the pgvector decision; the memory
  module is rewritten against Postgres in the memory phase.

## 2026-09-26 — Worker execution notes (durability test findings)

- **Celery uses the `threads` pool on Python 3.14.** The default prefork pool
  crashes in `fast_trace_task` with `ValueError: not enough values to unpack`
  (billiard is not 3.14-ready). Compose runs
  `--pool=threads --concurrency=4`; the kill/resume test uses `--pool=solo` for
  deterministic crashes. The graph work is async I/O, so threads are a good fit.
- **Every worker invoke passes `durability="sync"`.** LangGraph 1.x defaults to
  asynchronous checkpoint writes, and a SIGKILL loses them: an experiment showed
  one surviving checkpoint row with the default versus five with `sync`. Crash
  recovery is the phase requirement, so synchronous durability is non-negotiable
  in the worker.
- **`set_task_status` casts `$2`.** asyncpg inferred conflicting types for a
  parameter used both as the assigned status column and in a comparison;
  `$2::varchar` / `$2::text` fixes it.

## 2026-09-26 — Observability phase

- **Spans are owned by migration 004.** The exporter no longer creates the
  table at runtime; schema changes go through the migration runner like every
  other table.
- **The span exporter owns its asyncpg pool.** asyncpg pools are bound to the
  event loop that created them; borrowing the app's pool from the exporter's
  thread loop raised `InterfaceError: another operation is in progress` and
  silently dropped every span. `PostgresSpanExporter(dsn)` now creates its own
  pool inside its loop; the injectable pool argument exists only for tests.
- **One cost source of truth.** `observability/cost.py` and its `task_costs`
  table are deleted; per-run totals live in `run_metadata` and per-call detail
  lives in `spans`. `RecordingLLMProvider` collects usage, and providers expose
  `last_usage` so structured calls (which may include a repair retry) can be
  priced.
- **The OTLP tracing manager is deleted.** Decision D6 says the custom Postgres
  exporter is the only span sink; `observability/setup.py` configures it once
  per process from a DSN.
- **Trace and cost endpoints added:** `GET /tasks/{id}/trace` returns the span
  tree (every agent, tool and model call) and `GET /tasks/{id}/cost` returns the
  run rollup.
