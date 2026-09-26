/* Orchestra approval queue: polls /approvals/pending, renders decision cards,
 * and posts decisions to /approvals/{id}/decide (which resumes the paused
 * worker). Clarify asks /approvals/{id}/clarify without resuming the run. */
"use strict";

const POLL_SECONDS = 3;

async function loadApprovals() {
  try {
    const response = await fetch("/approvals/pending");
    const approvals = await response.json();
    renderApprovals(approvals);
    document.getElementById("last-refresh").textContent =
      "updated " + new Date().toLocaleTimeString();
  } catch (e) {
    console.error("Failed to load approvals:", e);
  }
}

function renderApprovals(approvals) {
  const container = document.getElementById("approvals-container");
  const emptyState = document.getElementById("empty-state");

  if (approvals.length === 0) {
    container.innerHTML = "";
    container.appendChild(emptyState);
    emptyState.style.display = "block";
    return;
  }

  emptyState.style.display = "none";
  container.innerHTML = approvals.map(renderApprovalCard).join("");
}

function renderApprovalCard(a) {
  const created = new Date(a.created_at).toLocaleString();
  const ctx = a.context || {};
  const rows = [
    ["Task", `<a href="/tasks/${a.task_id}" class="task-link" target="_blank">${a.task_id}</a>`],
    ["Trigger", escapeHtml(a.trigger)],
    ["Proposed Action", escapeHtml(a.proposed_action || "N/A")],
  ];
  // Surface the decision-critical context fields as rows.
  if (ctx.tool_name) rows.push(["Tool", escapeHtml(ctx.tool_name)]);
  if (ctx.arguments) rows.push(["Arguments", `<code>${escapeHtml(JSON.stringify(ctx.arguments))}</code>`]);
  if (ctx.plan_confidence !== undefined)
    rows.push(["Plan Confidence", escapeHtml(String(ctx.plan_confidence))]);
  if (ctx.subtask_id) rows.push(["Subtask", escapeHtml(ctx.subtask_id)]);
  if (ctx.error) rows.push(["Error", escapeHtml(ctx.error)]);

  const isPlan = a.escalation_level === "approve_plan";
  const modifyBlock = isPlan
    ? `<div class="mod-plan" id="modify-${a.id}">
         <textarea id="modify-input-${a.id}">${escapeHtml(JSON.stringify(ctx.plan || [], null, 2))}</textarea>
         <div class="hint">Edit the plan JSON, then send. The run continues with your version.</div>
         <div class="form-actions">
           <button class="btn btn-primary" onclick="sendModify('${a.id}')">Send Modified Plan</button>
           <button class="btn btn-secondary" onclick="hide('modify-${a.id}')">Cancel</button>
         </div>
       </div>`
    : "";

  return `
    <div class="approval-card" data-id="${a.id}">
      <div class="card-header">
        <span class="escalation-badge ${a.escalation_level}">${escapeHtml(a.escalation_level.replace(/_/g, " "))}</span>
        <span class="muted">${created}</span>
      </div>
      <div class="card-body">
        ${rows.map(([label, value]) => `
          <div class="detail-row">
            <span class="detail-label">${label}</span>
            <span class="detail-value">${value}</span>
          </div>`).join("")}
        <div class="context-box">
          <strong>Full context:</strong>
          <pre>${escapeHtml(JSON.stringify(ctx, null, 2))}</pre>
        </div>

        <div class="actions">
          <button class="btn btn-success" data-act="approve" onclick="decide('${a.id}', 'approve', this)">Approve</button>
          <button class="btn btn-danger" data-act="reject" onclick="decide('${a.id}', 'reject', this)">Reject</button>
          ${isPlan ? `<button class="btn btn-secondary" onclick="show('modify-${a.id}')">Modify Plan</button>` : ""}
          <button class="btn btn-secondary" data-act="take_over" onclick="decide('${a.id}', 'take_over', this)">Take Over</button>
          <button class="btn btn-primary" onclick="show('clarify-${a.id}')">Clarify</button>
        </div>
        <div class="status-note" id="note-${a.id}" style="display:none"></div>
        <div class="error-note" id="error-${a.id}" style="display:none"></div>

        ${modifyBlock}

        <div class="clarify-log" id="clarify-${a.id}">
          <div class="entries" id="clarify-log-${a.id}"></div>
          <div class="clarify-form">
            <textarea id="clarify-input-${a.id}" placeholder="Ask about this paused run..."></textarea>
            <button class="btn btn-primary" onclick="sendClarify('${a.id}', this)">Ask</button>
            <button class="btn btn-secondary" onclick="hide('clarify-${a.id}')">Close</button>
          </div>
        </div>
      </div>
    </div>`;
}

async function decide(approvalId, action, button) {
  const payload = { action };
  if (action === "take_over") {
    const reason = prompt("Reason for taking over (recorded with the decision):");
    if (reason === null) return;
    payload.clarification_question = reason;
  }
  await postDecision(approvalId, payload, button);
}

async function sendModify(approvalId, button) {
  const raw = document.getElementById(`modify-input-${approvalId}`).value;
  let plan;
  try {
    plan = JSON.parse(raw);
  } catch (e) {
    showError(approvalId, "Plan JSON does not parse: " + e.message);
    return;
  }
  await postDecision(approvalId, { action: "modify", modified_plan: plan }, button);
}

async function sendClarify(approvalId, button) {
  const input = document.getElementById(`clarify-input-${approvalId}`);
  const question = input.value.trim();
  if (!question) return;
  button.disabled = true;
  try {
    const response = await fetch(`/approvals/${approvalId}/clarify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "clarify failed");
    const log = document.getElementById(`clarify-log-${approvalId}`);
    const entry = document.createElement("div");
    entry.className = "entry";
    entry.innerHTML = `<div class="q">Q: ${escapeHtml(question)}</div><div class="a">A: ${escapeHtml(data.answer)}</div>`;
    log.appendChild(entry);
    input.value = "";
  } catch (e) {
    showError(approvalId, "Clarify failed: " + e.message);
  } finally {
    button.disabled = false;
  }
}

async function postDecision(approvalId, payload, button) {
  if (button) button.disabled = true;
  hideNote(`error-${approvalId}`);
  try {
    const response = await fetch(`/approvals/${approvalId}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "decision failed");
    showNote(approvalId, `Decision "${payload.action}" recorded; the task is resuming.`);
    const card = document.querySelector(`[data-id="${approvalId}"] .actions`);
    if (card) card.querySelectorAll("button").forEach((b) => (b.disabled = true));
  } catch (e) {
    showError(approvalId, e.message);
    if (button) button.disabled = false;
  }
}

function showNote(id, text) {
  const el = document.getElementById(`note-${id.replace(/^[^-]+-/, "")}`) ||
    document.getElementById(`note-${id}`);
  if (el) { el.textContent = text; el.style.display = "block"; }
}

function showError(approvalId, text) {
  const el = document.getElementById(`error-${approvalId}`);
  if (el) { el.textContent = text; el.style.display = "block"; }
}

function hideNote(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "none";
}

function show(id) { const el = document.getElementById(id); if (el) el.style.display = "block"; }
function hide(id) { const el = document.getElementById(id); if (el) el.style.display = "none"; }

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

setInterval(loadApprovals, POLL_SECONDS * 1000);
loadApprovals();
