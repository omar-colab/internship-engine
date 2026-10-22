"""Resumes: one master (data/resume.json), variants per track, a tailored PDF per role. Honest by construction.

A variant or tailoring may only REORDER: bullets inside an entry, projects, skill lines. Experience stays in date
order (moving jobs around misleads a reader). Rewording happens only in Claude Code (/tailor), and comes back through
check(): every line must trace to a master line, with no new number, tool or employer.

    uv run python -m engine resume variants        # data/resumes/variant-<track>.pdf for each of your tracks
    uv run python -m engine resume tailor <id>     # data/resumes/<id>.pdf ordered for that posting, + what moved
    uv run python -m engine resume check <file>    # honesty check for a reworded resume.json
"""
import copy
import html
import json
import re
from pathlib import Path

from . import db, score

MASTER = db.DATA / "resume.json"
OUT = db.DATA / "resumes"
TRACK_WORDS = {
    "ai-consulting": "ai agent claude automat llm voice workflow diligence research client consult strategy prompt agentic",
    "transformation": "workflow process operations automat coordinat scheduling vendor invoice p&l dispatch standards strategy end to end",
    "data-analytics": "data sql python tableau dashboard analy market sizing census acs cleaned visualiz excel model test",
}
STOP = set("the a an and or of to in for on with by from that this its as at is are was were be their our your".split())


def words(t: str) -> list[str]:
    toks = (w.strip(".,;:-") for w in re.findall(r"[a-z0-9&$.%~+-]+", t.lower()))   # "sql." → "sql", keep "$289.9m"
    return [w for w in toks if w and w not in STOP]


def relevance(text: str, keys: list[str]) -> float:
    t = text.lower()
    return sum(1 for k in keys if k in t)


def keywords(track: str | None, posting: str = "") -> list[str]:
    """Track words, plus the posting's own frequent words when tailoring for one role."""
    keys = TRACK_WORDS.get(track or "", "").split()
    if posting:
        freq: dict[str, int] = {}
        for w in words(posting):
            if len(w) > 4:
                freq[w] = freq.get(w, 0) + 1
        keys += [w for w, n in sorted(freq.items(), key=lambda x: -x[1])[:40] if n >= 2]
    return keys


def arrange(master: dict, keys: list[str]) -> dict:
    """Reorder only. Same lines, same entries, same facts."""
    r = copy.deepcopy(master)
    for sec in r["sections"]:
        for e in sec.get("entries", []):
            e["bullets"] = sorted(e["bullets"], key=lambda b: -relevance(b, keys))          # stable: ties keep master order
        if sec["title"].lower() == "projects":
            sec["entries"] = sorted(sec["entries"], key=lambda e: -relevance(" ".join(e["bullets"]) + e["org"], keys))
        if "lines" in sec:
            sec["lines"] = sorted(sec["lines"], key=lambda l: -relevance(l[1], keys))
    return r


def moved(master: dict, variant: dict) -> list[str]:
    """Plain list of what changed position, for the person to see before using it."""
    out = []
    for ms, vs in zip(master["sections"], variant["sections"]):
        for me, ve in zip(ms.get("entries", []), vs.get("entries", [])):
            if me["org"] != ve["org"]:
                out.append(f"{vs['title']}: {ve['org']} moved up")
                break
        for ve in vs.get("entries", []):
            me = next((m for m in ms.get("entries", []) if m["org"] == ve["org"] and m["role"] == ve["role"]), None)
            if me and ve["bullets"] and me["bullets"] and ve["bullets"][0] != me["bullets"][0]:
                out.append(f"{ve['org']}: leads with \"{ve['bullets'][0][:70]}…\"")
        if ms.get("lines") and vs.get("lines") and ms["lines"][0] != vs["lines"][0]:
            out.append(f"Skills: {vs['lines'][0][0]} listed first")
    return out


NUM = re.compile(r"\$?~?\d[\d,.]*[%xX+]?")


def check(master: dict, variant: dict) -> list[str]:
    """Honesty check. Returns problems; empty means every line traces to the master."""
    problems = []
    m_bullets = [b for s in master["sections"] for e in s.get("entries", []) for b in e["bullets"]]
    m_entries = {(e["org"], e["role"], e["dates"]) for s in master["sections"] for e in s.get("entries", [])}
    m_text = " ".join(m_bullets + [l[1] for s in master["sections"] for l in s.get("lines", [])]).lower()
    m_nums = set(NUM.findall(" ".join(m_bullets)))
    for s in variant["sections"]:
        for e in s.get("entries", []):
            if (e["org"], e["role"], e["dates"]) not in m_entries:
                problems.append(f"Entry not on the master: {e['org']} / {e['role']} / {e['dates']}")
            for b in e["bullets"]:
                # traceable = most of this line's words come from one master line (order may change, facts may not)
                bw = set(words(b))
                ratio = max((len(bw & set(words(m))) / max(len(bw), 1) for m in m_bullets), default=0)
                if ratio < 0.7:
                    problems.append(f"Doesn't trace to a master line ({ratio:.0%} match): {b[:90]}")
                for n in set(NUM.findall(b)) - m_nums:
                    problems.append(f"New number '{n}': {b[:90]}")
                for tool in re.findall(r"\b[A-Z][A-Za-z+#.]{1,}[A-Za-z]\b", b):
                    if tool.lower() not in m_text and tool.lower() not in {"built", "led", "ran", "designed", "wrote", "created", "managed"}:
                        problems.append(f"New name or tool '{tool}': {b[:90]}")
        for l in s.get("lines", []):
            for item in [x.strip() for x in l[1].split(",")]:
                if item and item.lower() not in m_text:
                    problems.append(f"New skill '{item}'")
    return problems


def check_text(master: dict, text: str) -> list[str]:
    """Honesty check for prose (a cover letter, a 'why us' answer). Each sentence with a claim in it must trace to a
    master bullet; short connective sentences ("I'd welcome the chance to talk.") pass. No new numbers."""
    m_bullets = [b for s in master["sections"] for e in s.get("entries", []) for b in e["bullets"]]
    m_text = " ".join(m_bullets + [l[1] for s in master["sections"] for l in s.get("lines", [])] +
                      [f"{e['org']} {e['role']}" for s in master["sections"] for e in s.get("entries", [])]).lower()
    m_nums = set(NUM.findall(" ".join(m_bullets)))
    problems = []
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        w = set(words(sent))
        if len(w) < 7 and not NUM.search(sent):
            continue
        for n in set(NUM.findall(sent)) - m_nums:
            problems.append(f"New number '{n}': {sent[:100]}")
        claims = {x for x in w if len(x) > 3} - set(words("intern internship role team company position opportunity apply applying excited interest interested work working help learn believe would welcome chance talk thank you your their this program"))
        if claims and len([x for x in claims if x in m_text]) / len(claims) < 0.5:
            problems.append(f"Doesn't trace to your resume: {sent[:100]}")
    return problems


def to_html(r: dict) -> str:
    """Classic one-page layout: name, contact line, ruled sections, bold org | italic role, right-aligned dates."""
    e = html.escape
    links = r.get("links", {})
    contact = " | ".join(f'<a href="{e(links[c])}">{e(c)}</a>' if c in links else e(c) for c in r["contact"])
    parts = [f'<h1>{e(r["name"])}</h1><p class="contact">{contact}</p>']
    for s in r["sections"]:
        parts.append(f'<h2>{e(s["title"].upper())}</h2>')
        for en in s.get("entries", []):
            parts.append(f'<div class="ent"><span><b>{e(en["org"])}</b> &nbsp;|&nbsp; <i>{e(en["role"])}</i></span><b>{e(en["dates"])}</b></div>')
            if en.get("bullets"):
                parts.append("<ul>" + "".join(f"<li>{e(b)}</li>" for b in en["bullets"]) + "</ul>")
        if s.get("lines"):
            parts.append("<ul>" + "".join(f"<li><b>{e(k)}</b>: {e(v)}</li>" for k, v in s["lines"]) + "</ul>")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      @page {{ size: Letter; margin: 0.45in 0.55in; }}
      body {{ font: var(--fs, 10.2pt)/1.22 "Times New Roman", Times, serif; color: #000; margin: 0; }}
      h1 {{ text-align: center; font-weight: 400; font-size: 21pt; margin: 0 0 2px; }}
      .contact {{ text-align: center; font-size: 8.6pt; margin: 0 0 6px; }} a {{ color: #000; }}
      h2 {{ font-size: 11pt; margin: 8px 0 3px; border-bottom: 1px solid #000; padding-bottom: 1px; }}
      .ent {{ display: flex; justify-content: space-between; margin-top: 4px; }}
      ul {{ margin: 1px 0 0; padding-left: 13px; }} li {{ margin: 0; }}
    </style></head><body>{''.join(parts)}</body></html>"""


def render(r: dict, path: Path) -> Path:
    """HTML → PDF with the browser the filler already uses. Shrinks the type slightly if it spills past one page."""
    from playwright.sync_api import sync_playwright
    path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 710, "height": 1000})        # Letter minus margins: 7.4in at 96 dpi
        page.set_content(to_html(r))
        for fs in (10.2, 9.8, 9.4, 9.0, 8.7):
            page.evaluate(f"document.body.style.setProperty('--fs', '{fs}pt')")
            if page.evaluate("document.body.scrollHeight") <= 970:       # 10.1in of printable height
                break
        page.pdf(path=str(path), format="Letter", print_background=True,
                 margin={"top": "0.45in", "bottom": "0.45in", "left": "0.55in", "right": "0.55in"})
        b.close()
    return path


def master() -> dict:
    if not MASTER.exists():
        raise SystemExit("No data/resume.json yet. Run /setup in Claude Code, or copy resume.example.json to data/resume.json.")
    return json.loads(MASTER.read_text())


def variants() -> dict:
    m = master()
    out = {}
    for t in score.load_profile().get("tracks", []):
        v = arrange(m, keywords(t))
        assert not check(m, v)
        out[t] = {"pdf": str(render(v, OUT / f"variant-{t}.pdf")), "moved": moved(m, v)}
    return out


def tailor(role_id: int) -> dict:
    con = db.connect()
    r = con.execute("select * from roles where id = ?", (role_id,)).fetchone()
    if not r:
        raise SystemExit("No such role.")
    m = master()
    v = arrange(m, keywords(r["track"], f"{r['title']} {r['description'] or ''}"))
    problems = check(m, v)
    if problems:                                         # reordering can't fail this; if it does, refuse loudly
        raise SystemExit("Honesty check failed:\n" + "\n".join(problems))
    pdf = render(v, OUT / f"{role_id}.pdf")
    (OUT / f"{role_id}.json").write_text(json.dumps(v, indent=1))
    con.execute("update roles set resume_variant = ? where id = ?", (f"tailored:{role_id}", role_id))
    con.commit()
    return {"pdf": str(pdf), "moved": moved(m, v)}


def _selfcheck() -> None:
    m = {"name": "A", "contact": [], "sections": [{"title": "Experience", "entries": [
        {"org": "Contoso", "role": "Analyst", "dates": "2026", "bullets": ["Ran payroll for 12 stores.", "Built a SQL dashboard in Tableau."]}]},
        {"title": "Skills", "lines": [["Technical", "SQL, Tableau"], ["Business", "Payroll"]]}]}
    v = arrange(m, keywords("data-analytics"))
    assert v["sections"][0]["entries"][0]["bullets"][0].startswith("Built a SQL") and not check(m, v)
    assert moved(m, v)
    bad = copy.deepcopy(m)
    bad["sections"][0]["entries"][0]["bullets"][1] = "Built a SQL dashboard in Tableau used by 40 managers."
    assert any("New number" in p for p in check(m, bad))
    bad["sections"][0]["entries"][0]["bullets"][1] = "Built a Python dashboard in Power BI."
    assert any("Python" in p or "Power" in p for p in check(m, bad)), check(m, bad)
    bad["sections"][0]["entries"].append({"org": "Fabrikam", "role": "Intern", "dates": "2025", "bullets": []})
    assert any("Entry not on the master" in p for p in check(m, bad))
    assert not check_text(m, "I built a SQL dashboard in Tableau at Contoso. I'd welcome the chance to talk.")
    assert check_text(m, "At Contoso I grew revenue 40% by launching a pricing engine in Python.")
    ok = copy.deepcopy(m)
    ok["sections"][0]["entries"][0]["bullets"][1] = "Built a Tableau dashboard with SQL."           # a reword that keeps the facts
    assert not check(m, ok), check(m, ok)


if __name__ == "__main__":
    _selfcheck()
    print("ok")
