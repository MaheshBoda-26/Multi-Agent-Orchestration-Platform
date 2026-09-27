# Orchestra console — Apple design rebuild

## Plan
- [x] Write design.md (Apple "Cupertino Precision Minimalism" spec)
- [x] Rebuild console.css on Apple tokens; keep legacy class API
- [x] Rebuild index.html landing (hero, loop grid, stats band, trust ledger, composer, footer)
- [x] Re-skin explorer / dashboard / approvals / memory via shared classes
- [x] Build dev_server.py — clean URLs + in-memory mock API (no Postgres/Celery)
- [x] Verify all routes + write paths (POST /tasks, decide, clarify, memories)
- [x] Screenshot every page; fix visual/logic defects
- [x] Run site on localhost

## Review (2026-09-27)
- Live: http://localhost:8000/ (start: `cd orchestra && nohup python3 dev_server.py 8000 &`)
- Pages: `/`, `/explorer`, `/dashboard`, `/approvals/ui`, `/memory/ui`, `/tasks/{id}/explorer`
- Bugs found & fixed this pass:
  - Dashboard token metrics stuck at 0 — global count-up (`data-count="0"`) overwrote fetched values; removed static data-count from prompt/completion.
  - `<p class="empty"><h3>…</h3></p>` — HTML parser auto-closes `<p>` before `<h3>`, so `display:none` landed on an empty `<p>` and the empty-state text rendered permanently; switched to `<div>`.
  - Escalations table showed a permanent skeleton when empty; now clears body and shows the empty state.
  - `/tasks/{id}` opened as raw JSON from the approval card; browser navigations (`Accept: text/html`) now 302 to `/tasks/{id}/explorer`, fetch still gets JSON.
  - Memory page required typing a user id; prefilled `console-user` + auto-loads, and fixed a null crash in `renderMemories` when switching to an empty user.
  - `9,100 ms` metric wrapped to two lines; nowrap + slightly smaller clamp.
  - Deleted unreferenced legacy pages: `*_preview.html`, `explorer_snapshot.html`.
- Seeds: 4 tasks (one trips the sensitive-tool gate → 1 pending approval), 4 memory lessons.
- Verified: all routes 200, dispatch toast + explorer link, deep-link auto-select, zero page errors.
