"""The shared side: a public directory of job boards, and a daily feed of postings built from it.

Only public facts go here (company, title, location, posting URL). Never anything from data/.

    uv run python -m engine boards        # your learned boards → boards.json (commit it to share them)
    uv run python -m engine feed-build    # boards.json + companies.json → site/feed.json (GitHub runs this daily)
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from . import ats, db, feed, finder, insight

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "boards.json"
FEED_OUT = ROOT / "site" / "feed.json"
FEED_URL = "https://omar-colab.github.io/internship-engine/feed.json"
FRESH_HOURS = 36
ENRICHMENT_BUDGET = 12 * 60
ENRICHMENT_FIELDS = ("skills", "pay", "auth", "years", "summary")
ENRICHMENT_VERSION = 3          # bump when a parser changes: every role is re-enriched once instead of carrying old values


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


def _carried(d: dict) -> dict[str, dict]:
    """Previous roles by url; enrichment from an older parser version is dropped so it gets redone."""
    roles = d.get("roles") if isinstance(d, dict) else None
    if not isinstance(roles, list):
        return {}
    stale = d.get("enrichment_version") != ENRICHMENT_VERSION
    return {r["url"]: {k: v for k, v in r.items() if not (stale and k in ENRICHMENT_FIELDS)}
            for r in roles if isinstance(r, dict) and isinstance(r.get("url"), str)}


def _previous_feed() -> dict[str, dict] | None:
    try:
        response = httpx.get(FEED_URL, timeout=20)
        response.raise_for_status()
        d = response.json()
        return _carried(d)
    except Exception:
        return None


def _auth_flags(description: str) -> list[str]:
    text = description or ""
    flags = []
    # citizen: US citizens only (clearance work). us_person: citizen OR permanent resident (export control/ITAR).
    for m in re.finditer(r"\b(?:u\.?s\.?\s+)?citizenship\b[^.\n]{0,80}?\brequired\b(?!:?\s*no\b)|\b(?:requires?|requiring) (?:u\.?s\.? )?citizenship\b|\bmust be (?:a )?(?:u\.?s\.? )?citizen\b|\bsecurity clearance (?:is )?required\b|\b(?:obtain|maintain|hold|possess)\b[^\n]{0,40}?\bsecurity clearance\b|\bu\.?s\.? persons?\b", text, re.I):
        window = text[max(0, m.start() - 150): m.end() + 150]
        if re.search(r"permanent resident|green card|lawful permanent|\bu\.?s\.? persons?\b|refugee|asylee|\bor be an?\b", window, re.I) \
                and not re.search(r"clearance", m.group(0), re.I):
            flags.append("us_person")
        else:
            flags.append("citizen")
        break
    no_sponsor = re.search(r"\b(?:will not|cannot|can't|does not|do not|unable to|not able to) sponsor\b|\bno (?:visa )?sponsorship (?:is )?available\b|\b(?:visa )?sponsorship (?:is )?not available\b|(?<!with or )\bwithout (?:the need for )?(?:(?:employer|visa) )?sponsorship\b|\bmust be authorized to work without sponsorship\b|\b(?:does|do|will) not (?:provide|offer) (?:visa )?sponsorship\b|\bwill not require sponsorship\b", text, re.I)
    if no_sponsor:
        flags.append("no_sponsor")
    elif re.search(r"\b(?:visa )?sponsorship (?:is )?(?:available|offered)\b|\b(?:offers?|provides?) (?:visa )?sponsorship\b|\bwill sponsor (?:a )?(?:work )?visa\b", text, re.I):
        flags.append("sponsor")
    return flags


def _graduation_years(description: str) -> list[int]:
    """Class years a posting accepts. 'December 2027 or later' / 'after August 2027' accept every later year too."""
    years = set()
    # "graduate degree/student/program" names a level of study, not a graduation date.
    for cue in re.finditer(r"\b(?:graduat(?!e (?:degree|student|program|school|level|studies|intern|position|role))\w*|class\s+of)\b", description or "", re.I):
        nearby = re.split(r"[.!?\n]", (description or "")[cue.end():cue.end() + 90], maxsplit=1)[0]
        found = list(map(int, re.findall(r"\b20\d{2}\b", nearby)))
        if found and re.search(r"\b(?:after|or later|and later|or beyond|or after|onwards?|no earlier than)\b", nearby, re.I):
            found += range(max(found) + 1, max(found) + 5)
        elif len(found) == 2 and re.search(r"\d{4}\s*(?:-|–|—|to|through)\s*\w*\s*\d{0,2},?\s*20\d{2}|between", nearby, re.I):
            found += range(min(found) + 1, max(found))     # "Dec 2027 – July 2029" includes 2028
        years.update(found)
    return sorted(years)


def _summary(description: str) -> str:
    return " ".join((description or "").split())[:280]


def _enrichment(description: str | None) -> dict:
    text = description or ""
    return {"skills": insight.keywords(text, "")["asked"], "pay": insight.pay(text),
            "auth": _auth_flags(text), "years": _graduation_years(text), "summary": _summary(text)}


def build_feed(previous: dict[str, dict] | None) -> dict:
    """Poll every shared board for intern roles (US + remote). Runs in CI with no personal data around."""
    roles, covered, errors = [], [], []
    seen = set()
    today = datetime.now(timezone.utc).date().isoformat()
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
                old = previous.get(r["url"], {}) if previous is not None else {}
                roles.append({k: r.get(k) for k in ("company", "title", "location", "url", "ats", "posted")} |
                             {"track": feed.track(r["title"]), "first_seen": old.get("first_seen", today) if previous is not None else None} |
                             {k: old[k] for k in ENRICHMENT_FIELDS if k in old})
            covered.append(c["name"])
        except Exception as e:
            errors.append(f"{c['name']}: {type(e).__name__}")
        time.sleep(0.3)                                  # be polite to the boards
    # Descriptions only for roles not enriched before. A failed or unfinished fetch adds nothing, so tomorrow retries it.
    pending = [r for r in roles if any(k not in r for k in ENRICHMENT_FIELDS)]
    pool = ThreadPoolExecutor(max_workers=8)
    futures = {pool.submit(ats.description, r["url"]): r for r in pending}
    try:
        for future in as_completed(futures, timeout=ENRICHMENT_BUDGET):
            if not future.exception() and future.result():
                futures[future].update(_enrichment(future.result()))
    except TimeoutError:
        pass
    pool.shutdown(wait=False, cancel_futures=True)
    FEED_OUT.parent.mkdir(exist_ok=True)
    FEED_OUT.write_text(json.dumps({"built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "enrichment_version": ENRICHMENT_VERSION,
                                    "boards": len(sources), "covered": covered, "roles": roles, "errors": errors}))
    return {"roles": len(roles), "boards": len(sources), "covered": len(covered), "errors": len(errors)}


def _first_seen_by_url(d: object) -> dict[str, str]:
    roles = d.get("roles") if isinstance(d, dict) else None
    if not isinstance(roles, list):
        return {}
    # A known-unknown date (None, after a failed fetch) stays unknown, so it never turns into a burst of "new".
    return {r["url"]: r.get("first_seen") if isinstance(r.get("first_seen"), str) else None for r in roles
            if isinstance(r, dict) and isinstance(r.get("url"), str) and r["url"]}


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
    import sys
    import tempfile
    from unittest.mock import patch

    sample = {"company": "Contoso", "title": "Data Intern", "location": "Remote", "url": "https://x", "ats": "greenhouse", "posted": None,
              "description": "secret", "fit": 5}
    out = {k: sample.get(k) for k in ("company", "title", "location", "url", "ats", "posted")}
    assert "fit" not in out and "description" not in out
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    document = {"built": (now - timedelta(hours=1)).isoformat(), "roles": [out], "covered": ["Contoso"]}
    assert _fresh_feed(document, now) == {"roles": [out], "covered": ["Contoso"]}
    assert _first_seen_by_url({"roles": [{"url": "https://contoso.example/jobs/1", "first_seen": "2026-10-21"},
                                         {"url": "https://northwind.example/jobs/2"}]}) == {
        "https://contoso.example/jobs/1": "2026-10-21", "https://northwind.example/jobs/2": None}
    assert _first_seen_by_url({"roles": "invalid"}) == {}
    fictional = "Contoso requires U.S. citizenship. No visa sponsorship is available. Graduating in 2027 or 2028. Use SQL. $20/hr - $30/hr."
    assert _auth_flags(fictional) == ["citizen", "no_sponsor"]
    assert _auth_flags("Employees must be a U.S. citizen, lawful U.S. permanent resident (i.e., green card holder).") == ["us_person"]
    assert _auth_flags("U.S. Citizenship, Lawful Permanent Residency, or Refugee/Asylee Status Required.") == ["us_person"]
    assert _auth_flags("US Citizenship Required: No. Job description follows.") == []
    assert _auth_flags("This position requires the ability to obtain and maintain a U.S. Government security clearance.") == ["citizen"]
    assert _auth_flags("Northwind offers visa sponsorship.") == ["sponsor"]
    assert _auth_flags("Fabrikam does not provide visa sponsorship.") == ["no_sponsor"]
    assert _auth_flags("Fabrikam may sponsor some roles.") == []
    assert _auth_flags("You must be a U.S. citizen or permanent resident.") == ["us_person"]
    assert _auth_flags("Authorized to work in the US with or without sponsorship.") == []
    assert _auth_flags("Must be authorized to work without sponsorship.") == ["no_sponsor"]
    assert _graduation_years("Graduating in 2027 or 2028; class of 2029.") == [2027, 2028, 2029]
    assert _graduation_years("Role posted in 2027; no graduation details.") == []
    assert _graduation_years("Expected graduation date of December 2027 or later.") == [2027, 2028, 2029, 2030, 2031]
    assert _graduation_years("Graduating after August 2027.") == [2027, 2028, 2029, 2030, 2031]
    assert _graduation_years("Graduating in Dec 2027 – July 2029 (U.S.)") == [2027, 2028, 2029]
    assert _graduation_years("Graduation date no earlier than December 2026.") == [2026, 2027, 2028, 2029, 2030]
    assert _graduation_years("Graduation date: 2026 or 2027") == [2026, 2027]
    old = {"roles": [{"url": "https://contoso.example/1", "first_seen": "2026-10-20", "years": [2027]}]}
    assert _carried(old)["https://contoso.example/1"] == {"url": "https://contoso.example/1", "first_seen": "2026-10-20"}
    assert _carried({**old, "enrichment_version": ENRICHMENT_VERSION})["https://contoso.example/1"]["years"] == [2027]
    assert _graduation_years("Enrolled in a graduate degree program, returning to school in Fall 2027.") == []
    assert _summary("  Contoso\n  data  intern ") == "Contoso data intern"
    assert _enrichment(fictional) == {"skills": ["sql"], "pay": "$20–30/hr", "auth": ["citizen", "no_sponsor"],
                                      "years": [2027, 2028], "summary": fictional}
    assert _fresh_feed({**document, "built": (now - timedelta(hours=FRESH_HOURS + 1)).isoformat()}, now) is None
    assert _fresh_feed({**document, "built": (now + timedelta(minutes=1)).isoformat()}, now) is None
    assert _fresh_feed({k: v for k, v in document.items() if k != "covered"}, now) is None
    with patch.object(httpx, "get", side_effect=httpx.ConnectError("offline")):
        assert pull_feed() is None

    with tempfile.TemporaryDirectory() as directory:
        seed = Path(directory) / "seed.json"
        seed.write_text('{"companies": []}')
        output = Path(directory) / "feed.json"
        listing = {"company": "Contoso", "title": "Data Intern", "location": "Remote",
                   "url": "https://contoso.example/jobs/1", "ats": "greenhouse", "posted": None}
        with (patch.object(httpx, "get", side_effect=httpx.ConnectError("offline")),
              patch.object(finder, "SEED", seed), patch.object(finder, "in_us", return_value=True),
              patch.object(ats, "LIST", {"greenhouse": lambda *_: [listing]}),
              patch.object(ats, "description", return_value="Use SQL. Graduating in 2028."),
              patch.object(sys.modules[__name__], "FEED_OUT", output),
              patch.object(time, "sleep"), patch(__name__ + ".load_boards", return_value=[{"name": "Contoso", "ats": "greenhouse"}])):
            assert _previous_feed() is None
            build_feed(None)
            result = json.loads(output.read_text())["roles"][0]
            assert result["first_seen"] is None and result["skills"] == ["sql"] and result["years"] == [2028]

        with (patch.object(finder, "SEED", seed), patch.object(finder, "in_us", return_value=True),
              patch.object(ats, "LIST", {"greenhouse": lambda *_: [listing]}),
              patch.object(ats, "description", side_effect=AssertionError("cached enrichment must not fetch")),
              patch.object(sys.modules[__name__], "FEED_OUT", output), patch.object(time, "sleep"),
              patch(__name__ + ".load_boards", return_value=[{"name": "Contoso", "ats": "greenhouse"}])):
            cached = {**result, "first_seen": "2026-10-21"}
            build_feed({listing["url"]: cached})
            assert json.loads(output.read_text())["roles"][0]["summary"] == result["summary"]

    class FailedResponse:
        def raise_for_status(self):
            raise httpx.HTTPError("bad status")

    with patch.object(httpx, "get", return_value=FailedResponse()):
        assert pull_feed() is None
    print("ok")
