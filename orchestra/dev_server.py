#!/usr/bin/env python3
"""Orchestra local dev server.

Serves the web console with production-clean URLs (so /explorer, /dashboard,
/approvals/ui, /memory/ui and /tasks/<id>/explorer all resolve) plus a
lightweight in-memory API that mirrors the real FastAPI surface, so every
page is fully interactive without Postgres/Celery/Redis.

Usage: python3 dev_server.py [port]   (default 8000)
"""
import json
import time
import uuid
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

WEB = Path(__file__).parent / "web"

# ---------------------------------------------------------------- demo state
STORE = {"tasks": {}, "order": [], "approvals": {}, "memories": {}}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def mk_task(description, user_id, status="completed"):
    tid = uuid.uuid4().hex[:12]
    created = now_iso()
    plan = [
        {"id": "sub-1", "title": "Gather sources", "depends_on": []},
        {"id": "sub-2", "title": "Compare options", "depends_on": ["sub-1"]},
        {"id": "sub-3", "title": "Write recommendation", "depends_on": ["sub-2"]},
    ]
    spans = [
        {"name": "supervisor.plan", "attributes": {"subtasks": 3, "plan_confidence": 0.87},
         "children": [{"name": "memory.retrieve", "attributes": {"lessons_used": 2}, "children": []}]},
        {"name": "specialist.execute sub-1", "attributes": {"tool_calls": 4, "sandbox": "workspace jail"},
         "children": []},
        {"name": "specialist.execute sub-2", "attributes": {"tool_calls": 3}, "children": []},
        {"name": "specialist.execute sub-3", "attributes": {"tool_calls": 2}, "children": []},
        {"name": "reviewer.gate", "attributes": {"score": 0.91, "verdict": "pass"}, "children": []},
        {"name": "memory.remember", "attributes": {"store": "pgvector", "kind": "lesson"}, "children": []},
    ]
    t0 = time.time()
    cursor = t0
    for s in spans:
        start = cursor
        end = start + 0.8 + (uuid.uuid4().int % 40) / 10
        s["start_time"] = datetime.fromtimestamp(start, timezone.utc).isoformat()
        s["end_time"] = datetime.fromtimestamp(end, timezone.utc).isoformat()
        for c in s["children"]:
            c["start_time"] = s["start_time"]
            c["end_time"] = datetime.fromtimestamp(start + 0.3, timezone.utc).isoformat()
        cursor = end

    STORE["tasks"][tid] = {
        "task_id": tid,
        "request": description,
        "status": status,
        "created_at": created,
        "user_id": user_id,
        "plan": plan,
        "result": {
            "answer": f"Synthesis for “{description}”: 3 subtasks executed in parallel, "
                      "reviewer score 0.91, one lesson stored for next time.",
            "cost_usd": 0.018, "latency_ms": 9100, "tokens": {"prompt": 4210, "completion": 1380},
        },
        "spans": spans,
    }
    STORE["order"].insert(0, tid)

    memories = STORE["memories"].setdefault(user_id or "console-user", [])
    memories.insert(0, {
        "id": len(memories) + 1,
        "content": f"Lesson from “{description}”: decompose into 3 subtasks; "
                   "retrieval-first plans score higher with this user.",
        "kind": "lesson",
        "importance": 0.78,
        "access_count": 0,
        "source_task_id": tid,
        "created_at": created,
    })

    # Tasks that touch sensitive tools pause for a human, like the real gate.
    if any(k in description.lower() for k in ("deploy", "write a file", "send email", "delete")):
        aid = uuid.uuid4().hex[:10]
        STORE["approvals"][aid] = {
            "id": aid,
            "task_id": tid,
            "created_at": created,
            "trigger": "sensitive tool call",
            "escalation_level": "tool_signature",
            "proposed_action": "execute code_execute in sandbox",
            "context": {
                "tool_name": "code_execute",
                "arguments": {"language": "python", "snippet": description[:120]},
                "subtask_id": "sub-2",
            },
        }
        STORE["tasks"][tid]["status"] = "awaiting_human"
    return tid


# Seed the demo fleet (the "deploy" task trips the sensitive-tool gate,
# so a fresh server already has one pending approval to review)
mk_task("Research vector DBs", "console-user")
mk_task("Draft vendor matrix", "console-user")
mk_task("Weekly cost rollup", "console-user")
mk_task("Deploy the release to staging", "console-user")


# ---------------------------------------------------------------- handler
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    # ---- helpers
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _page(self, name):
        self.path = "/" + name
        super().do_GET()

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    # ---- routing
    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/")
        if p == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if p in ("", "/index.html"):
            return self._page("index.html")
        if p == "/explorer":
            return self._page("explorer.html")
        if p == "/dashboard":
            return self._page("dashboard.html")
        if p == "/approvals/ui":
            return self._page("approval_page.html")
        if p == "/memory/ui":
            return self._page("memory.html")
        if p.startswith("/tasks/") and p.endswith("/explorer"):
            return self._page("explorer.html")
        if p == "/api/docs":
            return self._json({
                "Orchestra dev API": "in-memory mock of the FastAPI surface",
                "routes": ["POST /tasks", "GET /tasks?limit=50", "GET /tasks/{id}",
                           "GET /tasks/{id}/trace", "GET /stats/cost",
                           "GET /approvals/pending", "POST /approvals/{id}/decide",
                           "POST /approvals/{id}/clarify",
                           "GET/DELETE /users/{id}/memories"],
            })

        # ----- API
        if p == "/tasks":
            return self._json({"tasks": [
                {k: t[k] for k in ("task_id", "request", "status", "created_at")}
                for t in (STORE["tasks"][tid] for tid in STORE["order"])
            ]})
        if p.startswith("/tasks/") and p.endswith("/trace"):
            tid = p.split("/")[2]
            t = STORE["tasks"].get(tid)
            return self._json({"roots": t["spans"]} if t else {"detail": "not found"},
                              200 if t else 404)
        if p.startswith("/tasks/"):
            tid = p.split("/")[2]
            # browser navigation (Accept: text/html) → explorer page;
            # fetch() (Accept: */*) keeps receiving JSON
            if "text/html" in (self.headers.get("Accept") or ""):
                self.send_response(302)
                self.send_header("Location", f"/tasks/{tid}/explorer")
                self.end_headers()
                return
            t = STORE["tasks"].get(tid)
            if not t:
                return self._json({"detail": "not found"}, 404)
            return self._json(t)
        if p == "/stats/cost":
            tasks = list(STORE["tasks"].values())
            by_status = {}
            for t in tasks:
                by_status[t["status"]] = by_status.get(t["status"], 0) + 1
            esc = {}
            for a in STORE["approvals"].values():
                esc.setdefault(a["trigger"], {}).setdefault("pending", 0)
                esc[a["trigger"]]["pending"] += 1
            return self._json({
                "runs": len(tasks),
                "cost_usd": round(0.018 * len(tasks), 3),
                "prompt_tokens": 4210 * len(tasks),
                "completion_tokens": 1380 * len(tasks),
                "avg_latency_ms": 9100,
                "models": {"gpt-4o-mini": {"prompt_tokens": 4210 * len(tasks),
                                           "completion_tokens": 1380 * len(tasks),
                                           "cost_usd": round(0.018 * len(tasks), 3)}},
                "runs_by_status": by_status,
                "escalations": esc,
            })
        if p == "/approvals/pending":
            return self._json(list(STORE["approvals"].values()))
        if p.startswith("/users/") and p.endswith("/memories"):
            uid = p.split("/")[2]
            return self._json({"memories": STORE["memories"].get(uid, [])})

        return super().do_GET()

    def do_POST(self):
        p = self.path.split("?")[0].rstrip("/")
        if p == "/tasks":
            data = self._body()
            desc = (data.get("task_description") or "").strip()
            if not desc:
                return self._json({"detail": "task_description required"}, 422)
            tid = mk_task(desc, data.get("user_id"))
            return self._json({"task_id": tid}, 201)
        if p.startswith("/approvals/") and p.endswith("/decide"):
            aid = p.split("/")[2]
            if aid not in STORE["approvals"]:
                return self._json({"detail": "not found"}, 404)
            STORE["approvals"].pop(aid)
            return self._json({"ok": True, "resumed": True})
        if p.startswith("/approvals/") and p.endswith("/clarify"):
            aid = p.split("/")[2]
            if aid not in STORE["approvals"]:
                return self._json({"detail": "not found"}, 404)
            q = self._body().get("question", "")
            return self._json({"answer": f"[mock supervisor] Re: “{q}” — this call is paused "
                                         "because it matches a sensitive signature. Approving "
                                         "executes it inside the workspace jail with a full audit row."})
        return self._json({"detail": "not found"}, 404)

    def do_DELETE(self):
        p = self.path.split("?")[0].rstrip("/")
        if p.startswith("/users/") and p.endswith("/memories"):
            uid = p.split("/")[2]
            n = len(STORE["memories"].get(uid, []))
            STORE["memories"][uid] = []
            return self._json({"deleted": n})
        return self._json({"detail": "not found"}, 404)


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Orchestra dev console → http://localhost:{port}")
    server.serve_forever()
