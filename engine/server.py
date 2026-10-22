"""Local dashboard. Binds 127.0.0.1 only: the tracker is your data, not a website.

    uv run python -m engine serve          # http://127.0.0.1:8765
"""
import json
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import hmac
import secrets

from . import answers, ats, db, report, score

WEB = Path(__file__).resolve().parent.parent / "web"
NEEDS = ("queued", "assessment", "interview", "blocked", "offer")
TOKEN_FILE = db.DATA / "token"


def token() -> str:
    """The extension's key to this engine. Made once; `engine token` prints it for the extension's settings."""
    if not TOKEN_FILE.exists():
        db.DATA.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(secrets.token_urlsafe(24))
        TOKEN_FILE.chmod(0o600)
    return TOKEN_FILE.read_text().strip()


def canonical(url: str) -> str:
    return re.sub(r"[?#].*$", "", url or "").rstrip("/")


def find_role(con, url: str):
    u = canonical(url)
    return con.execute("select * from roles where url = ? or url = ? or ? like url || '%'", (u, url, u)).fetchone()


def ext_call(path: str, body: dict) -> dict:
    """Everything the browser extension can ask. Read your profile only to answer the questions on the page in front of you."""
    con = db.connect()
    if path == "/ext/ping":
        p = score.load_profile()
        return {"ok": True, "name": p.get("first_name"), "roles": con.execute("select count(*) from roles").fetchone()[0]}
    if path == "/ext/lookup":
        r = find_role(con, body.get("url", ""))
        return {"role": {k: r[k] for k in ("id", "company", "title", "fit", "fit_why", "eligible", "eligible_why", "status", "warm")} if r else None}
    if path == "/ext/answers":
        p = score.load_profile()
        resume = (WEB.parent / p.get("resume", "data/resume.txt"))
        qs = [q for q in body.get("questions", []) if isinstance(q, dict) and q.get("label") is not None][:200]
        return {"answers": answers.answer_all([{"label": str(q["label"])[:500], "kind": str(q.get("kind", "text")),
                                                 "options": [str(o)[:200] for o in (q.get("options") or [])][:300],
                                                 "required": bool(q.get("required"))} for q in qs],
                                               p, resume.read_text() if resume.exists() else "")}
    if path == "/ext/save":
        url = canonical(body.get("url", ""))
        if not url.startswith("https://"):
            raise ValueError("only https postings can be saved")
        if not (r := find_role(con, url)):
            found = ats.detect_url(url)
            db.upsert_role(con, {"key": url, "url": url, "company": str(body.get("company") or "Unknown")[:120],
                                 "title": str(body.get("title") or "Saved role")[:200], "location": (body.get("location") or None),
                                 "source": "extension", "ats": found[0] if found else None})
            r = find_role(con, url)
            desc = str(body.get("description") or "")[:20000] or None
            if not desc:
                try:
                    desc = ats.description(url)
                except Exception:
                    desc = None
            con.execute("update roles set description = coalesce(?, description) where id = ?", (desc, r["id"]))
        if r["status"] == "new":
            con.execute("update roles set status = 'queued' where id = ?", (r["id"],))
        scored = score.score_one(con, r["id"])
        con.commit()
        return {"role": {k: scored[k] for k in ("id", "company", "title", "fit", "fit_why", "eligible", "eligible_why")} | {"status": "queued"}}
    if path == "/ext/applied":                 # you clicked Submit on a page the extension filled
        r = find_role(con, body.get("url", ""))
        if r and r["status"] in ("new", "queued", "blocked"):
            update(r["id"], {"status": "submitted"})
            con.execute("update roles set applied_by = 'you (extension)' where id = ?", (r["id"],))
            con.commit()
        return {"ok": bool(r)}
    raise ValueError("unknown call")


def state() -> dict:
    con = db.connect()
    rows = [dict(r) for r in con.execute(
        "select r.*, substr(r.description, 1, 1500) description, (select max(at) from events e where e.role_id = r.id) last_event "
        "from roles r order by case status when 'new' then 1 else 0 end, coalesce(eligible, 1) = 0, coalesce(fit, 0) desc, "
        "coalesce(last_event, found_on) desc, id desc")]
    events = [dict(e) for e in con.execute("select * from events order by at desc limit 200")]
    runs = [dict(r) for r in con.execute("select * from runs where id in (select max(id) from runs group by job) order by id desc")]
    for r in rows:                          # attach the last prep summary, if any
        f = db.DATA / "prep" / f"{r['id']}.json"
        if f.exists() and r["status"] in ("queued", "blocked", "new"):
            prep = json.loads(f.read_text())
            r["prep"] = {"filled": prep["filled"], "fields": prep["fields"],
                         "yours": [{"label": a["label"], "suggest": a.get("suggest", []), "error": a.get("error")}
                                   for a in prep["answers"] if a["result"] in ("needs_you", "failed")]}
    needs = [r for r in rows if r["status"] in NEEDS]
    warm_seen = set()                       # one "message your contact" per company: rows arrive best fit first
    for r in rows:
        if r["status"] == "new" and r["warm"] and (r["fit"] or 0) >= 3 and r["company"] not in warm_seen:
            warm_seen.add(r["company"])
            needs.append(r)
    fu = {f["id"]: f for f in report.follow_ups(con)}
    for r in rows:
        if r["id"] in fu:
            r["follow_up"] = fu[r["id"]]
            needs.append(r)
    return {"roles": rows, "events": events, "runs": runs, "needs": needs, "health": report.health(con),
            "funnel": {"all": report.funnel(con)["all"], "track": report.funnel(con, "track"), "source": report.funnel(con, "source")}}


def update(role_id: int, body: dict) -> dict:
    con = db.connect()
    sets, args = [], []
    if "status" in body:
        if body["status"] not in db.STATUSES:
            raise ValueError(f"unknown status {body['status']!r}")
        sets.append("status = ?"); args.append(body["status"])
        if body["status"] == "submitted":
            sets.append("applied_on = coalesce(applied_on, ?)"); args.append(db.today())
            sets.append("applied_by = coalesce(applied_by, 'you')")
    for f in ("notes", "blocked_reason", "next_action"):
        if f in body:
            sets.append(f"{f} = ?"); args.append(str(body[f])[:2000])
    if body.get("log"):                     # "Followed up" and similar: history only, status unchanged
        con.execute("insert into events (role_id, at, type, summary) values (?, datetime('now'), 'note', ?)",
                    (role_id, str(body["log"])[:200]))
        if not sets:
            con.commit()
            return dict(con.execute("select * from roles where id = ?", (role_id,)).fetchone())
    if not sets:
        raise ValueError("nothing to update")
    con.execute(f"update roles set {', '.join(sets)} where id = ?", (*args, role_id))
    if "status" in body:
        con.execute("insert into events (role_id, at, type, summary) values (?, datetime('now'), 'note', ?)",
                    (role_id, f"Marked {body['status']}"))
    con.commit()
    return dict(con.execute("select * from roles where id = ?", (role_id,)).fetchone())


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ext_ok(self) -> bool:
        return hmac.compare_digest(self.headers.get("X-Engine-Token", ""), token())

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Engine-Token")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/state":
            return self._send(200, json.dumps(state()).encode())
        if m := re.fullmatch(r"/api/resume/(\d+)\.pdf", self.path):
            pdf = db.DATA / "resumes" / f"{m[1]}.pdf"
            return self._send(200, pdf.read_bytes(), "application/pdf") if pdf.exists() else self._send(404, b'{"error":"not tailored yet"}')
        if self.path in ("/", "/index.html"):
            return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        try:
            self._post()
        except Exception as e:                  # never drop the connection: say what broke
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode())

    def _post(self):
        if self.path.startswith("/ext/"):       # the browser extension: token required, any page origin refused
            if not self._ext_ok():
                return self._send(401, b'{"error":"wrong or missing engine token"}')
            if self.path == "/ext/resume":      # the PDF itself, so the extension can attach it like a drag-and-drop
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                role = find_role(db.connect(), body.get("url", "")) if body.get("url") else None
                pdf = WEB.parent / score.load_profile().get("resume_pdf", "data/resume.pdf")
                if role and (db.DATA / "resumes" / f"{role['id']}.pdf").exists():
                    pdf = db.DATA / "resumes" / f"{role['id']}.pdf"        # tailored for this posting
                if not pdf.exists():
                    return self._send(404, b'{"error":"no resume_pdf in your profile"}')
                data = pdf.read_bytes()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/pdf")
                self.send_header("X-File-Name", pdf.name)
                self.send_header("Access-Control-Expose-Headers", "X-File-Name")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                out = json.dumps(ext_call(self.path, body)).encode()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                return self.wfile.write(out)
            except (ValueError, TypeError, KeyError) as e:
                return self._send(400, json.dumps({"error": str(e)}).encode())
        m = re.fullmatch(r"/api/role/(\d+)(/prep|/tailor)?", self.path)
        # same-origin only: a page on another site must not be able to change your tracker
        if not m or self.headers.get("Origin") not in (None, f"http://{self.headers.get('Host')}"):
            return self._send(403, b'{"error":"forbidden"}')
        if m[2] == "/tailor":                   # reorder your resume for this posting; never adds a word
            from . import resume
            try:
                return self._send(200, json.dumps(resume.tailor(int(m[1]))).encode())
            except SystemExit as e:
                return self._send(400, json.dumps({"error": str(e)}).encode())
        if m[2]:                                # Prep: a visible browser on this laptop, filled up to (never past) Submit
            subprocess.Popen([sys.executable, "-m", "engine", "fill", m[1]], cwd=str(WEB.parent),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return self._send(202, b'{"ok":true}')
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self._send(200, json.dumps(update(int(m[1]), body)).encode())
        except (ValueError, TypeError) as e:
            self._send(400, json.dumps({"error": str(e)}).encode())

    def log_message(self, *a):
        pass


def serve(port: int = 8765) -> None:
    token()
    print(f"Dashboard: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
