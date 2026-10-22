"""Shared feed: public internship lists → one deduped list of roles.

Sources are public GitHub READMEs (JobRight's per-category lists, SimplifyJobs).
They carry no license, so we READ them as a feed and never republish them.

    uv run python -m engine.feed            # prints counts + a sample
"""
import re
import sys

import httpx

JOBRIGHT = ["2026-Consultant-Internship", "2026-Business-Analyst-Internship", "2026-Data-Analysis-Internship"]
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

TRACKS = {  # title OR description signals; first match wins
    "ai-consulting": r"\bai\b|artificial intelligence|gen ?ai|llm|technology consult|solutions consult",
    "transformation": r"transform|digital|strategy|\bprocess\b|automation|operations",
    "data-analytics": r"data|analyt|business intelligence|\bbi\b|power bi|tableau|sql",
}


def readme(repo: str) -> str:
    for branch in ("master", "main"):
        r = httpx.get(f"https://raw.githubusercontent.com/jobright-ai/{repo}/{branch}/README.md", timeout=20)
        if r.status_code == 200:
            return r.text
    raise RuntimeError(f"{repo}: no README")


def parse_jobright(md: str, source: str) -> list[dict]:
    rows, company, homepage = [], "", None
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or set(cells[0]) <= set("- "):
            continue
        title_link = LINK.search(cells[1])
        if not title_link:
            continue                                        # header row
        if cells[0] != "↳":                                 # ↳ = same company as the row above
            m = LINK.search(cells[0])
            company = (m.group(1) if m else cells[0]).strip("* ")
            homepage = m.group(2) if m else None
        rows.append({"company": company, "title": title_link.group(1).strip("* "),
                     "location": cells[2], "work_model": cells[3], "posted": cells[4],
                     "source": source, "homepage": homepage})
    return rows


def track(title: str) -> str | None:
    t = title.lower()
    return next((k for k, rx in TRACKS.items() if re.search(rx, t)), None)


def dedupe_key(r: dict) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return f"{norm(r['company'])}|{norm(r['title'])}|{norm(r['location'])}"


def build() -> list[dict]:
    seen, out = set(), []
    for repo in JOBRIGHT:
        for r in parse_jobright(readme(repo), "jobright:" + repo.split("-", 1)[1].lower()):
            k = dedupe_key(r)
            if k in seen:
                continue
            seen.add(k)
            r["track"] = track(r["title"])
            out.append(r)
    return out


def _selfcheck() -> None:
    md = ("| Company | Job Title | Location | Work Model | Date Posted |\n| ----- | --- | --- | --- | --- |\n"
          "| **[Ryan](http://ryan.com)** | **[Summer 2027 Intern, Data Analytics](https://x/1)** | Boston, MA | On Site | Oct 21 |\n"
          "| ↳ | **[Summer 2027 Intern, Data Analytics](https://x/2)** | Plano, TX | On Site | Oct 21 |\n")
    rows = parse_jobright(md, "t")
    assert [r["company"] for r in rows] == ["Ryan", "Ryan"], rows
    assert rows[1]["homepage"] == "http://ryan.com"                # ↳ rows inherit the company's homepage
    assert rows[1]["location"] == "Plano, TX" and track(rows[0]["title"]) == "data-analytics"
    assert dedupe_key(rows[0]) != dedupe_key(rows[1])


if __name__ == "__main__":
    _selfcheck()
    roles = build()
    from collections import Counter
    print(len(roles), "roles;", dict(Counter(r["source"] for r in roles)), dict(Counter(r["track"] for r in roles)))
    for r in roles[:5]:
        print(" ", r["company"], "—", r["title"], "|", r["location"], "|", r["track"])
    sys.exit(0)
