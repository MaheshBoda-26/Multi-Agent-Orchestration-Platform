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
