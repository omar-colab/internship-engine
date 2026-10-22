"""Resolver: a role from a public list → the same posting on the employer's own job board.

List links route through jobright.ai and its public page hides the apply link, so we go the
other way: company homepage → careers page → job board → the posting whose title matches.
Each company is checked once a week at most; the answer is cached in `companies`.

    uv run python -m engine resolve
"""
import difflib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import httpx

from . import ats, db

CAREERS_LINK = re.compile(r"""href=["']([^"'#]+)["'][^>]*>(?:(?!</a>).){0,200}?\b(careers?|jobs|join (?:us|our team)|work with us|opportunities)\b""",
                          re.I | re.S)
RECHECK_DAYS = 7


def norm_title(t: str) -> str:
    t = re.sub(r"\b(summer|fall|spring|winter)?\s*20\d\d\b|\(.*?\)|job details.*$|[-–|/,:]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def same_title(a: str, b: str) -> bool:
    x, y = norm_title(a), norm_title(b)
    return bool(x) and (x == y or difflib.SequenceMatcher(None, x, y).ratio() >= 0.86 or (len(x) > 14 and (x in y or y in x)))


def find_board(homepage: str) -> tuple[str, dict] | None:
    """Homepage → board link on it, or one careers link away."""
    r = httpx.get(homepage, headers=ats.UA, follow_redirects=True, timeout=15)
    if found := ats.detect_html(r.text):
        return found
    seen = set()
    for href, _ in CAREERS_LINK.findall(r.text)[:4]:
        url = str(r.url.join(href))
        if url in seen or not url.startswith("http"):
            continue
        seen.add(url)
        try:
            page = httpx.get(url, headers=ats.UA, follow_redirects=True, timeout=15)
        except httpx.HTTPError:
            continue
        if found := ats.detect_html(page.text) or ats.detect_url(str(page.url)) or ats.detect_phenom(page.text, str(page.url)):
            return found
    return None


def search_terms(title: str) -> str:
    """Workday/iCIMS keyword search works best on the distinctive words of the title."""
    words = [w for w in norm_title(title).split() if w not in {"intern", "internship", "the", "and", "of", "program", "summer"}]
    return " ".join(words[:5]) or "intern"


def slugs(name: str) -> list[str]:
    base = re.sub(r"\b(inc|llc|llp|ltd|corp(oration)?|company|co|group|the|us|usa|holdings)\b\.?", " ", name.lower())
    words = re.findall(r"[a-z0-9]+", base)
    out = ["".join(words), "-".join(words), words[0] if words else ""]
    return list(dict.fromkeys(s for s in out if len(s) > 2))


def guess_board(name: str) -> tuple[str, dict] | None:
    """Most Greenhouse/Lever/Ashby boards are just the company name. One cheap GET each."""
    for s in slugs(name):
        probes = [("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs"),
                  ("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{s}"),
                  ("lever", f"https://api.lever.co/v0/postings/{s}?mode=json&limit=1")]
        for kind, url in probes:
            try:
                r = httpx.get(url, timeout=8)
            except httpx.HTTPError:
                continue
            if r.status_code == 200 and r.text.lstrip()[:1] in "[{" and '"ok":false' not in r.text:
                return kind, {"token": s}
    return None


def render_board(homepage: str) -> tuple[str, dict] | None:
    """Last resort for JavaScript careers pages: load them in a real browser and watch the network.
    An embedded board always calls its own API (…myworkdayjobs.com/wday/cxs/…, boards-api.greenhouse.io/…)."""
    from playwright.sync_api import sync_playwright
    seen: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=ats.UA["User-Agent"])
        page.on("request", lambda req: seen.append(req.url))
        try:
            page.goto(homepage, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2500)
            if found := ats.detect_html(page.content() + " ".join(seen)):
                return found
            link = page.get_by_role("link", name=re.compile(r"^\s*(careers?|jobs|join us|work with us)\b", re.I)).first
            if link.count():
                link.click(timeout=8000)
                page.wait_for_timeout(4000)
                return ats.detect_html(page.content() + " " + page.url + " " + " ".join(seen))
        except Exception:
            return ats.detect_html(" ".join(seen))
        finally:
            browser.close()
    return None


def _company_job(name: str, homepage: str, titles: list[str], known: tuple | None) -> tuple[str, tuple | None, list[dict], str | None]:
    """Runs in a worker thread: network only, no database."""
    try:
        board = known or find_board(homepage) or guess_board(name) or render_board(homepage)
        if not board:
            return name, None, [], None
        lister = ats.LIST[board[0]]
        roles = lister(name, board[1])
        if board[0] in ats.SEARCHABLE:          # a wide "intern" search caps out; ask for each title too
            for t in titles:
                roles += lister(name, board[1], search_terms(t))
        return name, board, roles, None
    except Exception as e:
        return name, None, [], f"{name}: {type(e).__name__}"


def run() -> dict:
    con = db.connect()
    pending = con.execute("""select company, min(homepage) homepage from roles
                             where url is null and homepage is not null and status = 'new' group by company""").fetchall()
    cutoff = (date.today() - timedelta(days=RECHECK_DAYS)).isoformat()
    todo = []
    for p in pending:
        c = con.execute("select * from companies where name = ?", (p["company"],)).fetchone()
        if c and c["checked_on"] and c["checked_on"] > cutoff and not c["ats"]:
            continue                                       # looked last week, no board: don't hammer it
        titles = [r["title"] for r in con.execute("select title from roles where company = ? and url is null", (p["company"],))]
        known = (c["ats"], json.loads(c["board"])) if c and c["ats"] else None
        todo.append((p["company"], p["homepage"], titles, known))
    resolved, errors = 0, []
    with ThreadPoolExecutor(4) as pool:                  # 4: each may open a headless browser
        homepages = {t[0]: t[1] for t in todo}
        for name, board, roles, err in pool.map(lambda t: _company_job(*t), todo):
            if err:
                errors.append(err)
            con.execute("""insert into companies (name, homepage, ats, board, checked_on) values (?, ?, ?, ?, ?)
                           on conflict(name) do update set homepage = excluded.homepage, ats = coalesce(excluded.ats, ats),
                           board = coalesce(excluded.board, board), checked_on = excluded.checked_on""",
                        (name, homepages[name], board and board[0], board and json.dumps(board[1]), db.today()))
            for row in con.execute("select id, title from roles where company = ? and url is null", (name,)).fetchall():
                match = next((r for r in roles if same_title(row["title"], r["title"])), None)
                if match:
                    con.execute("update roles set url = ?, ats = ?, resolved = 'board' where id = ?", (match["url"], board[0], row["id"]))
                    resolved += 1
    con.commit()
    db.log_run(con, "resolve", len(todo), resolved, errors)
    return {"companies": len(todo), "resolved": resolved, "errors": len(errors)}


def _selfcheck() -> None:
    assert same_title("Process Risk and Controls Consulting Intern - Summer 2027", "Process Risk and Controls Consulting Intern")
    assert same_title("GTG Intern - Business Intelligence Job Details | Grainger Businesses", "GTG Intern - Business Intelligence")
    assert not same_title("Data Analyst Intern", "Supply Chain Intern")
    assert slugs("Rippling") == ["rippling"] and "west-monroe-partners" in slugs("West Monroe Partners LLC")
    assert slugs("The Energy Authority, Inc.")[0] == "energyauthority"
    assert search_terms("Technology Risk Consulting Intern - Summer 2027") == "technology risk consulting"
    html = '<a class="nav" href="/about/careers">Careers</a><a href="/x">Blog</a>'
    assert CAREERS_LINK.findall(html)[0][0] == "/about/careers"


if __name__ == "__main__":
    _selfcheck()
    print("ok")
