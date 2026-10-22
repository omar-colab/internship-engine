"""Answers: every question on a form → an answer that points at where it came from, or a hand-off to you.

The honesty rule: an answer exists only if a profile field or a resume line backs it. No rule matches →
the question goes to Needs-you with the closest resume lines as a starting point. Optional questions with
no backing are left blank, never guessed. Questions you answered yourself are kept in data/answers.json
and reused only for the same question word for word (and, on a list, only if your answer is one of its options).

    answer(field, profile, resume_lines) → {"value"|"option", "source", "status": auto | needs_you | skip}
"""
import json
import re
from datetime import date

from . import db

BANK = db.DATA / "answers.json"

# never kept, whoever asks: identity numbers, birth dates, money, logins
SENSITIVE = r"social security|\bssn\b|\bsin\b|date of birth|\bdob\b|birth ?date|passport|driver.?s? licen|license number|" \
            r"bank|routing|account number|credit card|card number|password|passcode|\bpin\b|tax id|\btin\b|national id"
DECLINE = r"decline|don.?t wish|prefer not|not to (answer|disclose|say)|choose not"


def plain(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace("’", "'").replace("'", ""))


def pick(options: list[str], *prefs: str) -> str | None:
    """First option matching the first preference that matches anything (apostrophes don't matter)."""
    for rx in prefs:
        for o in options:
            if re.search(rx, o, re.I) or re.search(rx, plain(o), re.I):
                return o
    return None


def yes_no(options: list[str], yes: bool) -> str | None:
    return pick(options, r"^\s*yes\b" if yes else r"^\s*no\b")


def _grad_option(options: list[str], p: dict) -> str | None:
    y, m = int(p["graduation"][:4]), int(p["graduation"][5:7])
    season = "spring" if m <= 6 else "fall" if m >= 9 else "summer"
    month = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"][m - 1]
    return pick(options, rf"{season}\s*{y}|{y}\s*{season}", rf"{month}\s*{y}", rf"\b{y}\b")


def _auth(p: dict, key: str, field: dict, yes_means: bool):
    v = p.get(key, "unknown")
    if v in (None, "unknown"):
        return None
    yes = (v in ("us_citizen", "permanent_resident", "authorized", True, "yes")) if key == "work_authorization" else (v in (True, "yes"))
    return yes_no(field.get("options", []), yes if yes_means else not yes) if field.get("options") else ("Yes" if yes else "No")


# (label pattern, resolver) — resolver returns (answer, source) or None. Order matters: specific before general.
RULES = [
    # Voluntary self-identification: the profile's choice, "decline" by default
    (r"gender|sex\b|\brace\b|racial|ethnic|hispanic|latin|veteran|disabilit|sexual orientation|transgender|pronoun",
     lambda p, f: (pick(f.get("options", []), DECLINE), "profile.eeo=decline") if p.get("eeo", "decline") == "decline" and f.get("options") and pick(f["options"], DECLINE) else None),
    (r"^\s*first name|given name", lambda p, f: (p["first_name"], "profile.first_name")),
    (r"^\s*last name|family name|surname", lambda p, f: (p["last_name"], "profile.last_name")),
    (r"preferred (first )?name", lambda p, f: (p["first_name"], "profile.first_name")),
    (r"^\s*(full )?name\*?\s*$", lambda p, f: (f"{p['first_name']} {p['last_name']}", "profile.first_name+last_name")),
    (r"e-?mail", lambda p, f: (p["email"], "profile.email")),
    (r"^\s*country\b", lambda p, f: (pick(f.get("options", []), rf"^{re.escape(p['country'])}\b") or p["country"], "profile.country")),
    (r"phone|mobile", lambda p, f: (p["phone"], "profile.phone")),
    (r"linkedin", lambda p, f: (p["linkedin"], "profile.linkedin")),
    (r"location|city|where (do you|are you) (live|located|based)",       # short labels only: "work at our Chicago location?" is a question
     lambda p, f: ((c, "profile.country") if (c := pick(f.get("options", []), rf"^{re.escape(p['country'])}$")) else
                   (f"{p['city']}, {p['state']}", "profile.city+state")) if len(f["label"]) < 40 else None),   # a country list → your country
    (r"^\s*(resume|cv)\b|attach", lambda p, f: (p["resume_pdf"], "profile.resume_pdf")),
    (r"^\s*school|university|college|institution", lambda p, f: (p["school"], "profile.school")),
    (r"^\s*degree\b|degree type|level of (education|study)", lambda p, f: (pick(f.get("options", []), r"bachelor") or p["degree_type"], "profile.degree_type")),
    (r"^\s*(discipline|major)\b|field of study|area of study|what (is|was) your major", lambda p, f: (p["major"], "profile.major")),
    (r"graduat", lambda p, f: (_grad_option(f.get("options", []), p) or p["graduation"], "profile.graduation") if f.get("options") or "date" in f["label"].lower() or "year" in f["label"].lower() else None),
    (r"(legally )?(authori[sz]ed|eligible) to work", lambda p, f: (a, "profile.work_authorization") if (a := _auth(p, "work_authorization", f, True)) else None),
    (r"sponsor", lambda p, f: (a, "profile.needs_sponsorship") if (a := _auth(p, "needs_sponsorship", f, True)) else None),
    (r"relocat", lambda p, f: (yes_no(f.get("options", []), bool(p.get("open_to_relocation"))) or ("Yes" if p.get("open_to_relocation") else "No"), "profile.open_to_relocation")),
    (r"how did you (hear|find|learn)|source|referr(al|ed) (source|by)", lambda p, f: (pick(f.get("options", []), r"job board|website|online|internet|other") or p["heard_about"], "profile.heard_about")),
]
FREE_TEXT = ("textarea", "text")
SEARCH_SOURCES = {"profile.school", "profile.city+state"}


def suggest(label: str, resume_lines: list[str], n: int = 3) -> list[str]:
    """Resume lines sharing the most words with the question: a starting point, not an answer."""
    words = {w for w in re.findall(r"[a-z]{4,}", label.lower())} - {"what", "your", "with", "this", "that", "have", "about", "would", "describe", "please"}
    scored = sorted(((len(words & set(re.findall(r"[a-z]{4,}", l.lower()))), l) for l in resume_lines if len(l) > 40), reverse=True)
    return [l.strip("• ").strip() for s, l in scored[:n] if s]


def key(label: str) -> str:
    """The same question on two forms: case, punctuation and the required star don't matter; wording does."""
    return " ".join(plain(re.sub(r"[*✱]|\(required\)", "", label)).split())


def load_bank(path=BANK) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def remember(label: str, ans: str, path=BANK) -> dict:
    """Your answer to a question, kept for next time. Empty answer = forget it."""
    k, ans = key(str(label)[:500]), str(ans).strip()[:5000]
    if not k:
        raise ValueError("a question needs a label")
    if re.search(SENSITIVE, k):
        raise ValueError("answers to identity, birth-date, bank or login questions are never saved")
    bank = load_bank(path)
    if ans:
        if k not in bank and len(bank) >= 2000:
            raise ValueError("answer bank is full (2000)")
        bank[k] = {"answer": ans, "label": str(label)[:500], "on": date.today().isoformat()}
    else:
        bank.pop(k, None)
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(bank, indent=1))
    tmp.replace(path)                           # never a half-written bank
    return bank


def answer(field: dict, p: dict, resume_lines: list[str], bank: dict | None = None) -> dict:
    label = re.sub(r"[*✱]|\(required\)", "", field["label"]).strip()
    for rx, resolve in RULES:
        if re.search(rx, label, re.I):
            got = resolve(p, field)
            opts = field.get("options") or []
            # a fixed list must contain the answer; search lists (school, city) and capped reads (60+) only show a slice
            open_list = not opts or field["kind"] == "combobox" and (len(opts) >= 60 or got and got[1] in SEARCH_SOURCES)
            if got and got[0] and (open_list or any(plain(o) == plain(str(got[0])) for o in opts)):
                ans, src = got                  # with a fixed list, the answer must be one of its options
                return {"label": label, "kind": field["kind"], "answer": ans, "source": src, "status": "auto"}
            break                                   # the right rule, but the profile can't back it → you decide
    saved = (bank or {}).get(key(label))
    if saved and field["kind"] not in ("textarea", "file"):   # essays name a company: a draft below; uploads are yours
        opts = field.get("options") or []
        hit = next((o for o in opts if plain(o) == plain(saved["answer"])), None) if opts else saved["answer"]
        if hit:
            return {"label": label, "kind": field["kind"], "answer": hit, "source": f"you ({saved.get('on', 'saved')})", "status": "auto"}
    if not field.get("required"):
        return {"label": label, "kind": field["kind"], "answer": None, "source": None, "status": "skip"}
    return {"label": label, "kind": field["kind"], "answer": None, "source": None, "status": "needs_you",
            "options": field.get("options", [])[:12], "suggest": ([saved["answer"]] if saved else []) + suggest(label, resume_lines) if field["kind"] in FREE_TEXT else []}


def answer_all(fields: list[dict], p: dict, resume_text: str, bank: dict | None = None) -> list[dict]:
    lines = [l.strip() for l in resume_text.splitlines() if l.strip()]
    bank = load_bank() if bank is None else bank
    return [answer(f, p, lines, bank) for f in fields]


def _selfcheck() -> None:
    p = {"first_name": "Ana", "last_name": "Lee", "email": "a@x.com", "phone": "555", "linkedin": "https://linkedin.com/in/a",
         "city": "Hartford", "state": "CT", "country": "United States", "school": "State U", "degree_type": "Bachelor's",
         "major": "Economics", "graduation": "2028-05", "work_authorization": "unknown", "needs_sponsorship": "unknown",
         "open_to_relocation": True, "heard_about": "Job board", "eeo": "decline", "resume_pdf": "data/resume.pdf"}
    a = lambda label, kind="text", options=None, required=True: answer({"label": label, "kind": kind, "options": options or [], "required": required}, p, [])
    assert a("First Name*")["answer"] == "Ana" and a("Last Name*")["answer"] == "Lee"
    assert a("Country*", "combobox", ["United States +1", "Afghanistan +93"])["answer"] == "United States +1"
    assert a("Degree", "combobox", ["Associate's Degree", "Bachelor's Degree"])["answer"] == "Bachelor's Degree"
    grad = a("What is your expected graduation date?", "checkbox", ["Spring 2027", "Winter 2027", "Spring 2028", "Winter 2028"])
    assert grad["answer"] == "Spring 2028", grad
    # unknown work authorization is never guessed
    assert a("Are you legally eligible to work in the United States?*", "combobox", ["Yes", "No"])["status"] == "needs_you"
    assert a("Will you require visa sponsorship?*", "combobox", ["Yes", "No"])["status"] == "needs_you"
    p2 = {**p, "work_authorization": "us_citizen", "needs_sponsorship": "no"}
    assert answer({"label": "Are you legally eligible to work in the US?", "kind": "combobox", "options": ["Yes", "No"], "required": True}, p2, [])["answer"] == "Yes"
    assert answer({"label": "Will you require sponsorship?", "kind": "combobox", "options": ["Yes", "No"], "required": True}, p2, [])["answer"] == "No"
    assert a("Veteran Status", "combobox", ["I am not a protected veteran", "I don't wish to answer"], False)["answer"] == "I don't wish to answer"
    assert a("Gender", "combobox", ["Male", "Female"], False)["status"] == "skip"
    dis = a("Do you have a disability or chronic condition that substantially limits one or more of your major life activities?",
            "combobox", ["Yes", "No", "I don’t wish to answer"], False)
    assert dis["answer"] == "I don’t wish to answer", dis         # no decline option → leave it
    why = answer({"label": "Why do you want to work in AI consulting?", "kind": "textarea", "required": True}, p,
                 ["Built a Claude-based agent that manages the company's Google Ads account and automated its email workflow end to end.",
                  "Led 5-6 merchandisers across multiple retail stores in Connecticut and New York."])
    assert why["status"] == "needs_you" and why["answer"] is None
    assert a("Full name ✱")["answer"] == "Ana Lee"
    assert a("What is your location?", "select-one", ["Select...", "Afghanistan", "United States"])["answer"] == "United States"
    assert a("Pick a city", "select-one", ["Boston", "Austin"], False)["status"] == "skip"
    assert a("School", "combobox", ["Aalborg University"] * 60)["answer"] == "State U"            # 60+ = a slice, not the list
    assert a("How did you hear about us?", "combobox", ["LinkedIn", "Indeed"])["status"] == "needs_you"   # no backed option
    assert a("Are you willing to work at our Chicago office location?", "text")["status"] == "needs_you"
    assert a("Location (City)*", "combobox")["answer"] == "Hartford, CT"
    assert a("This role requires working in the office 3-4 days per week. Can you?", "checkbox", ["Yes", "No"])["status"] == "needs_you"
    import pathlib, tempfile
    f = pathlib.Path(tempfile.mkdtemp()) / "answers.json"
    remember("Can you work in the office 3-4 days per week?*", "yes", f)
    bank = load_bank(f)
    q = {"label": "Can you work in the office 3–4 days per week? (required)", "kind": "combobox", "options": ["Yes", "No"], "required": True}
    got = answer(q, p, [], bank)
    assert got["answer"] == "Yes" and got["source"].startswith("you ("), got          # same question, the form's own option text
    assert answer({**q, "options": ["Agree", "Disagree"]}, p, [], bank)["status"] == "needs_you"     # not an option here → ask
    assert answer({**q, "label": "Can you work in the office 5 days per week?"}, p, [], bank)["status"] == "needs_you"   # wording matters
    assert answer({"label": "First name", "kind": "text", "required": True}, p, [], {key("First name"): {"answer": "X", "on": "x"}})["answer"] == "Ana"
    for bad in ("Social Security Number*", "Date of Birth", "Bank account number", "Driver's License #"):
        try:
            remember(bad, "123", f)
            raise AssertionError(bad)
        except ValueError:
            pass
    remember("Why do you want to work here?", "Contoso's retail analytics work.", f)
    essay = answer({"label": "Why do you want to work here?", "kind": "textarea", "required": True}, p, [], load_bank(f))
    assert essay["status"] == "needs_you" and essay["suggest"][0].startswith("Contoso"), essay      # a draft for you, not a fill
    remember("Upload portfolio", "data/resume.pdf", f)
    assert answer({"label": "Upload portfolio", "kind": "file", "required": True}, p, [], load_bank(f))["status"] == "needs_you"
    remember("Upload portfolio", "", f)
    remember("Why do you want to work here?", "", f)
    remember("Can you work in the office 3-4 days per week?", "", f)
    assert not load_bank(f)                                                            # empty answer = forget


if __name__ == "__main__":
    _selfcheck()
    print("ok")
