"""Local tracker: one SQLite file in data/, never committed.

roles is the spine; history lives in events so status stays one field.
"""
import json
import os
import sqlite3
import time
from pathlib import Path

# INTERNSHIP_ENGINE_DATA lets the shared-feed job build in a scratch folder, away from anyone's personal data
DATA = Path(os.environ.get("INTERNSHIP_ENGINE_DATA") or Path(__file__).resolve().parent.parent / "data")
SCHEMA = """
create table if not exists roles (
  id integer primary key,
  key text unique not null,              -- dedupe: canonical url, else company|title|location
  company text not null, title text not null, location text, work_model text,
  url text, source text, ats text, track text,
  fit integer, fit_why text,
  found_on text not null, posted text,
  status text not null default 'new',    -- new·queued·submitted·assessment·interview·offer·rejected·skipped·blocked
  blocked_reason text, applied_on text, applied_by text, next_action text, notes text
);
create table if not exists events (
  id integer primary key, role_id integer references roles(id),
  at text not null, type text not null,  -- confirmation·assessment·interview·rejection·reply·note
  summary text, mail_id text unique      -- mail_id makes the listener idempotent
);
create table if not exists runs (
  id integer primary key, job text, started text, found integer, new integer, errors text
);
create table if not exists contacts (
  id integer primary key, name text not null, company text, title text, url text, email text,
  status text not null default 'to_message',  -- to_message · messaged · replied · met · not_now
  next_on text, notes text, source text, unique(name, company)
);
create table if not exists companies (
  name text primary key, careers_url text, ats text, board text   -- board = token / workday {t,wd,site} json
);
"""
# columns added after Phase 1; connect() adds any that an older data/engine.db is missing
MIGRATIONS = {
    "roles": {"description": "text", "homepage": "text", "eligible": "integer", "eligible_why": "text",
              "checked_on": "text",
              "warm": "text", "outreach": "text", "resolved": "text", "resume_variant": "text", "pay": "text", "keywords": "text"},
    "companies": {"homepage": "text", "checked_on": "text"},
}
STATUSES = ["new", "queued", "submitted", "assessment", "interview", "offer", "rejected", "skipped", "blocked", "ghosted"]


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DATA / "engine.db"
    path.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in db.execute(f"pragma table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                db.execute(f"alter table {table} add column {col} {typ}")
    return db


def today() -> str:
    return time.strftime("%Y-%m-%d")


def upsert_role(db: sqlite3.Connection, r: dict) -> bool:
    """Insert a role if its key is new. Returns True when it was new. Never overwrites status."""
    cur = db.execute(
        """insert or ignore into roles (key, company, title, location, work_model, url, source, ats, track, found_on, posted, homepage, description)
           values (:key, :company, :title, :location, :work_model, :url, :source, :ats, :track, :found_on, :posted, :homepage, :description)""",
        {"location": None, "work_model": None, "url": None, "ats": None, "track": None, "posted": None, "homepage": None, "description": None,
         "found_on": today(), **r})
    return cur.rowcount == 1


def log_run(db: sqlite3.Connection, job: str, found: int, new: int, errors: list[str]) -> None:
    db.execute("insert into runs (job, started, found, new, errors) values (?, datetime('now'), ?, ?, ?)",
               (job, found, new, json.dumps(errors) if errors else None))
    db.commit()
