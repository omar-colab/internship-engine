"""The shared side: a public directory of job boards, and a daily feed of postings built from it.

Only public facts go here (company, title, location, posting URL). Never anything from data/.

    uv run python -m engine boards        # your learned boards → boards.json (commit it to share them)
    uv run python -m engine feed-build    # boards.json + companies.json → site/feed.json (GitHub runs this daily)
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from . import ats, db, feed, finder

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "boards.json"
FEED_OUT = ROOT / "site" / "feed.json"
FEED_URL = "https://omar-colab.github.io/internship-engine/feed.json"
FRESH_HOURS = 36


def load_boards() -> list[dict]:
    return json.loads(BOARDS.read_text())["boards"] if BOARDS.exists() else []


def export_boards() -> dict:
    """Merge the boards your resolver found into boards.json. Public data only: company name → board."""
    con = db.connect()
    known = {b["name"]: b for b in load_boards()}
    for r in con.execute("select name, ats, board from companies where ats is not null and board is not null"):
        known[r["name"]] = {"name": r["name"], "ats": r["ats"], **json.loads(r["board"])}
    boards = sorted(known.values(), key=lambda b: b["name"].lower())
    BOARDS.write_text(json.dumps({"_note": "Company → job board, found by the resolver. Shared so every engine starts with them.",
                                  "boards": boards}, indent=1) + "\n")
    return {"boards": len(boards)}


def build_feed() -> dict:
    """Poll every shared board for intern roles (US + remote). Runs in CI with no personal data around."""
    roles, covered, errors = [], [], []
    seen = set()
    sources = [{"name": b["name"], "board": {k: v for k, v in b.items() if k != "name"}} for b in load_boards()]
    sources += [c for c in json.loads(finder.SEED.read_text())["companies"] if "board" in c]
    for c in sources:
        try:
            b = dict(c["board"])
            kind = b.pop("ats")
            for r in ats.LIST[kind](c["name"], b):
                if r["url"] in seen or not finder.in_us(r["location"]):
                    continue
                seen.add(r["url"])
                roles.append({k: r.get(k) for k in ("company", "title", "location", "url", "ats", "posted")} | {"track": feed.track(r["title"])})
            covered.append(c["name"])
        except Exception as e:
            errors.append(f"{c['name']}: {type(e).__name__}")
        time.sleep(0.3)                                  # be polite to the boards
    FEED_OUT.parent.mkdir(exist_ok=True)
    FEED_OUT.write_text(json.dumps({"built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "boards": len(sources), "covered": covered, "roles": roles, "errors": errors}))
    return {"roles": len(roles), "boards": len(sources), "covered": len(covered), "errors": len(errors)}


def _fresh_feed(d: object, now: datetime | None = None) -> dict | None:
    if not isinstance(d, dict):
        return None
    try:
        built = datetime.fromisoformat(d["built"])
    except (KeyError, TypeError, ValueError):
        return None
    if built.tzinfo is None:
        return None
    age = (now or datetime.now(timezone.utc)) - built.astimezone(timezone.utc)
    if age < timedelta(0) or age > timedelta(hours=FRESH_HOURS):
        return None
    roles, covered = d.get("roles"), d.get("covered")
    if not isinstance(roles, list) or not isinstance(covered, list):
        return None
    required = ("company", "title", "url", "ats")
    if any(
        not isinstance(r, dict) or any(not isinstance(r.get(k), str) or not r[k] for k in required)
        for r in roles
    ):
        return None
    if any(not isinstance(name, str) or not name for name in covered):
        return None
    return {"roles": roles, "covered": covered}


def pull_feed() -> dict | None:
    """Today's shared feed, or None if it's missing or stale (then the finder polls the boards itself)."""
    try:
        response = httpx.get(FEED_URL, timeout=20)
        response.raise_for_status()
        return _fresh_feed(response.json())
    except Exception:
        return None


if __name__ == "__main__":
    # self-check: shared feeds are public-only, fresh, and usable only with complete board coverage.
    from unittest.mock import patch

    sample = {"company": "Contoso", "title": "Data Intern", "location": "Remote", "url": "https://x", "ats": "greenhouse", "posted": None,
              "description": "secret", "fit": 5}
    out = {k: sample.get(k) for k in ("company", "title", "location", "url", "ats", "posted")}
    assert "fit" not in out and "description" not in out
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    document = {"built": (now - timedelta(hours=1)).isoformat(), "roles": [out], "covered": ["Contoso"]}
    assert _fresh_feed(document, now) == {"roles": [out], "covered": ["Contoso"]}
    assert _fresh_feed({**document, "built": (now - timedelta(hours=FRESH_HOURS + 1)).isoformat()}, now) is None
    assert _fresh_feed({**document, "built": (now + timedelta(minutes=1)).isoformat()}, now) is None
    assert _fresh_feed({k: v for k, v in document.items() if k != "covered"}, now) is None
    with patch.object(httpx, "get", side_effect=httpx.ConnectError("offline")):
        assert pull_feed() is None

    class FailedResponse:
        def raise_for_status(self):
            raise httpx.HTTPError("bad status")

    with patch.object(httpx, "get", return_value=FailedResponse()):
        assert pull_feed() is None
    print("ok")
