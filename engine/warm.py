"""Warm lane: roles at companies where you know someone get flagged, with an outreach draft.

Contacts come from data/contacts.csv: LinkedIn's own export (Settings → Data privacy → Get a copy
of your data → Connections) or any CSV with First Name, Last Name, Company, Position, URL columns.

Drafts follow two rules: under 200 characters (a LinkedIn note without Premium), and built only from
facts in your profile. Nothing is ever sent — you copy it. Only name, company, position and profile link
are kept from the export; emails and the rest are dropped on read.

    uv run python -m engine warm
"""
import csv
import io
import re

from . import db, score

CONTACTS = db.DATA / "contacts.csv"
LIMIT = 200
SUFFIX = re.compile(r"\b(inc|llc|llp|ltd|corp(oration)?|company|co|group|the|us|usa|na|holdings|plc)\b\.?", re.I)


def company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", SUFFIX.sub(" ", (name or "").lower()))


def load_contacts(path=CONTACTS) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig")
    start = next((i for i, l in enumerate(text.splitlines()) if l.startswith("First Name")), 0)   # LinkedIn puts notes above the header
    rows = csv.DictReader(io.StringIO("\n".join(text.splitlines()[start:])))
    keep = ("First Name", "Last Name", "Company", "Position", "URL")
    return [{k: r.get(k) for k in keep} for r in rows if r.get("Company")]


def short_title(title: str, location: str = "") -> str:
    t = re.sub(r"\s*[-–|(].*$", "", title)                     # "Data Analyst Intern - Summer 2027 (Hybrid)" → "Data Analyst Intern"
    city = {w.lower() for w in re.findall(r"[A-Za-z]+", location or "")}
    t = " ".join(w for w in t.split() if w.lower() not in city) or t   # "Atlanta Technology Consulting Intern" → "Technology Consulting Intern"
    return t if len(t) <= 48 else t[:45].rsplit(" ", 1)[0] + "…"


def draft(contact: dict, role: dict, p: dict) -> str:
    """Who you are · why them · one small ask. Shortens itself to fit; never invents."""
    first = (contact.get("First Name") or "").strip() or "there"
    who = f"{p.get('class_standing', 'student').title()} at {p.get('school_short') or p.get('school', '')}".strip()
    hook = p.get("hook", "")
    for parts in ([f"Hi {first}, {who}, applying to {role['company']}'s {short_title(role['title'], role.get('location'))}.", hook, "Could I ask you 2 quick questions about the team?"],
                  [f"Hi {first}, {who}, applying to {role['company']}'s {short_title(role['title'], role.get('location'))}.", hook, "Open to 2 quick questions?"],
                  [f"Hi {first}, {who}, applying to {role['company']}.", "Open to 2 quick questions about the team?"]):
        msg = " ".join(x for x in parts if x)
        if len(msg) <= LIMIT:
            return msg
    return msg[:LIMIT - 1] + "…"


def run() -> dict:
    con = db.connect()
    p = score.load_profile()
    contacts = load_contacts()
    by_company: dict[str, list[dict]] = {}
    for c in contacts:
        by_company.setdefault(company_key(c["Company"]), []).append(c)
    con.execute("update contacts set email = null where source = 'linkedin'")     # older imports kept these; nothing uses them
    for c in contacts:                       # everyone in the export lands in People: name, company, position, profile link only
        con.execute("""insert into contacts (name, company, title, url, source) values (?, ?, ?, ?, 'linkedin')
                       on conflict(name, company) do update set title = excluded.title, url = excluded.url""",
                    (f"{c.get('First Name', '')} {c.get('Last Name', '')}".strip(), c.get("Company"), c.get("Position"), c.get("URL")))
    flagged = 0
    con.execute("update roles set warm = null, outreach = null where status in ('new', 'queued')")
    for r in [dict(r) for r in con.execute("select * from roles where status in ('new', 'queued') and coalesce(eligible, 1) > 0")]:
        key = company_key(r["company"])
        people = by_company.get(key) or next((v for k, v in by_company.items() if len(k) > 4 and (k in key or key in k)), None)
        if not people:
            continue
        c = people[0]
        who = f"{c.get('First Name', '')} {c.get('Last Name', '')}".strip() + (f", {c['Position']}" if c.get("Position") else "")
        con.execute("update roles set warm = ?, outreach = ? where id = ?",
                    (f"{who} | {c.get('URL', '')}".strip(" |"), draft(c, r, p), r["id"]))
        flagged += 1
    con.commit()
    db.log_run(con, "warm", len(contacts), flagged, [] if contacts else ["no data/contacts.csv yet"])
    return {"contacts": len(contacts), "warm_roles": flagged}


def _selfcheck() -> None:
    p = {"class_standing": "junior", "school_short": "State U", "hook": "I run AI agents in production at a company I co-founded."}
    r = {"company": "Northwind", "title": "Consultative Offerings - Summer Associate - Enterprise Tech Strategy"}
    m = draft({"First Name": "Sam"}, r, p)
    assert len(m) <= LIMIT and m.startswith("Hi Sam, Junior at State U") and "co-founded" in m, m
    assert short_title("Atlanta Technology Consulting Intern - 2027", "ATLANTA - PEACHTREE RD") == "Technology Consulting Intern"
    long = draft({"First Name": "Alexandria"}, {"company": "X", "title": "A" * 120}, p)
    assert len(long) <= LIMIT, long
    assert company_key("Northwind LLP") == company_key("Northwind") == "northwind"
    export = "Notes:\nWhen exporting...\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\nSam,Lee,https://linkedin.com/in/x,sam@northwind.example,Northwind,Senior Consultant,01 Oct 2026\n"
    import pathlib, tempfile
    f = pathlib.Path(tempfile.mkdtemp()) / "c.csv"
    f.write_text(export)
    row = load_contacts(f)[0]
    assert row["Position"] == "Senior Consultant" and "Email Address" not in row and "sam@" not in str(row), row


if __name__ == "__main__":
    _selfcheck()
    print("ok")
