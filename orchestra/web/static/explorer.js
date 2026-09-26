/* Trace explorer (Phase 8, Task 44): task list + plan/results/span tree. */
"use strict";

let selectedTaskId = null;

async function loadTasks() {
  try {
    const response = await fetch("/tasks?limit=50");
    const data = await response.json();
    renderTasks(data.tasks || []);
    document.getElementById("last-refresh").textContent =
      "updated " + new Date().toLocaleTimeString();
  } catch (e) {
    console.error("Failed to load tasks:", e);
  }
}

function renderTasks(tasks) {
  const list = document.getElementById("tasks");
  if (!tasks.length) {
    list.innerHTML = '<li class="muted">No tasks yet. POST /tasks to create one.</li>';
    return;
  }
  list.innerHTML = tasks.map((task) => `
    <li data-id="${task.task_id}" class="${task.task_id === selectedTaskId ? "selected" : ""}">
      <div class="request"><span class="status-dot ${escapeHtml(task.status)}"></span>${escapeHtml(task.request)}</div>
      <div class="meta"><span>${escapeHtml(task.status)}</span><span>${new Date(task.created_at).toLocaleString()}</span></div>
    </li>`).join("");
  list.querySelectorAll("li[data-id]").forEach((li) => {
    li.addEventListener("click", () => selectTask(li.dataset.id));
  });
}

async function selectTask(taskId) {
  selectedTaskId = taskId;
  document.querySelectorAll("#tasks li").forEach((li) =>
    li.classList.toggle("selected", li.dataset.id === taskId));
  await loadDetail(taskId);
  history.replaceState(null, "", `/tasks/${taskId}/explorer`);
}

async function loadDetail(taskId) {
  const detail = document.getElementById("detail");
  detail.innerHTML = '<div class="empty-state"><h3>Loading…</h3></div>';
  const [task, trace] = await Promise.all([
    fetch(`/tasks/${taskId}`).then((r) => r.json()).catch(() => null),
    fetch(`/tasks/${taskId}/trace`).then((r) => r.json()).catch(() => null),
  ]);
  if (!task) {
    detail.innerHTML = '<div class="empty-state"><h3>Task not found</h3></div>';
    return;
  }
  detail.innerHTML = `
    <div class="section">
      <div class="task-header">
        <span class="request"><span class="status-dot ${escapeHtml(task.status)}"></span>${escapeHtml(task.request)}</span>
        <span class="muted">${escapeHtml(task.status)} · created ${new Date(task.created_at).toLocaleString()}</span>
      </div>
    </div>
    <div class="section"><h2>Plan</h2><pre>${escapeHtml(JSON.stringify(task.plan ?? [], null, 2))}</pre></div>
    <div class="section"><h2>Result</h2><pre>${escapeHtml(JSON.stringify(task.result ?? task.error ?? {}, null, 2))}</pre></div>
    <div class="section"><h2>Trace</h2>${renderSpanTree((trace && trace.roots) || [])}</div>`;
  detail.querySelectorAll(".span-row").forEach((row) => {
    row.addEventListener("click", () => {
      const attrs = row.nextElementSibling;
      if (attrs && attrs.classList.contains("span-attrs")) attrs.classList.toggle("open");
    });
  });
}

function renderSpanTree(roots) {
  if (!roots.length) return '<p class="muted">No spans recorded for this task.</p>';
  return `<ul class="span-tree">${roots.map(renderSpanNode).join("")}</ul>`;
}

function renderSpanNode(node) {
  const start = node.start_time ? Date.parse(node.start_time) : null;
  const end = node.end_time ? Date.parse(node.end_time) : null;
  const ms = start && end ? Math.max(0, end - start) : null;
  const attrs = Object.entries(node.attributes || {})
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`).join("\n");
  const children = (node.children || []).map(renderSpanNode).join("");
  return `
    <li>
      <div class="span-row"><span class="span-name">${escapeHtml(node.name)}</span>
      <span class="span-latency">${ms === null ? "" : ms + " ms"}</span></div>
      <div class="span-attrs">${escapeHtml(attrs || "(no attributes)")}</div>
      ${children ? `<ul>${children}</ul>` : ""}
    </li>`;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

if (window.location.pathname.match(/\/tasks\/[^/]+\/explorer/)) {
  const taskId = window.location.pathname.split("/")[2];
  if (taskId) {
    selectedTaskId = taskId;
    loadTasks().then(() => loadDetail(taskId));
  }
} else {
  loadTasks();
}
setInterval(loadTasks, 5000);
