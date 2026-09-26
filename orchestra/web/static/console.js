/* Orchestra console runtime: nav injection, scroll reveals, count-ups,
 * relative time, toasts. Shared by every page. No dependencies. */
"use strict";

/* ------------------------------------------------------------------ nav */
function consoleNav(active) {
  const links = [
    ["/explorer", "Explorer"],
    ["/dashboard", "Dashboard"],
    ["/approvals/ui", "Approvals"],
    ["/memory/ui", "Memory"],
  ];
  return `
    <nav class="console-nav">
      <div class="shell">
        <a class="brand" href="/">
          <span class="spark" aria-hidden="true"></span> Orchestra
        </a>
        <div class="nav-links">
          ${links.map(([href, label]) =>
            `<a href="${href}"${href === active ? ' aria-current="page"' : ""}>${label}</a>`
          ).join("")}
          <a href="/#new-task" class="nav-cta">New task</a>
        </div>
      </div>
    </nav>`;
}

function mountNav(active) {
  document.body.insertAdjacentHTML("afterbegin", consoleNav(active));
}

/* ------------------------------------------------------------------ reveals */
const revealObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (entry.isIntersecting) {
      entry.target.classList.add("in");
      revealObserver.unobserve(entry.target);
    }
  }
}, { threshold: 0.12 });

function observeReveals(root = document) {
  root.querySelectorAll(".reveal:not(.in)").forEach((el) => revealObserver.observe(el));
}

/* ------------------------------------------------------------------ count-ups */
function countUp(el, target, { decimals = 0, suffix = "", duration = 900 } = {}) {
  const start = performance.now();
  const from = 0;
  function frame(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 4);
    el.textContent = (from + (target - from) * eased).toFixed(decimals) + suffix;
    if (t < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function observeCountUps(root = document) {
  const els = root.querySelectorAll("[data-count]");
  const io = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const el = entry.target;
      io.unobserve(el);
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        el.textContent = Number(el.dataset.count).toLocaleString();
        continue;
      }
      countUp(el, Number(el.dataset.count), {
        decimals: Number(el.dataset.decimals || 0),
        suffix: el.dataset.suffix || "",
        duration: Number(el.dataset.duration || 900),
      });
    }
  }, { threshold: 0.4 });
  els.forEach((el) => io.observe(el));
}

/* ------------------------------------------------------------------ time */
function timeAgo(iso) {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 60) return Math.floor(s) + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}

/* ------------------------------------------------------------------ toast */
function toast(message) {
  let host = document.querySelector(".toast-host");
  if (!host) {
    host = document.createElement("div");
    host.className = "toast-host";
    host.style.cssText =
      "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);" +
      "display:flex;flex-direction:column;gap:8px;z-index:30;align-items:center;";
    document.body.appendChild(host);
  }
  const el = document.createElement("div");
  el.className = "toast";
  el.style.cssText =
    "background:var(--panel-2);border:1px solid var(--ember-line);color:var(--ink);" +
    "font-size:0.9rem;padding:10px 18px;border-radius:8px;box-shadow:0 8px 30px rgba(0,0,0,0.35);" +
    "opacity:0;transform:translateY(8px);transition:opacity .25s,transform .25s;";
  el.textContent = message;
  host.appendChild(el);
  requestAnimationFrame(() => { el.style.opacity = "1"; el.style.transform = "none"; });
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateY(8px)";
    setTimeout(() => el.remove(), 300);
  }, 2600);
}

/* ------------------------------------------------------------------ svg icon helper (no emoji icons) */
function icon(name, size = 16) {
  const paths = {
    play:   '<path d="M8 5v14l11-7z"/>',
    pulse:  '<path d="M3 12h4l3-8 4 16 3-8h4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    layers: '<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5" fill="none" stroke="currentColor" stroke-width="2"/><path d="m3 17 9 5 9-5" fill="none" stroke="currentColor" stroke-width="2"/>',
    shield: '<path d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5l-8-3Z"/>',
    cpu:    '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/>',
    brain:  '<circle cx="12" cy="12" r="4"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>',
    arrow:  '<path d="M5 12h14m-6-6 6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    check:  '<path d="m5 13 4 4L19 7" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>',
    x:      '<path d="M6 6l12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>',
    clock:  '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7v5l3 3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    coins:  '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M15.5 9.5a5.5 5.5 0 1 1-6 9" fill="none" stroke="currentColor" stroke-width="2"/>',
  };
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${paths[name] || ""}</svg>`;
}

/* ------------------------------------------------------------------ boot helpers */
function consoleBoot(active) {
  // Idempotent: pages that already document.write'd the nav keep it; bare
  // fragments (previews, tests) get it mounted here exactly once.
  if (!document.querySelector(".console-nav")) mountNav(active);
  observeReveals();
  observeCountUps();
}
