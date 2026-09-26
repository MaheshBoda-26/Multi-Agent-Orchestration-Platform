# PRODUCT.md — Orchestra

## What this is
Orchestra is a durable multi-agent orchestration platform with a web console.
A supervisor plans a task, parallel specialists execute it with real tools, a
reviewer gates every output, humans approve sensitive or uncertain steps, and
every run leaves a pgvector lesson. Everything is checkpointed to Postgres:
worker crashes resume, pauses survive restarts, and completed runs can be
replayed with edited inputs.

## Who it's for
Engineers and platform teams running agent workloads they must be able to
trust — the people who need to see what the agents did, what it cost, and
where a human vetoed or corrected them.

## Register
**Product / instrument.** Design serves the data. The aesthetic is a signal
console: dark instrument panel, one accent, mono labels, dense-but-calm.
The UI's job is to make the pipeline legible and the numbers trustworthy —
not to entertain. The landing page is the one brand-flavored surface.

## Surfaces
- `/` — landing: what it is, the loop, the numbers, dispatch a task inline.
- `/explorer` (+ per-task) — task list and full span traces.
- `/dashboard` — fleet cost/latency/escalation rollup.
- `/approvals/ui` — the durable human decision queue.
- `/memory/ui` — per-user long-term memory inspect/erase.

## Design system
"Signal Console" — see `web/static/console.css` (tokens) and `web/static/console.js`
(shared runtime). Key invariants: OKLCH color only, ember as the single accent,
Space Grotesk + JetBrains Mono, 4px spacing rhythm, transform/opacity motion
with `prefers-reduced-motion` fallbacks, SVG icons only, status hues are data.
