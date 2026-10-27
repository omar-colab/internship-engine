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

SOURCES = [
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md",
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README-Off-Season.md",
    "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/README.md",
]
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


def clean_name(name: str) -> str:
    """Public lists decorate names ("🔥 NVIDIA", "**Figma**"); the feed shows the employer's plain name."""
    return re.sub(r"^[^\w(]+|[^\w).&!]+$", "", name).strip() or name


def parse_readme(markdown: str) -> list[tuple[str, str]]:
    """Extract only (company, employer apply URL); public-list job details are discarded."""
    table = _Table()
    table.feed(markdown)
    found, company = [], ""

    def add_rows(rows, allow_redirects=False):
        nonlocal company
        headers = [" ".join(" ".join(cell["text"]).split()).lower() for cell in rows[0]] if rows else []
        company_col = next((i for i, value in enumerate(headers) if "company" in value), None)
        apply_col = next((i for i, value in enumerate(headers)
                          if any(word in value for word in ("apply", "application", "link"))), None)
        if company_col is None or apply_col is None:
            return
        for row in rows[1:]:
            if max(company_col, apply_col) >= len(row):
                continue
            label = " ".join(" ".join(row[company_col]["text"]).split())
            if label and label != "↳":
                company = label
            apply_cell = row[apply_col]
            # Simplify's apply cell also links to its own site; keep the employer ATS link.
            employer = next((h for h in apply_cell["hrefs"] if _ATS_LINK.search(h)), None)
            # Other lists may wrap the employer URL in a redirect link.
            if employer is None and allow_redirects and apply_cell["hrefs"]:
                employer = apply_cell["hrefs"][0]
            if company and employer:
                found.append((company, employer))

    add_rows(table.rows)

    md_rows = []
    for line in markdown.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        row = []
        for value in cells:
            cell_parser = _Table()
            cell_parser.feed(value)
            text = " ".join(" ".join(" ".join(cell["text"]) for cell in r).split()
                            for r in cell_parser.rows)
            # Markdown cell text can be plain text or inline HTML; links come from HTML anchors.
            if not text:
                text = re.sub(r"\[([^]]+)\]\([^)]*\)|<[^>]+>", lambda m: m.group(1) or "", value)
            hrefs = re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\']', value, re.I)
            hrefs.extend(re.findall(r"\]\((https?://[^)]+)\)", value))
            row.append({"text": [text], "hrefs": hrefs})
        md_rows.append(row)
    add_rows(md_rows, allow_redirects=True)
    return found


def fetch_source(url: str, _get=None) -> str:
    import httpx

    get = _get or httpx.get
    urls = [url]
    if "/dev/" in url:
        urls.append(url.replace("/dev/", "/main/"))
    for source in urls:
        response = get(source, timeout=20)
        if response.status_code == 200:
            if re.search(r"(?i)captcha|access denied|verify you are human|unusual traffic", response.text):
                raise RuntimeError(f"{source}: bot wall returned; stopping")
            return response.text
        if response.status_code != 404:
            raise RuntimeError(f"{source}: HTTP {response.status_code}; stopping")
    raise FileNotFoundError(f"{url}: README not found")


def _board_key(board: dict) -> str:
    return json.dumps({k: v for k, v in board.items() if k != "name"}, sort_keys=True)


def resolve_redirects(rows: list[tuple[str, str]], get=None) -> list[tuple[str, str]]:
    """Links that aren't a job board (list shorteners) → their one-hop redirect target. The target page is never loaded."""
    from engine import ats
    from urllib.parse import urljoin
    get = get or (lambda url: ats._safe_request("GET", url, timeout=10, max_bytes=1024,
                                                _follow_redirects=False))

    def one(row):
        name, href = row
        if _ATS_LINK.search(href):
            return row
        try:
            target = get(href).headers.get("location", "")
        except Exception:
            return None
        target = urljoin(href, target) if target else ""
        return (name, target) if _ATS_LINK.search(target) else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        return [r for r in pool.map(one, rows) if r]


def discover(rows: list[tuple[str, str]], existing: list[dict]) -> tuple[list[dict], dict]:
    from engine import ats, finder

    known = {_board_key(board) for board in existing}
    unique = {}
    counts = {"rows": len(rows), "detected": 0, "existing": 0, "eligible": 0, "errors": 0}
    seen = set()
    for name, href in rows:
        if href in seen:
            continue
        seen.add(href)
        found = ats.detect_html(href)
        if not found:
            continue
        kind, board = found
        candidate = {"name": clean_name(name), "ats": kind, **board}
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
    parser.add_argument("--source", action="append", help="source README URL (repeatable; overrides SOURCES)")
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
        markdown_fixture = """| Company | Role | Location | Application/Link | Date Posted |
| ------- | ---- | -------- | ---------------- | ----------- |
| Fabrikam | Software Intern | Boston | <a href="https://jobs.lever.co/fabrikam"><img alt="Apply"></a> | Today |
| ↳ | Data Co-op | Remote | <a href="https://boards.greenhouse.io/fabrikam"><img alt="Apply"></a> | Today |
| Tailspin | Analyst Intern | Chicago | <a href="https://jobs.ashbyhq.com/tailspin">Apply</a> | Today |
"""
        assert clean_name("🔥 Northwind") == "Northwind" and clean_name("**Contoso**") == "Contoso"
        assert clean_name("Tailspin (TT)") == "Tailspin (TT)" and clean_name("Fabrikam & Co.") == "Fabrikam & Co."
        assert parse_readme(markdown_fixture) == [
            ("Fabrikam", "https://jobs.lever.co/fabrikam"),
            ("Fabrikam", "https://boards.greenhouse.io/fabrikam"),
            ("Tailspin", "https://jobs.ashbyhq.com/tailspin"),
        ]
        class Response:
            def __init__(self, status_code, text=""):
                self.status_code, self.text = status_code, text

        calls = []
        try:
            fetch_source(SOURCES[0], lambda url, **kwargs: calls.append(url) or Response(403))
            raise AssertionError("403 must stop source fallback")
        except RuntimeError as error:
            assert "403" in str(error)
        assert len(calls) == 1 and "/dev/" in calls[0], calls

        calls = []
        assert fetch_source(SOURCES[0], lambda url, **kwargs: calls.append(url) or
                            Response(404 if "/dev/" in url else 200, "fixture")) == "fixture"
        assert len(calls) == 2 and "/dev/" in calls[0] and "/main/" in calls[1], calls

        calls = []
        try:
            fetch_source(SOURCES[0], lambda url, **kwargs: calls.append(url) or Response(200, "verify you are human"))
            raise AssertionError("bot wall must stop source fallback")
        except RuntimeError as error:
            assert "bot wall" in str(error)
        assert len(calls) == 1, calls
        class Hop:
            def __init__(self, location): self.headers = {"location": location}
        hops = {"https://short.example/a": "https://jobs.lever.co/contoso/1", "https://short.example/b": "https://contoso.example/careers"}
        assert resolve_redirects([("Contoso", "https://short.example/a"), ("Northwind", "https://short.example/b"),
                                  ("Fabrikam", "https://boards.greenhouse.io/fabrikam/jobs/2")], get=lambda u: Hop(hops[u])) == \
            [("Contoso", "https://jobs.lever.co/contoso/1"), ("Fabrikam", "https://boards.greenhouse.io/fabrikam/jobs/2")]
        print("board discovery self-check passed")
        return 0

    source = json.loads((ROOT / "boards.json").read_text())
    current = source["boards"]
    source_urls = args.source or SOURCES
    rows = []
    missing = []
    for source_url in source_urls:
        try:
            rows.extend(parse_readme(fetch_source(source_url)))
        except FileNotFoundError as error:
            missing.append(str(error))
    if not rows:
        raise RuntimeError("no internship-list rows parsed; missing sources: " + "; ".join(missing))
    boards, counts = discover(resolve_redirects(list(dict.fromkeys(rows))), current)
    if not args.dry_run and boards:
        merged = current + boards
        merged.sort(key=lambda board: board["name"].lower())
        source["boards"] = merged
        (ROOT / "boards.json").write_text(json.dumps(source, indent=1) + "\n")
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
