# Lessons

Append-only. One entry per correction or root cause, dated.

## 2026-09-26 — Durability worker

- **Celery's prefork pool is broken on Python 3.14.** A task received by a
  prefork worker dies with `ValueError: not enough values to unpack (expected 3,
  got 0)` inside `billiard`/`fast_trace_task`. Use `--pool=threads` in compose
  and `--pool=solo` where a deterministic single process matters (tests).
- **LangGraph's default checkpoint durability is async.** With `durability` left
  at the default, a SIGKILL during a review call left only the very first
  checkpoint row; passing `durability="sync"` to `ainvoke` commits every
  super-step and the killed run resumes without repeating completed subtasks.
- **Test brokers need their own Redis DB.** Unacked messages from a killed
  worker linger and get redelivered (visibility timeout), so integration tests
  must run on an isolated broker DB (`/15`) and flush it before use.
- **asyncpg parameter types are inferred across the whole query.** A parameter
  used both as an assignment value and in a comparison (`$2` as status and in
  `$2 = 'running'`) raises `AmbiguousParameterError`; cast it (`$2::text`).
- **Worker readiness checks must match the log level.** `--loglevel=warning`
  filters out the `ready.` line, so a test that waits for it times out; log at
  `info` or detect readiness another way.
- **asyncpg pools are loop-bound.** An exporter on its own thread loop cannot
  borrow the app's pool: asyncpg raises `InterfaceError: another operation is
  in progress` and every span is lost. Give exporters a DSN and their own pool.
- **A mocked pool hides loop-affinity bugs.** The exporter's unit test passed
  while production dropped 100% of spans; the DB-backed trace test caught it.
  Keep one end-to-end assertion per exporter or writer.
- **CheckpointTuple state lives in checkpoint["channel_values"]** on the
  pinned langgraph version; `.state`/`.values` are plain strings (thread ids),
  not the graph state. Version-tolerant access goes through
  `graph.replay.load_checkpoint_values`.
- **KeyError is a LookupError.** In FastAPI except-clauses, the KeyError
  branch (422) must precede the LookupError branch (404) or unknown edit
  fields come back as 404.
- **The sandbox reaps background processes when each command exits.** For
  live-UI checks, prefer the page-asserting integration tests
  (`/explorer`, `/dashboard` render 200 + title) over long-lived dev servers.
- **Fake baselines must be symmetric.** A replay no-edit proof diverges unless
  the original run and the replay share one provider (script the worker via
  FAKE_PLAN_PATH or run the original in-process, as the replay test does).
