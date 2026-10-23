"""Mark new roles skipped when their public posting has closed."""
import re
import socket
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import ats, db

CLOSED = re.compile(r"no longer accepting applications|this job (?:is )?closed|job posting has closed", re.I)
GREENHOUSE = re.compile(r"https://(?:boards|job-boards)\.greenhouse\.io/([a-z0-9]+)/jobs/(\d+)")
LEVER = re.compile(r"https://jobs\.lever\.co/([a-z0-9-]+)/([0-9a-f-]{36})")
ASHBY = re.compile(r"https://jobs\.ashbyhq\.com/([a-z0-9-]+)/([0-9a-f-]{36})")
WORKDAY = re.compile(r"(https://([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)(/job/.+)")


def _closed(url: str, *, _resolver=socket.getaddrinfo, _transport=None) -> bool:
    """Use a board's posting API where known, then inspect the public page."""
    match = GREENHOUSE.fullmatch(url)
    if match:
        check_url = f"https://boards-api.greenhouse.io/v1/boards/{match[1]}/jobs/{match[2]}"
    elif match := LEVER.fullmatch(url):
        check_url = f"https://api.lever.co/v0/postings/{match[1]}/{match[2]}"
    elif match := ASHBY.fullmatch(url):
        check_url = f"https://api.ashbyhq.com/posting-api/job-board/{match[1]}/{match[2]}"
    elif match := WORKDAY.fullmatch(url):
        base, tenant, site, path = match.groups()
        check_url = f"{base}/wday/cxs/{tenant}/{site}{path}"
    else:
        check_url = url
    try:
        response = ats._safe_request("GET", check_url, headers={**ats.UA, "Accept": "application/json"}, timeout=15,
                                     _resolver=_resolver, _transport=_transport)
    except (httpx.HTTPError, ValueError, OSError):
        return False
    if response.status_code in {404, 410}:
        return True
    if response.status_code != 200:
        return False
    body = response.text
    if CLOSED.search(body):
        return True
    if WORKDAY.fullmatch(url):
        try:
            info = response.json().get("jobPostingInfo", {})
            return bool(info.get("isClosed") or info.get("closed") or
                        str(info.get("status", "")).lower() in {"closed", "filled", "inactive"})
        except (ValueError, AttributeError):
            return False
    return False


def run(*, _resolver=socket.getaddrinfo, _transport=None, _db_path=None) -> dict:
    con = db.connect(_db_path)
    due = [dict(r) for r in con.execute(
        "select id, url from roles where status='new' and url is not null "
        "and url not like '%jobright.ai%' "                 # list pages, not postings; never poll JobRight per role
        "and (checked_on is null or checked_on <= date('now', '-3 days'))")]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda row: _closed(row["url"], _resolver=_resolver, _transport=_transport), due))
    closed = 0
    for row, is_closed in zip(due, results):
        con.execute("update roles set checked_on = ? where id = ?", (db.today(), row["id"]))
        if is_closed:
            con.execute("update roles set status='skipped', blocked_reason='posting closed' where id=?", (row["id"],))
            con.execute("insert into events (role_id, at, type, summary) values (?, datetime('now'), 'note', 'Posting closed')",
                        (row["id"],))
            closed += 1
    con.commit()
    return {"checked": len(due), "closed": closed}


def _selfcheck() -> None:
    import tempfile
    from pathlib import Path

    def resolver(host, port, type):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(404, stream=httpx.ByteStream(b""), request=request)

    transport = httpx.MockTransport(respond)
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "engine.db"
        con = db.connect(path)
        con.execute("insert into roles (key, company, title, url, found_on) values (?, ?, ?, ?, ?)",
                    ("https://boards.greenhouse.io/contoso/jobs/123", "Contoso", "Intern", "https://boards.greenhouse.io/contoso/jobs/123", db.today()))
        con.commit()
        assert run(_resolver=resolver, _transport=transport, _db_path=path) == {"checked": 1, "closed": 1}
        role = con.execute("select status, blocked_reason, checked_on from roles").fetchone()
        event = con.execute("select type, summary from events").fetchone()
        assert (role["status"], role["blocked_reason"], role["checked_on"]) == ("skipped", "posting closed", db.today())
        assert tuple(event) == ("note", "Posting closed")
        assert len(seen) == 1 and seen[0].url.path == "/v1/boards/contoso/jobs/123"
        assert run(_resolver=resolver, _transport=transport, _db_path=path) == {"checked": 0, "closed": 0}
    open_ = httpx.MockTransport(lambda req: httpx.Response(200, stream=httpx.ByteStream(b'{"title": "Intern"}'), request=req))
    assert not _closed("https://jobs.lever.co/contoso/" + "0" * 8 + "-0000-0000-0000-" + "0" * 12, _resolver=resolver, _transport=open_)
    down = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("offline", request=req)))
    assert not _closed("https://jobs.contoso.example/1", _resolver=resolver, _transport=down)   # can't reach it: keep it


if __name__ == "__main__":
    _selfcheck()
    print("ok")
