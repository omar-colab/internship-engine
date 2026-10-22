"""Funnel, follow-ups, health, and the weekly digest. All read-only over the tracker.

    uv run python -m engine digest        # writes data/digest/<date>.md and shows a notification
"""
import json
import subprocess
from datetime import date, datetime, timedelta

from . import db, score

APPLIED = ("submitted", "assessment", "interview", "offer", "rejected", "ghosted")
REPLY_EVENTS = ("assessment", "interview", "rejection", "reply")


def settings() -> dict:
    p = score.load_profile()
    return {"follow_up_days": p.get("follow_up_days", 14), "ghost_days": p.get("ghost_days", 35)}


def funnel(con, by: str | None = None) -> dict:
    """found → queued → applied → replied → interview → offer, overall or split by track/source."""
    rows = [dict(r) for r in con.execute("select * from roles")]
    ev: dict[int, set] = {}
    for e in con.execute("select role_id, type, summary from events"):
        ev.setdefault(e["role_id"], set()).add(e["type"] if e["type"] != "note" else (e["summary"] or "").lower())
    def stage(r):
        t = ev.get(r["id"], set())
        applied = r["status"] in APPLIED or bool(r["applied_on"])
        return {
            "found": True,
            "queued": applied or r["status"] in ("queued", "blocked") or "marked queued" in t,
            "applied": applied,
            "replied": bool(t & set(REPLY_EVENTS)),
            "interview": r["status"] in ("interview", "offer") or "interview" in t,
            "offer": r["status"] == "offer",
        }
    groups: dict[str, dict] = {}
    for r in rows:
        key = "all" if not by else (r[by] or "other").split(":")[0]
        g = groups.setdefault(key, {s: 0 for s in ("found", "queued", "applied", "replied", "interview", "offer")})
        for s, on in stage(r).items():
            g[s] += on
    return groups


def follow_ups(con) -> list[dict]:
    """Applied, no word since: due for a nudge (follow_up_days) or ready to call ghosted (ghost_days)."""
    s = settings()
    out = []
    for r in con.execute("""select r.*, (select max(at) from events e where e.role_id = r.id) last
                            from roles r where status = 'submitted' and applied_on is not null"""):
        last = (r["last"] or r["applied_on"])[:10]
        idle = (date.today() - date.fromisoformat(last)).days
        if idle >= s["follow_up_days"]:
            out.append({"id": r["id"], "company": r["company"], "title": r["title"], "idle_days": idle,
                        "action": "ghost" if idle >= s["ghost_days"] else "follow_up"})
    return out


def contacts_due(con) -> list[dict]:
    """People you messaged whose follow-up date has come."""
    return [dict(r) for r in con.execute("select * from contacts where status = 'messaged' and next_on <= date('now')")]


def new_match_alert() -> int:
    """After the morning run: a notification when roles scoring 5 appeared today."""
    con = db.connect()
    rows = con.execute("""select company from roles where found_on = date('now', 'localtime') and fit = 5 and coalesce(eligible, 1) > 0
                          and status = 'new'""").fetchall()
    if rows:
        names = ", ".join(sorted({r["company"] for r in rows})[:3])
        subprocess.run(["osascript", "-e", f'display notification "{len(rows)} new fit-5 roles: {names}" with title "Internship Engine"'],
                       capture_output=True)
    return len(rows)


def health(con) -> list[str]:
    """Plain warnings for the dashboard banner."""
    warn = []
    last = con.execute("select * from runs where job in ('find', 'daily') order by id desc limit 1").fetchone()
    if not last:
        warn.append("Jobs haven't been checked yet. Run: uv run python -m engine daily")
    else:
        age = datetime.utcnow() - datetime.fromisoformat(last["started"])
        if age > timedelta(hours=48):
            warn.append(f"No job check in {age.days} days. Is the laptop asleep at 7:00, or the schedule off?")
    if not con.execute("select 1 from runs where job = 'listen' and started > datetime('now', '-3 days')").fetchone():
        warn.append("Your inbox hasn't been read in 3 days, so statuses may be stale.")
    return warn


def digest() -> str:
    con = db.connect()
    week = (date.today() - timedelta(days=7)).isoformat()
    new_good = con.execute("select count(*) from roles where found_on >= ? and fit >= 4 and coalesce(eligible, 1) > 0", (week,)).fetchone()[0]
    applied = con.execute("select count(*) from roles where applied_on >= ?", (week,)).fetchone()[0]
    replies = [dict(r) for r in con.execute("""select r.company, e.type, e.summary from events e join roles r on r.id = e.role_id
                                               where e.at >= ? and e.type in ('assessment', 'interview', 'rejection', 'reply')
                                               order by e.at""", (week,))]
    open_assess = [r["company"] for r in con.execute("select company from roles where status = 'assessment'")]
    fu = follow_ups(con)
    f = funnel(con)["all"]
    rate = lambda a, b: f"{round(100 * a / b)}%" if b else "–"
    lines = [f"# Week of {week}", "",
             f"- **{new_good}** new roles scored 4–5",
             f"- **{applied}** applications sent",
             f"- **{len(replies)}** replies: " + (", ".join(f"{r['company']} ({r['type']})" for r in replies) or "none"), ""]
    if open_assess:
        lines += ["## Assessments waiting", *[f"- {c}" for c in open_assess], ""]
    if fu:
        lines += ["## Follow-ups due", *[f"- {x['company']}: {x['title'] if x['title'] != '(role from email)' else 'role not named'} ({x['idle_days']} days quiet)" for x in fu], ""]
    lines += ["## All time", f"{f['applied']} applied → {f['replied']} replied ({rate(f['replied'], f['applied'])}) → "
              f"{f['interview']} interviews ({rate(f['interview'], f['applied'])}) → {f['offer']} offers", ""]
    if warn := health(con):
        lines += ["## Check", *[f"- {w}" for w in warn], ""]
    text = "\n".join(lines)
    out = db.DATA / "digest"
    out.mkdir(exist_ok=True)
    (out / f"{date.today().isoformat()}.md").write_text(text)
    db.log_run(con, "digest", applied, new_good, [])
    note = f"{new_good} strong new roles, {applied} sent, {len(replies)} replies" + (f", {len(fu)} follow-ups due" if fu else "")
    subprocess.run(["osascript", "-e", f'display notification "{note}" with title "Internship Engine: your week"'], capture_output=True)
    return text


def _selfcheck() -> None:
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    for col, typ in db.MIGRATIONS["roles"].items():
        con.execute(f"alter table roles add column {col} {typ}")
    old = (date.today() - timedelta(days=20)).isoformat()
    con.executemany("insert into roles (id, key, company, title, found_on, status, applied_on, track, source) values (?,?,?,?,?,?,?,?,?)", [
        (1, "a", "A", "t", old, "new", None, "data-analytics", "workday"),
        (2, "b", "B", "t", old, "submitted", old, "data-analytics", "workday"),
        (3, "c", "C", "t", old, "interview", old, "ai-consulting", "greenhouse"),
        (4, "d", "D", "t", old, "rejected", old, "ai-consulting", "inbox")])
    con.executemany("insert into events (role_id, at, type) values (?,?,?)", [(3, old, "interview"), (4, old, "rejection")])
    f = funnel(con)["all"]
    assert (f["found"], f["applied"], f["replied"], f["interview"]) == (4, 3, 2, 1), f
    assert funnel(con, "track")["ai-consulting"]["applied"] == 2
    fu = follow_ups(con)
    assert [x["company"] for x in fu] == ["B"] and fu[0]["action"] == "follow_up", fu


if __name__ == "__main__":
    _selfcheck()
    print("ok")
