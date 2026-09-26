# Orchestra — Phase 9 build brief (Live & Shipped)

You are continuing a multi-agent orchestration platform called Orchestra. The
full roadmap (Phases 0–8) is IMPLEMENTED and COMMITTED on `main`: durable
LangGraph runs (AsyncPostgresSaver checkpoints, Celery redelivery), parallel
specialists with a bounded tool loop, reviewer loop, durable HITL
(decide/clarify + pause-survives-restart), pgvector long-term memory, a
100-task eval harness with 6 configs and a cache, a 25-case prompt-injection
suite with data-framing defenses, checkpoint replay with divergence diff, an
MCP tool server, a trace explorer + cost dashboard, a demo script, an e2e
test, CI, and a README.

Working directory: `orchestra/` (repo root is one level up). Python 3.14 + uv.
pytest.ini: asyncio_mode=strict (async tests need `@pytest.mark.asyncio`),
markers `live` (needs OPENROUTER_API_KEY) and `integration` (needs compose
postgres+redis up; DB tests use the `postgres_pool` fixture, auto-skip).
Bare imports + `python -m pkg.mod` from `orchestra/` is the convention.

## Verify commands (run from orchestra/)
- `uv run pytest tests -m "not integration" -m "not live"` (currently 140 pass)
- `uv run pytest tests/integration tests/e2e -m integration` (currently 10 pass; needs compose services)
- `uv run mypy` and `uv run ruff check .` (both clean today)
- Anti-pattern greps must stay clean: chroma, OTLPSpanExporter, operator.add,
  task_costs, and no hard-coded model names outside `config/routing.yaml`.

## Locked architecture (do not change)
OpenRouter via httpx behind `llm/provider.py`; pgvector in Postgres (not
ChromaDB); FastAPI-served static UI (no build step); models ONLY in
`config/routing.yaml` (roles: supervisor/reviewer=claude-3.5-sonnet,
specialist/extractor/judge=gpt-4o-mini, cheap=llama-3.3-70b, embedding=
text-embedding-3-small; costs section prices runs). No secrets in repo.
Commit style: `feat:/fix:/test:/docs:/chore:` + footer
`🤖 Generated with Codebuff` / `Co-Authored-By: Codebuff <noreply@codebuff.com>`.

## Your tasks, in order

### 1. Eval cache + budget guard (pre-spend safety)
`evals/cache.py` already has `LLMCache`/`CachedProvider`; migration 007 has the
`llm_cache` table. In `evals/run.py`: when a `pool` is passed, wrap the
provider in `CachedProvider` backed by the DB table (prompt-hash → response,
survives restarts). Add a `--budget-max USD` flag: before each task, sum
estimated cost (prompt+completion tokens priced from routing.yaml costs) for
the current config run; abort that config with a clear error if the estimate
exceeds the cap (default 40.0). Unit tests: cache roundtrip through the real
table (postgres_pool fixture) and budget-abort behavior (fake provider).
Commit: `feat: cache live eval calls and guard the matrix with a budget cap`

### 2. Hand-labeled judge samples (Task 33)
Create `evals/judge_samples.jsonl`: 20 lines, each
`{"id": "...", "instruction": "...", "response": "...", "human_pass": true|false}`.
Draw instructions from the four locked families (research / data_analysis /
writing / coding); label ~10 true / ~10 false, with the false ones failing for
real reasons (missing required content, too short, wrong facts, no sources).
Create `evals/validate_judge.py --provider openrouter`: runs `judge_agreement`
from `evals/graders.py` over the file, writes `evals/output/judge_agreement.json`,
prints the agreement %. Unit test the loader + report shape (fake provider);
live test `tests/live/test_judge_agreement.py` (marked `live`, skips without
key) asserts agreement >= 0.8.
Commit: `test: validate the llm judge against 20 hand-labeled samples`

### 3. Clean-machine verification (Task 49)
Write `scripts/clean_clone_check.sh` (bash, set -euo pipefail):
clone the repo to a `mktemp -d` dir, `uv sync`, `docker compose up -d
postgres redis api worker`, wait for api health on :8000, run
`uv run python scripts/demo.py --base-url http://localhost:8000`, run the eval
dry-run (`uv run python -m evals.run --repeats 1`), then compose down. Print a
PASS/FAIL checklist per step. Add a `.dockerignore` (workspaces/, .venv/,
evals/output/, security/output/, __pycache__) so the compose build context
stays small. RUN the script and fix whatever breaks (Dockerfile, compose
healthchecks, README quickstart drift). Record gotchas in tasks/lessons.md.
Commit: `docs: verify the clean-clone quickstart` (plus any fix commits)

### 4. Live numbers (requires OPENROUTER_API_KEY in env — skip cleanly if absent)
Run in this order, regenerating artifacts after each:
a. `uv run python scripts/live_plan_check.py --provider openrouter --limit 20`
   → evals/output/plan_validity.json; gate >= 0.95
   (`tests/live/test_live_plan_validity.py` must pass).
b. `uv run python -m evals.run --provider openrouter` (6 configs x 3 repeats,
   cache on, budget cap 40) → regenerate `evals/results.md` via
   `uv run python -m evals.report`. Add a "Routing" section to the report
   comparing full vs cheap-only pass rate AND cost delta (Task 37).
c. `evals/failures.md` (Task 38): list the 10 worst tasks by score, name the
   top recurrent failure cause, fix it (tighten the supervisor/reviewer prompt
   or schema validation FIRST, per rules.md — never add agents), re-run the
   affected configs only.
d. `uv run python -m security.run_injection --provider openrouter` then
   `uv run python -m security.report` → live before/after in
   security/results.md.
e. Update README's "What is verified" section so every number comes from the
   regenerated artifacts; keep the fake-baseline tables labeled as baselines.
Commits: `feat: record live eval numbers and address the top failure cause`,
`docs: publish live injection and plan-validity numbers`.

### 5. docs/architecture.md + docs/api.md (Task 48 completion)
architecture.md: system diagram, the four flows (submit→run, HITL pause→
resume, crash→checkpoint resume, replay), stack table, security layers
(jail/allowlist/sandbox/approvals/sanitizer), durability guarantees with the
proving tests named. api.md: every endpoint with method, path, request/
response JSON examples (seed from the README table + api/server.py).
Commit: `docs: write the API and architecture docs`

### 6. Final verification (Task 51)
Run ALL gates. Re-grep the anti-patterns. Check every README number traces to
a committed artifact. Append a Phase 9 entry to docs/decisions.md. Optional:
tag `v0.1.0`. Commit: `chore: final verification notes`.

## Rules
- Test-first where practical; one commit per task; run the verify commands
  before every commit.
- Never put OPENROUTER_API_KEY in any file. Live tests skip without it.
- If the judge agreement < 0.8: fix the judge prompt/model (routing.yaml judge
  role) and re-validate — max 2 attempts, then report.
- If the budget cap trips: stop, report spent vs estimate, ask before raising.
- If a live number is bad (e.g. plan validity < 0.95): that is a FINDING.
  Record it in failures.md, fix the top cause, re-run — do not lower gates.
