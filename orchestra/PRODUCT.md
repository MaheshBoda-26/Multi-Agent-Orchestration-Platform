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
**Premium clarity.** The whole console follows the Apple.com web language
(see `../design.md`): light neutral canvas, SF Pro stack, one accent
(`#0071e3`), pill CTAs, hairline structure, dark blurred 44px nav. Data-dense
panels keep their density — the language changes chrome and canvas, not
information. The UI's job is still to make the pipeline legible and the
numbers trustworthy.

## Surfaces
- `/` — landing: what it is, the loop, the numbers, dispatch a task inline.
- `/explorer` (+ per-task) — task list and full span traces.
- `/dashboard` — fleet cost/latency/escalation rollup.
- `/approvals/ui` — the durable human decision queue.
- `/memory/ui` — per-user long-term memory inspect/erase.

## Design system
"Cupertino Precision Minimalism" — full spec in `../design.md`; implemented in
`web/static/console.css` (tokens) and `web/static/console.js` (shared runtime).
Key invariants: hex tokens from the Apple palette (`#f5f5f7` / `#1d1d1f` /
`#0071e3`), SF Pro Text/Display via `-apple-system` stack + SF Mono for data,
8px rhythm with 100px section air, 18px card radii and 980px pills,
`cubic-bezier(0.28,0.11,0.32,1)` transform/opacity motion with
`prefers-reduced-motion` fallbacks, SVG icons only, status hues are data.
