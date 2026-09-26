# Eval failure analysis (Task 38)

Method: for each matrix run, sort tasks by score then latency (worst first),
cluster by `reason`, and name the **top recurrent cause**. A fix lands only
against that cause; gates are never lowered to make numbers look better.

## Status: dry-run (fake provider) — awaiting live runs

The current committed results come from the deterministic fake provider:
every config passes 100/100, so **there are no failures to analyze yet**. The
analysis below becomes meaningful with `--provider openrouter` runs.

## Known non-failures (dry-run artifacts, not model failures)

1. **Deterministic grader is deliberately shallow.** `evals/build_task_set.py`
   sets `min_chars=30` with empty `must_contain` for most tasks, so any
   coherent paragraph passes. This measures plumbing, not quality. The live
   failure analysis should first tighten `must_contain` for the ~25% of tasks
   where objective keywords exist, then re-run before drawing conclusions.
2. **Repeats are identical by construction** (same prompts, deterministic
   provider), so spread carries no information in dry runs.

## How to regenerate with live numbers

```bash
OPENROUTER_API_KEY=... uv run python -m evals.run --provider openrouter \
    --repeats 3 --budget-max 40
uv run python -m evals.report
# then fill this file: worst 10 tasks, top cause, the fix, re-run results
```
