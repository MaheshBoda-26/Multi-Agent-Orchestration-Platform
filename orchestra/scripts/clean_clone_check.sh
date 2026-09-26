#!/usr/bin/env bash
# Clean-machine verification (Task 49): proves a stranger can clone, run one
# command, and see the system work. Clones the repo into a temp dir, syncs
# deps, boots compose services, runs the demo and an eval dry-run, then tears
# everything down. Prints a PASS/FAIL checklist and exits nonzero on any FAIL.
#
# Usage: bash scripts/clean_clone_check.sh [REPO_DIR]
#   REPO_DIR defaults to the parent of this script's orchestra/ dir.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRA_SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$ORCHESTRA_SRC/.." && pwd)"
REPO_DIR="${1:-$REPO_ROOT}"

COMPOSE_PROJECT="orchestra-clean-$$"
CLONE_DIR="$(mktemp -d /tmp/orchestra-clean-clone.XXXXXX)"
API_URL="http://localhost:8000"
declare -a RESULTS=()
FAILED=0

pass() { RESULTS+=("PASS  $1"); echo "PASS  $1"; }
fail() { RESULTS+=("FAIL  $1  -- $2"); echo "FAIL  $1  -- $2"; FAILED=1; }

step() { echo; echo "== $1"; }

cleanup() {
  step "teardown"
  ( cd "$CLONE_DIR/orchestra" 2>/dev/null || cd "$ORCHESTRA_SRC";
    docker compose -p "$COMPOSE_PROJECT" down --remove-orphans -v >/dev/null 2>&1 ) || true
  rm -rf "$CLONE_DIR"
}
trap cleanup EXIT

step "1. clone to a clean temp dir ($CLONE_DIR)"
if git clone --quiet "$REPO_DIR" "$CLONE_DIR/repo" 2>/dev/null \
   || cp -R "$REPO_DIR" "$CLONE_DIR/repo"; then
  pass "clone"
else
  fail "clone" "could not clone $REPO_DIR"; print_results; exit 1
fi

step "2. uv sync (fresh .venv from uv.lock)"
if ( cd "$CLONE_DIR/repo/orchestra" && uv sync --dev >/dev/null 2>&1 ); then
  pass "uv sync"
else
  fail "uv sync" "dependency resolution failed"; print_results; exit 1
fi

step "3. docker compose up postgres redis api worker"
if ( cd "$CLONE_DIR/repo/orchestra" \
     && docker compose -p "$COMPOSE_PROJECT" up -d --build postgres redis api worker \
        >/dev/null 2>&1 ); then
  pass "compose up"
else
  fail "compose up" "build or boot failed (check Dockerfile / compose)"; print_results; exit 1
fi

step "4. wait for API health on :8000"
HEALTHY=0
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null "$API_URL/tasks?limit=1"; then HEALTHY=1; break; fi
  sleep 2
done
if [ "$HEALTHY" = "1" ]; then pass "api healthy"; else
  fail "api healthy" "API never answered on $API_URL (logs: docker compose logs api)"
  print_results; exit 1
fi

step "5. run the demo (scripts/demo.py)"
if ( cd "$CLONE_DIR/repo/orchestra" \
     && uv run python scripts/demo.py --base-url "$API_URL" >/dev/null 2>&1 ); then
  pass "demo end to end"
else
  fail "demo end to end" "scripts/demo.py failed against the clean deployment"
fi

step "6. eval dry-run (fake provider, 1 repeat)"
if ( cd "$CLONE_DIR/repo/orchestra" \
     && uv run python -m evals.run --repeats 1 >/dev/null 2>&1 ); then
  pass "eval dry-run"
else
  fail "eval dry-run" "python -m evals.run --repeats 1 failed"
fi

step "7. check pages render"
for path in "/explorer" "/dashboard" "/approvals/ui" "/memory/ui"; do
  if curl -sf -o /dev/null "$API_URL$path"; then
    pass "page $path"
  else
    fail "page $path" "non-200 from $API_URL$path"
  fi
done

print_results() {
  echo; echo "================ clean-clone checklist ================"
  for line in "${RESULTS[@]}"; do echo "$line"; done
  echo "======================================================="
  if [ "$FAILED" = "0" ]; then echo "RESULT: PASS"; else echo "RESULT: FAIL"; fi
}
trap - EXIT
cleanup
print_results
exit "$FAILED"
