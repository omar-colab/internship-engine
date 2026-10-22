"""Enrich + score: fetch each posting's description, then decide two things about it.

  eligible  hard gates read from the posting: degree level, graduation window, class year, past seasons.
            0 = you can't apply (hidden), 1 = you can, 2 = you can but check something (shown with the note)
  fit       1–5 against data/profile.json, with the reasons in one line. Under 3 is hidden by default.

Every rule is a plain pattern on the posting text, so a "why" can always point at the words it read.

    uv run python -m engine score
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import ats, db, feed, insight

PROFILE = db.DATA / "profile.json"
EXAMPLE = Path(__file__).resolve().parent.parent / "profile.example.json"

# Fields that need training the profile doesn't claim. Matched on the TITLE: a finance intern posting that
# says "work with engineering" is still a finance internship.
OFF_FIELD = re.compile(r"\b(mechanical|electrical|civil|chemical|aerospace|manufacturing|hardware|firmware|embedded|"
                       r"structural|process engineer|quality (assurance )?(intern|engineer)|software (engineer|developer)|"
                       r"\bsde\b|biostatist|epidemiolog|chemist|biolog|clinical|nurs|pharma(cy|cist)|legal|paralegal|law clerk|"
                       r"tax|audit|assurance|actuar|geospatial|gis\b|cad\b|electro|optic|research assistant|teacher|"
                       r"warehouse|driver|technician|welder|machinist|lab\b|underwrit|sales desk|valuation|unclaimed property|"
                       r"talent management|human resources|\bhr\b|recruit|marketing|communications|radar|systems engineer|"
                       r"engineer(ing)? intern|data scien|accounting|architecture|receiver|antenna|rf\b)", re.I)


def desc_track(desc: str) -> str | None:
    d = desc.lower()
    best = max(DESC_TRACK, key=lambda k: len(set(re.findall(DESC_TRACK[k], d))))
    return best if len(set(re.findall(DESC_TRACK[best], d))) >= 2 else None
# A description only counts toward a track with 2+ of these distinct signals: one stray "data" proves nothing.
DESC_TRACK = {
    "ai-consulting": r"generative ai|gen ?ai|\bllms?\b|large language|ai (adoption|strategy|transformation|solutions|use cases)|copilot|machine learning|agentic",
    "transformation": r"digital transformation|process (improvement|automation|redesign)|change management|operating model|automation|lean six sigma",
    "data-analytics": r"\bsql\b|tableau|power bi|dashboards?|data visuali[sz]ation|business intelligence|\bpython\b|data analysis",
}
CORE = {"ai", "automation", "agent", "llm", "generative ai", "claude", "prompt", "python", "sql", "tableau", "financial model",
        "dashboard", "data visualization", "data cleaning", "consulting", "market sizing", "due diligence", "business intelligence",
        "analytics", "swift", "ios", "google ads"}
TITLE_FIELD = re.compile(r"consult|business|analyt|strategy|product|data|\bai\b|digital|transformation|operations", re.I)
GRAD_WINDOW = re.compile(r"graduat\w*[^.]{0,80}?\b(?:between|from)\s+(?:\w+\s+)?(20\d\d)\s+(?:and|to|through|-|–)\s+(?:\w+\s+)?(20\d\d)", re.I)
GRAD_YEAR = re.compile(r"(?:graduat\w*|class of|expected (?:graduation|to graduate))[^.]{0,60}?\b(20\d\d)\b", re.I)
GRAD_NEAR = re.compile(r"graduat\w*|class of|expected to graduate", re.I)
SEASON = re.compile(r"\b(?:(summer|fall|spring|winter)\s*(20\d\d)|(20\d\d)\s*(summer|fall|spring|winter))\b", re.I)


def load_profile() -> dict:
    return json.loads((PROFILE if PROFILE.exists() else EXAMPLE).read_text())


def eligibility(title: str, desc: str, p: dict) -> tuple[int, str | None]:
    t, d = title.lower(), (desc or "").lower()
    grad = int(p["graduation"][:4])
    if p["degree_level"] == "bachelors":
        if re.search(r"\b(mba|ph\.?d|pharm\.?d|doctoral|master'?s|graduate (student )?intern|law student|jd\b|md\b)", t):
            return 0, "Graduate-level role"
        if re.search(r"(currently (enrolled|pursuing) (in )?(an? )?(mba|ph\.?d|master'?s|graduate|doctoral))", d) and \
                not re.search(r"bachelor|undergraduate", d):
            return 0, "Asks for a graduate degree in progress"
    for m in SEASON.finditer(title):
        season, year = (m[1] or m[4]).title(), int(m[2] or m[3])
        if year < grad - 1:                            # Summer 2026 posted for someone graduating 2028
            return 0, f"{season} {year} has already happened"
    if m := GRAD_WINDOW.search(d):
        lo, hi = int(m[1]), int(m[2])
        if not lo <= grad <= hi:
            return 0, f"Graduation window {lo}–{hi}; you graduate {grad}"
    elif years := {int(y) for m in GRAD_NEAR.finditer(d) for y in re.findall(r"\b(20\d\d)\b", d[m.end():m.end() + 90])
                   if 2025 <= int(y) <= 2032}:                  # "graduation date in 2027 or 2028" → both years
        if grad not in years and grad + 1 not in years and len(years) == 1:
            return 0, f"Asks for class of {years.pop()}; you graduate {grad}"
    standing = p.get("class_standing", "")
    if re.search(r"\b(freshm[ae]n|sophomores?|first[- ]year|second[- ]year)\b[^.]{0,40}\b(only|program|students)\b", d) and \
            not re.search(r"junior|rising senior|third[- ]year", d) and standing in ("junior", "senior"):
        return 0, "For first- and second-year students"
    if re.search(r"\b(co-?op)\b", t) and "co-op" not in " ".join(p.get("open_to", [])).lower():
        return 2, "Co-op: usually a semester away from classes"
    if re.search(r"(u\.?s\.? citizen(ship)? (is )?required|must be a u\.?s\.? citizen|security clearance|secret clearance)", d) \
            and p.get("work_authorization") in (None, "unknown"):
        return 2, "Needs US citizenship or a clearance; set work_authorization in your profile"
    return 1, None


def fit(role: dict, p: dict) -> tuple[int, str]:
    title, desc = role["title"], role.get("description") or ""
    text = f"{title}\n{desc}".lower()
    off = OFF_FIELD.search(title)
    if off and not (TITLE_FIELD.search(title) and not re.search(r"scien|underwrit|valuation|marketing|recruit|sales|radar|pharm|nurs|clinical|legal|tax|audit|accounting|actuar", off[0], re.I)):
        return 1, f"Different field ({off[0].strip()})"
    why, score = [], 1.5
    names = {"ai-consulting": "AI consulting", "transformation": "transformation/strategy", "data-analytics": "analytics"}
    if (t := feed.track(title)) in p["tracks"]:
        score += 1.5
        why.append(names[t] + " role")
    elif (t := desc_track(desc)) in p["tracks"]:
        score += 0.6
        why.append(names[t] + " work")
    hits = [s for s in p["strengths"] if re.search(rf"\b{re.escape(s)}\b", text)]
    core = [h for h in hits if h in CORE]
    score += min(len(core), 5) * 0.35 + min(len(hits) - len(core), 4) * 0.1
    if core:
        why.append("asks for " + ", ".join(core[:4]))
    if TITLE_FIELD.search(title):
        score += 0.4
    must = sorted(set(re.findall(r"\b(java|c\+\+|c#|matlab|solidworks|autocad|cpa|series 7|nursing)\b", text)))
    if must:
        score -= 0.5 * len(must)
        why.append("wants " + ", ".join(must[:3]))
    loc = role.get("location") or ""
    if any(re.search(rf"\b{re.escape(l)}\b", loc, re.I) for l in p["locations"]):
        score += 0.3
        why.append("remote" if "remote" in loc.lower() else "in your area")
    if not desc:
        why.append("title only, no description yet")
    return max(1, min(5, round(score))), "; ".join(why) or "little overlap with your profile"


def _describe(row: dict) -> tuple[int, str | None]:
    try:
        return row["id"], ats.description(row["url"])
    except Exception:
        return row["id"], None


def resume_text(p: dict) -> str:
    f = db.DATA.parent / p.get("resume", "data/resume.txt") if not str(p.get("resume", "")).startswith("/") else Path(p["resume"])
    f = f if f.exists() else db.DATA / "resume.txt"
    return f.read_text() if f.exists() else ""


def score_one(con, role_id: int, p: dict | None = None) -> dict:
    """Score a single role now (the extension saves a job and wants its fit right away)."""
    p = p or load_profile()
    r = dict(con.execute("select * from roles where id = ?", (role_id,)).fetchone())
    e, ewhy = eligibility(r["title"], r["description"] or "", p)
    f, fwhy = fit(r, p)
    track = feed.track(r["title"]) or desc_track(r["description"] or "")
    kw = insight.keywords(r["description"] or "", resume_text(p))
    con.execute("update roles set eligible = ?, eligible_why = ?, fit = ?, fit_why = ?, track = coalesce(?, track), pay = ?, keywords = ? where id = ?",
                (e, ewhy, f, fwhy, track, insight.pay(r["description"]), json.dumps(kw), role_id))
    return {**r, "eligible": e, "eligible_why": ewhy, "fit": f, "fit_why": fwhy, "track": track, "pay": insight.pay(r["description"]), "keywords": kw}


def run(refetch: bool = False) -> dict:
    con = db.connect()
    p = load_profile()
    todo = [dict(r) for r in con.execute(
        "select id, url from roles where url is not null and status = 'new'" + ("" if refetch else " and description is null"))]
    fetched = 0
    with ThreadPoolExecutor(8) as pool:
        for rid, desc in pool.map(_describe, todo):
            if desc:
                con.execute("update roles set description = ? where id = ?", (desc[:20000], rid))
                fetched += 1
    scored = 0
    resume = resume_text(p)
    for r in [dict(r) for r in con.execute("select * from roles where status in ('new', 'queued')")]:
        e, ewhy = eligibility(r["title"], r["description"] or "", p)
        f, fwhy = fit(r, p)
        track = feed.track(r["title"]) or desc_track(r["description"] or "")
        con.execute("update roles set eligible = ?, eligible_why = ?, fit = ?, fit_why = ?, track = coalesce(?, track), pay = ?, keywords = ? where id = ?",
                    (e, ewhy, f, fwhy, track, insight.pay(r["description"]), json.dumps(insight.keywords(r["description"] or "", resume)), r["id"]))
        scored += 1
    con.commit()
    db.log_run(con, "score", scored, fetched, [])
    return {"descriptions": fetched, "scored": scored}


def _selfcheck() -> None:
    p = {"graduation": "2028-05", "degree_level": "bachelors", "class_standing": "junior", "open_to": [],
         "work_authorization": "unknown", "tracks": ["ai-consulting", "transformation", "data-analytics"],
         "strengths": ["python", "sql", "tableau", "consulting", "ai"], "locations": ["CT", "NY", "Remote"]}
    assert eligibility("MBA Summer Associate", "", p)[0] == 0
    assert eligibility("Summer 2026 Analyst Intern", "", p) == (0, "Summer 2026 has already happened")
    assert eligibility("Analyst Intern", "Candidates graduating between December 2026 and June 2027.", p)[0] == 0
    assert eligibility("Analyst Intern", "Must be graduating between December 2027 and June 2028.", p)[0] == 1
    assert eligibility("Analyst Intern", "Open to sophomores only through our discovery program.", p)[0] == 0
    assert eligibility("Data Co-Op - Spring 2027", "", p)[0] == 2
    assert eligibility("Analyst Intern", "You must be a U.S. citizen to be considered.", p)[0] == 2
    assert eligibility("Summer 2027 Consulting Intern", "Rising seniors (class of 2028).", p) == (1, None)
    assert eligibility("AI Intern", "Must have an expected graduation date in 2027 or 2028 .", p) == (1, None)
    assert eligibility("AI Intern", "Must have an expected graduation date in 2027.", p)[0] == 0
    good = fit({"title": "AI Strategy Consulting Intern", "location": "Stamford, CT",
                "description": "Use Python, SQL and Tableau to help clients adopt AI."}, p)
    assert good[0] >= 4, good
    assert fit({"title": "Mechanical Engineering Intern", "location": "CT", "description": "python"}, p)[0] == 1
    assert fit({"title": "Marketing Intern", "location": "TX", "description": "Requires Java and C++."}, p)[0] <= 2
    assert fit({"title": "Systems Engineering Intern, Weather Radar", "location": "MA", "description": "python, sql"}, p)[0] == 1
    assert fit({"title": "Business Insurance Underwriting Program", "location": "CT", "description": "excel"}, p)[0] == 1
    assert fit({"title": "AI Consulting Associate Program (AI CAP) Engineering Intern", "location": "NY",
                "description": "Generative AI and LLM use cases with Python and SQL"}, p)[0] >= 4
    da = fit({"title": "Data Analytics Intern", "location": "TX", "description": "SQL, Tableau and Python dashboards"}, p)
    assert da[0] == 4, da
    assert eligibility("University, 2026 Fall Technologist Intern", "", p) == (0, "Fall 2026 has already happened")
    assert eligibility("Pharmacy Intern, Formulary Strategy (PharmD students)", "", p)[0] == 0
    assert fit({"title": "2027 Summer Intern - Accounting", "location": "CT", "description": "automation"}, p)[0] == 1
    assert fit({"title": "Receiver, Exciter & Processing Architecture Co-Op", "location": "MA", "description": ""}, p)[0] == 1
    assert desc_track("We build dashboards in Tableau and write SQL.") == "data-analytics"
    assert desc_track("Some data and process work.") is None


if __name__ == "__main__":
    _selfcheck()
    print("ok")
