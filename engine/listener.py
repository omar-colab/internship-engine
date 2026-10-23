"""Listener: application emails → status changes + events. Read-only on the inbox.

Two ways in, same rules:
  • IMAP with a Gmail app password (GMAIL_ADDRESS + GMAIL_APP_PASSWORD) — for scheduled runs
  • `import` of a JSON list of {id, from, subject, snippet, date} — what Claude Code's Gmail
    connector returns, so the operator can sync without any password

    uv run python -m engine listen            # IMAP, last 14 days
    uv run python -m engine import mail.json
"""
import email
import email.header
import email.utils
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timedelta

from . import db, platform

ALERT_SENDERS = re.compile(r"jobright\.ai|jobalert\.indeed|jobs-listings@linkedin|wellfound|handshake|simplify\.jobs", re.I)
RULES = [  # first match wins; order matters (a rejection often says "thank you for applying")
    ("rejection", r"regret|not (be )?(moving|proceeding|move) forward|other candidates|able to offer you|unable to offer|decided not to"),
    ("assessment", r"assessment|hirevue|recorded interview|online test|codility|hackerrank|pymetrics|game-based"),
    ("interview", r"\binterview\b|schedule (a|your) (call|chat|time)|superday"),
    ("confirmation", r"(thank you|thanks) for (applying|your (interest|application)|submitting)|application (received|was sent)|"
                     r"you have applied|"
                     r"successfully submitted|received your application|your application with"),
]
STATUS_FOR = {"confirmation": "submitted", "assessment": "assessment", "interview": "interview", "rejection": "rejected"}
RANK = {s: i for i, s in enumerate(["new", "queued", "blocked", "skipped", "submitted", "assessment", "interview", "offer"])}
ATS_DOMAINS = re.compile(r"myworkday|greenhouse|lever\.co|ashbyhq|icims|taleo|successfactors|smartrecruiters|jobvite|gmail")


def classify(sender: str, subject: str, snippet: str) -> str | None:
    if ALERT_SENDERS.search(sender):
        return "alert"
    text = f"{subject} {snippet}".lower()
    return next((kind for kind, rx in RULES if re.search(rx, text)), None)


def company_hint(sender: str, subject: str) -> str:
    """Best guess at the employer: subject phrasing first, then the sender's address."""
    m = re.search(r"(?i:applying to|application with|interest in|application to) ([A-Z][\w&.' -]{1,40}?)(?:[!.,]| \d|$)", subject)
    if m:
        return m.group(1).strip()
    m = re.search(r"^(?:your )?([A-Z][\w&.' -]{1,30}?) (?:job )?application", subject, re.I)
    if m and m.group(1).lower() not in ("your", "job"):
        return m.group(1).strip()
    local, _, domain = sender.lower().partition("@")
    if ATS_DOMAINS.search(domain):              # contoso@myworkday.com → the tenant is the employer
        return local.split(".")[0]
    labels = domain.split(".")                  # talent@talent.wallstreetoasis.example → wallstreetoasis
    return labels[-2] if len(labels) >= 2 else domain


TITLE = re.compile(r"(?:applying to the role of|position of|[Aa]pplication with [A-Z]\w+ \d{5,}|applying to the|apply for the role of|role of|interest in the|qualifications for the|"
                   r"Ref: \d+ -|application - )\s*(?:\d{5,}\s*-?\s*)?(.{6,100}?)(?:\s*-\s*\d{5,}|,\s*\d{5,}|\s+position\b| \(| at [A-Z]| with us|\. |\s+We |$)")


PLACEHOLDER = "(role from email)"


def title_from(text: str) -> str | None:
    m = TITLE.search(text)
    return m.group(1).strip(" .-–") if m else None


def pretty_company(hint: str, text: str) -> str:
    """'ag' + 'A&G Online Assessment' → 'A&G'; 'wideworldimporters' + '...Wide World Importers' → 'Wide World Importers'."""
    if not hint.islower():
        return hint
    words = re.findall(r"[A-Z][\w&]*", text)
    for n in range(4, 0, -1):
        for i in range(len(words) - n + 1):
            if norm("".join(words[i:i + n])) == norm(hint):
                return " ".join(words[i:i + n])
    return hint.title()


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def match_role(con, company: str, title: str | None, text: str):
    """The role this email is about: same company and (title in the email | the one title-less row | its only active row)."""
    c = norm(company)
    rows = [r for r in con.execute("select * from roles").fetchall()
            if c and (c in norm(r["company"]) or norm(r["company"]) in c)]
    t = norm(text)
    titled = [r for r in rows if len(norm(r["title"])) > 8 and (norm(r["title"]) in t or title and norm(title) == norm(r["title"]))]
    if titled:
        return titled[0]
    placeholder = [r for r in rows if r["title"] == PLACEHOLDER and r["status"] not in ("rejected", "skipped")]
    if placeholder:                            # an earlier email couldn't name the role; this one can
        if title:
            con.execute("update roles set title = ? where id = ?", (title, placeholder[0]["id"]))
        return placeholder[0]
    if title:                                  # the email names a role we don't have → it's a different role
        return None
    active = [r for r in rows if r["status"] not in ("new", "rejected", "skipped")]
    return active[0] if len(active) == 1 else None


def apply(con, msg: dict) -> str:
    """Process one email. Returns what happened, for the run log."""
    if con.execute("select 1 from events where mail_id = ?", (msg["id"],)).fetchone():
        return "seen"
    kind = classify(msg["from"], msg["subject"], msg.get("snippet", ""))
    if kind in (None, "alert"):
        return kind or "ignored"
    company = company_hint(msg["from"], msg["subject"])
    text = f"{msg['subject']} {msg.get('snippet', '')}"
    sent_to = re.search(r"application was sent to ([A-Z][\w&.' -]{1,40})", msg["subject"])   # LinkedIn Easy Apply
    if sent_to:
        company = sent_to.group(1).strip()
    title = title_from(msg["subject"]) or title_from(msg.get("snippet", ""))
    role = match_role(con, company, title, text)
    if role is None:   # applied outside the engine (or the finder never saw it): track it anyway
        title = title or PLACEHOLDER
        key = f"inbox:{norm(company)}:{norm(title)}"
        db.upsert_role(con, {"key": key, "company": pretty_company(company, text), "title": title, "source": "inbox"})
        role = con.execute("select * from roles where key = ?", (key,)).fetchone()
    new = STATUS_FOR[kind]
    if role["status"] != "rejected" and (new == "rejected" or RANK.get(new, 0) > RANK.get(role["status"], 0)):
        con.execute("update roles set status = ?, applied_on = coalesce(applied_on, ?) where id = ?",
                    (new, msg["date"][:10] if new == "submitted" else None, role["id"]))
    con.execute("insert into events (role_id, at, type, summary, mail_id) values (?, ?, ?, ?, ?)",
                (role["id"], msg["date"], kind, msg["subject"][:200], msg["id"]))
    return kind


def run(messages: list[dict]) -> dict:
    con = db.connect()
    counts: dict[str, int] = {}
    for m in sorted(messages, key=lambda m: m["date"]):       # oldest first, so status only moves forward
        k = apply(con, m)
        counts[k] = counts.get(k, 0) + 1
    con.commit()
    db.log_run(con, "listen", len(messages), sum(v for k, v in counts.items() if k in STATUS_FOR), [])
    return counts


def gmail_login() -> tuple[str, str]:
    """Env vars win (CI); otherwise read the OS credential store."""
    if os.environ.get("GMAIL_APP_PASSWORD"):
        return os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"]
    address, password = platform.get_secret()
    if not (address and password):
        raise SystemExit("No Gmail app password yet. Run: uv run python -m engine gmail")
    return address, password


def save_gmail_login() -> None:
    """Interactive: ask once, test the login, store it in the Keychain."""
    import getpass
    address = input("Gmail address: ").strip()
    print("Create an app password at https://myaccount.google.com/apppasswords (needs 2-Step Verification).")
    pw = getpass.getpass("App password (16 letters, spaces ok): ").replace(" ", "")
    box = imaplib.IMAP4_SSL("imap.gmail.com")
    box.login(address, pw)                                     # fails loudly here, before anything is saved
    box.logout()
    platform.set_secret(address, pw)
    print("Saved to your OS credential store. The listener can read your inbox now (read-only).")


def sent_at(header: str | None, meta: bytes = b"") -> str:
    """The Date header; missing or malformed (some mailers) → when Gmail received it."""
    try:
        return email.utils.parsedate_to_datetime(header).isoformat()
    except (TypeError, ValueError):
        t = imaplib.Internaldate2tuple(meta)
        return (datetime(*t[:6]) if t else datetime.now()).isoformat()


def fetch_imap(days: int = 14) -> list[dict]:
    """ponytail: plain IMAP over SSL with an app password; Gmail OAuth only if app passwords go away."""
    address, password = gmail_login()
    box = imaplib.IMAP4_SSL("imap.gmail.com")
    box.login(address, password)
    box.select("INBOX", readonly=True)                         # read-only: the listener never changes mail
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    _, ids = box.search(None, f'(SINCE "{since}")')
    out = []
    for i in ids[0].split():
        _, data = box.fetch(i, "(INTERNALDATE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.600>)")
        try:
            hdr = email.message_from_bytes(data[0][1])
            dec = lambda v: str(email.header.make_header(email.header.decode_header(v or "")))
            out.append({"id": hdr["Message-ID"] or i.decode(), "from": email.utils.parseaddr(hdr["From"])[1],
                        "subject": dec(hdr["Subject"]), "snippet": data[1][1].decode(errors="replace") if len(data) > 1 else "",
                        "date": sent_at(hdr["Date"], data[0][0])})
        except Exception as e:                                 # one odd message never stops the inbox read
            print(f"skipped message {i.decode()}: {type(e).__name__}", file=sys.stderr)
    box.logout()
    return out


def _selfcheck() -> None:
    assert sent_at("Wed, 21 Oct 2026 09:30:00 -0400").startswith("2026-10-21T09:30")
    assert sent_at(None, b'1 (INTERNALDATE "21-Oct-2026 09:30:00 +0000" BODY[HEADER] {10}').startswith("2026-10-21")
    assert sent_at("garbage", b"")                                       # no date anywhere: still a value, no crash
    c = lambda s, sub, sn="": classify(s, sub, sn)
    assert c("contoso@myworkday.com", "Contoso job application: Progress update", "We regret to inform you") == "rejection"
    assert c("donotreply@northwind.example", "Thank you for applying to Northwind!") == "confirmation"
    assert c("talent@fabrikam.example", "Action Required:Fabrikam Assessments for completion") == "assessment"
    assert c("talent@fabrikam.example", "Your Fabrikam Application Status", "invited to complete Fabrikam's recorded interview") == "assessment"
    assert c("noreply@jobright.ai", "SAP just posted a 82% match") == "alert"
    assert c("x@y.example", "The Morning: Paper towns") is None
    assert c("p@talent.wideworldimporters.example", "Application Update", "we weren't able to offer you a spot") == "rejection"
    assert title_from("Thank you for submitting an application for the position of Internal Services - Co-Op Intern - "
                      "Finance Strategy & Transformation - Winter 2027, 364303.") == \
        "Internal Services - Co-Op Intern - Finance Strategy & Transformation - Winter 2027"
    assert title_from("Ref: 128644 - Strategy Consultant Intern 2027 We regret to inform you") == "Strategy Consultant Intern 2027"
    assert title_from("Thank you for applying to the role of Strategy Consultant Intern 2027 - 128644 at Fabrikam.") == "Strategy Consultant Intern 2027"
    assert title_from("Your Application with Tailspin 2602661 Campus Digital Technology Center Intern - Summer 2027") == \
        "Campus Digital Technology Center Intern - Summer 2027"
    assert pretty_company("ag", "ACTION NEEDED – A&G Online Assessment") == "A&G"
    assert pretty_company("wideworldimporters", "the WWI Analyst Internship at Wide World Importers") == "Wide World Importers"
    assert company_hint("contoso@myworkday.com", "Contoso job application: Progress update") == "Contoso"
    assert company_hint("adatum@myworkday.com", "Application Received") == "adatum"
    assert company_hint("tailspinfinancial@myworkday.com", "Your Application with Tailspin") == "Tailspin"
    assert company_hint("no-reply@greenhouse-mail.io", "Thank you for applying to Acme Solutions!") == "Acme Solutions"
    assert company_hint("abbank@myworkday.com", "A&B Bank Application") == "A&B Bank"
    assert company_hint("talentacquisition.people_organization@litware.example", "An update on your recent Litware application") == "litware"
    assert company_hint("agcareers.im@ag.example", "ACTION NEEDED – A&G Online Assessment") == "ag"


if __name__ == "__main__":
    _selfcheck()
    print("ok")
