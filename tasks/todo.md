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

## Review round 2 — full click-test + visual QA (2026-09-27)
- Playwright full click-test (`/tmp/playwright-test-console.js`): 26 interactions, 3 dialogs, 7/7 links, **zero page/console errors** (ran twice, clean both times).
- `approval.js` `renderApprovals` crashed on empty queue (destroyed `#empty-state` node then queried it) — fixed with `APPROVALS_EMPTY` HTML constant.
- `dev_server.py`: `ThreadingHTTPServer` (browser keep-alive was starving the single thread → link-check timeouts); `/favicon.ico` → 204.
- `.btn-secondary` had no styles (Take Over/Modify Plan rendered as plain text) — added gray-outline pill.
- Footers missing on explorer / approvals / memory — added shared `.footer` markup (5/5 pages now have one).
- `.footer` itself was unstyled → appended footer CSS to console.css.
- Dashboard: `Cost (USD)` → `Cost`; `#models-body td:first-child` nowrap (gpt-4o-mini no longer wraps).

## Review round 3 — mobile + layout QA (2026-09-27)
- Mobile horizontal overflow fixed (all 5 pages scrollWidth = 390):
  - `.page { padding: X 0 Y }` overrode `.shell`'s 22px side padding (h1/cards flush at x=0) → switched to `padding-top/bottom` longhand.
  - `.dash-grid`/`.explorer-layout` mobile `1fr` = auto min-content → `minmax(0, 1fr)`; `.panel { min-width:0; overflow-x:auto }` (wide tables scroll inside the card, never the page).
  - Cost-by-model table compacted at ≤734px (bar column hidden, cells tightened) — fits fully in card.
  - `.metrics` min track 180→150px so mobile wraps 2/2/1 instead of stacking 5.
- Explorer panels equal height: `.explorer-layout { align-items: stretch }` (was `start` → 60px mismatch).
- "Jump to" pills overflowed their card (nowrap long labels) → `.btn { white-space: normal; min-width: 0 }`.
- Memory page footer floated mid-page (`body { min-height:100vh }` didn't push it down) → body flex column + `main { flex: 1 0 auto }`; nav sticky verified still works.
- Approvals mobile: clarify textarea full-width row, Ask/Close below; `.detail-row` stacks label/value at ≤720px.
- Landing blank bands in full-page screenshots = scroll-reveal capture artifact (reveals fire on scroll 5→19/27); screenshots force `.reveal` visible for review only.

## Final verification
- Geometry probes: mobile scrollWidth 390 on all pages; memory footer blank-below = 0; explorer panels 522/522; jump pills in-card desktop+mobile; metrics 5-col desktop / 2-col mobile.
- Subagent visual QA round (10 screenshots, desktop+mobile): **8/8 checks PASS, overall PASS** — gutters, cost table in card, 2-col metrics, jump pills, footers pinned, 4 approval pills, no new defects.
- Font audit for "text looks different": `-apple-system` stack + `antialiased` + Apple tracking in place — Chrome on macOS renders SF Pro; nothing non-Apple in the stack.
- Caveat: the image-read layer intermittently serves shifted screenshot files (filename↔content mismatch); QA was done by identifying pages via h1 content + PIL probes.
- Live: http://localhost:8000/ — zero errors, 26/26 interactions, all routes pass.
