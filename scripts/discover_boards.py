"""Discover employer job boards from public internship-list links, without copying list rows."""
import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

README_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/{branch}/README.md"
INTERN_TITLE = re.compile(r"\bintern(ship)?s?\b|\bco[\s-]?op\b", re.I)


class _Table(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.row = []
        elif self.row is not None and tag in {"td", "th"}:
            self.cell = {"text": [], "hrefs": []}
            self.row.append(self.cell)
        elif self.cell is not None and tag == "a" and attrs.get("href"):
            self.cell["hrefs"].append(attrs["href"])

    def handle_endtag(self, tag):
        if tag in {"td", "th"}:
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"].append(data)


# Employer job-board hosts (the apply cell also links to the list's own site). Exact board detection happens later with ats.
_ATS_LINK = re.compile(r"myworkdayjobs\.com|greenhouse\.io|lever\.co|ashbyhq\.com|icims\.com|ultipro\.com|oraclecloud\.com|"
                       r"jobvite\.com|applytojob\.com|workable\.com|successfactors|taleo\.net|adp\.com|smartrecruiters\.com")


def parse_readme(markdown: str) -> list[tuple[str, str]]:
    """Extract only (company, employer apply URL); public-list job details are discarded."""
    table = _Table()
    table.feed(markdown)
    found, company = [], ""
    for row in table.rows:
        if len(row) < 4:
            continue
        company_cell, _, _, apply_cell = row[:4]
        label = " ".join(" ".join(company_cell["text"]).split())
        if label == "↳":
            pass
        elif label:
            company = label
        # The apply cell also links to the list's own site; keep the employer's link.
        employer = next((h for h in apply_cell["hrefs"] if _ATS_LINK.search(h)), None)
        if company and employer:
            found.append((company, employer))
    return found


def readme() -> str:
    import httpx

    for branch in ("dev", "main"):
        response = httpx.get(README_URL.format(branch=branch), timeout=20)
        if response.status_code == 200:
            return response.text
    raise RuntimeError("SimplifyJobs/Summer2027-Internships: no README on dev or main")


def _board_key(board: dict) -> str:
    return json.dumps({k: v for k, v in board.items() if k != "name"}, sort_keys=True)


def discover(rows: list[tuple[str, str]], existing: list[dict]) -> tuple[list[dict], dict]:
    from engine import ats, finder

    known = {_board_key(board) for board in existing}
    unique = {}
    counts = {"rows": len(rows), "detected": 0, "existing": 0, "eligible": 0, "errors": 0}
    for name, href in rows:
        found = ats.detect_html(href)
        if not found:
            continue
        kind, board = found
        candidate = {"name": name, "ats": kind, **board}
        counts["detected"] += 1
        key = _board_key(candidate)
        if key in known:
            counts["existing"] += 1
            continue
        unique[key] = candidate

    pace_lock = threading.Lock()
    last_call = [0.0]

    def poll(candidate):
        with pace_lock:
            delay = 0.3 - (time.monotonic() - last_call[0])
            if delay > 0:
                time.sleep(delay)
            last_call[0] = time.monotonic()
        board = {k: v for k, v in candidate.items() if k not in {"name", "ats"}}
        roles = ats.LIST[candidate["ats"]](candidate["name"], board)
        return any(finder.in_us(role.get("location")) and INTERN_TITLE.search(role.get("title", ""))
                   for role in roles)

    eligible = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(poll, candidate): candidate for candidate in unique.values()}
        for future in as_completed(futures):
            try:
                if future.result():
                    eligible.append(futures[future])
                    counts["eligible"] += 1
            except Exception:
                counts["errors"] += 1
    return sorted(eligible, key=lambda board: board["name"].lower()), counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print discovery counts without editing boards.json")
    parser.add_argument("--self-check", action="store_true", help="run the offline fixture check")
    args = parser.parse_args()
    if args.self_check:
        fixture = """<table><tr><th>Company</th><th>Role</th><th>Location</th><th>Apply</th></tr>
        <tr><td><a href="https://contoso.example">Contoso</a></td><td>Data Intern</td><td>Boston</td><td><a href="https://jobs.lever.co/contoso">Apply</a> <a href="https://list.example/p/1">More</a></td></tr>
        <tr><td>↳</td><td>Research Co-op</td><td>Remote</td><td><a href="https://jobs.ashbyhq.com/contoso">Apply</a></td></tr>
        <tr><td><a href="https://northwind.example">Northwind</a></td><td>Analyst Intern</td><td>Chicago</td><td><a href="https://boards.greenhouse.io/northwind">Apply</a></td></tr>
        </table>"""
        assert parse_readme(fixture) == [
            ("Contoso", "https://jobs.lever.co/contoso"),
            ("Contoso", "https://jobs.ashbyhq.com/contoso"),
            ("Northwind", "https://boards.greenhouse.io/northwind"),
        ]
        print("board discovery self-check passed")
        return 0

    source = json.loads((ROOT / "boards.json").read_text())
    current = source["boards"]
    boards, counts = discover(parse_readme(readme()), current)
    if not args.dry_run and boards:
        merged = current + boards
        merged.sort(key=lambda board: board["name"].lower())
        source["boards"] = merged
        (ROOT / "boards.json").write_text(json.dumps(source, indent=1) + "\n")
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
