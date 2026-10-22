"""Employer job boards: detect which one a company uses, then list its intern roles.

All public, no login: Greenhouse / Lever / Ashby posting APIs and Workday's own
career-site search (the JSON the career page itself calls).
"""
import re

import httpx

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"}
INTERN = re.compile(r"\bintern(ship)?s?\b|co-?op|summer (analyst|associate|20\d\d)", re.I)
BOARD = re.compile(
    r"https?://(?P<wd>[a-z0-9-]+)\.(?P<n>wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?(?P<site>[A-Za-z0-9_-]+)"
    r"|greenhouse\.io/embed/job_board(?:/js)?\?for=(?P<ghe>[a-z0-9]+)"
    r"|https?://(?:boards|job-boards)\.greenhouse\.io/(?!embed\b)(?P<gh>[a-z0-9]+)"
    r"|https?://(?P<icims>(?!www\.|cookie)[a-z0-9-]+\.icims\.com)/jobs"
    r"|https?://(?P<ukg>recruiting2?\.ultipro\.com/[A-Z0-9]+/JobBoard/[0-9a-f-]{36})"
    r"|https?://jobs\.jobvite\.com/(?!api\b|__assets__)(?P<jobvite>[a-z0-9-]+)"
    r"|https?://(?!www\.)(?P<jazz>[a-z0-9-]+)\.applytojob\.com"
    r"|https?://apply\.workable\.com/(?!api\b|j\b)(?P<workable>[a-z0-9-]+)"
    r"|https?://(?P<sfhost>career\d*\.successfactors\.(?:com|eu))/careers?\?(?:[^\"'\s<>]*?&(?:amp;)?)?company=(?P<sfco>[A-Za-z0-9_-]+)"
    r"|https?://(?P<orahost>[a-z0-9.-]+\.oraclecloud\.com)(?::443)?/hcmUI/CandidateExperience/[a-z]{2}/sites/(?P<orasite>CX(?:_\d+)?)"
    r"|https?://jobs\.lever\.co/(?P<lever>[a-z0-9-]+)"
    r"|https?://jobs\.ashbyhq\.com/(?P<ashby>[a-z0-9-]+)")


def detect(careers_url: str) -> tuple[str, dict] | None:
    """Read a careers page and return (ats, board) for the first job-board link on it."""
    r = httpx.get(careers_url, headers=UA, follow_redirects=True, timeout=15)
    return detect_html(r.text) or detect_url(str(r.url)) or detect_phenom(r.text, str(r.url))


def detect_phenom(html: str, url: str) -> tuple[str, dict] | None:
    """Phenom career sites are the company's own domain running Phenom's front end; the page itself is the board."""
    if "phenompeople" not in html:
        return None
    from urllib.parse import urlsplit
    u = urlsplit(url)
    locale = re.search(r"/([a-z]{2}/[a-z]{2})(?:/|$)", u.path)
    return "phenom", {"origin": f"{u.scheme}://{u.netloc}", "locale": locale[1] if locale else "us/en"}


def detect_url(url: str) -> tuple[str, dict] | None:
    return detect_html(url)


def detect_html(html: str) -> tuple[str, dict] | None:
    """First job-board link in a page (or a bare URL): (ats, board)."""
    for m in BOARD.finditer(html):
        if m["wd"] and m["site"] not in ("en-US", "wday"):
            return "workday", {"tenant": m["wd"], "wd": m["n"], "site": m["site"]}
        if m["icims"]:
            return "icims", {"host": m["icims"]}
        if m["ukg"]:
            return "ukg", {"board": m["ukg"]}
        if m["jobvite"]:
            return "jobvite", {"token": m["jobvite"]}
        if m["jazz"]:
            return "jazzhr", {"token": m["jazz"]}
        if m["workable"]:
            return "workable", {"token": m["workable"]}
        if m["sfhost"]:
            return "successfactors", {"host": m["sfhost"], "company": m["sfco"]}
        if m["orahost"]:
            return "oracle", {"host": m["orahost"], "site": m["orasite"]}
        for ats in ("ghe", "gh", "lever", "ashby"):
            if m[ats]:
                return {"gh": "greenhouse", "ghe": "greenhouse"}.get(ats, ats), {"token": m[ats]}
    return None


def _role(company, title, location, url, ats, posted=None):
    return {"key": url, "company": company, "title": title, "location": location,
            "url": url, "source": ats, "ats": ats, "posted": posted}


def workday(company: str, b: dict, query: str = "intern") -> list[dict]:
    base = f"https://{b['tenant']}.{b['wd']}.myworkdayjobs.com"
    out, offset = [], 0
    while offset < 200:                                          # ponytail: 200-role cap per company
        r = httpx.post(f"{base}/wday/cxs/{b['tenant']}/{b['site']}/jobs",
                       json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": query},
                       headers={**UA, "Accept": "application/json"}, timeout=20)
        r.raise_for_status()
        page = r.json().get("jobPostings", [])
        out += [_role(company, j["title"], j.get("locationsText"), f"{base}/{b['site']}{j['externalPath']}",
                      "workday", j.get("postedOn")) for j in page
                if j.get("externalPath") and INTERN.search(j.get("title", ""))]
        if len(page) < 20:
            break
        offset += 20
    return out


def greenhouse(company: str, b: dict) -> list[dict]:
    jobs = httpx.get(f"https://boards-api.greenhouse.io/v1/boards/{b['token']}/jobs", timeout=20).json()["jobs"]
    return [_role(company, j["title"], (j.get("location") or {}).get("name"), j["absolute_url"].split("?")[0], "greenhouse")
            for j in jobs if INTERN.search(j["title"])]


def lever(company: str, b: dict) -> list[dict]:
    jobs = httpx.get(f"https://api.lever.co/v0/postings/{b['token']}?mode=json", timeout=20).json()
    return [_role(company, j["text"], j.get("categories", {}).get("location"), j["hostedUrl"], "lever")
            for j in jobs if INTERN.search(j["text"])]


def ashby(company: str, b: dict) -> list[dict]:
    jobs = httpx.get(f"https://api.ashbyhq.com/posting-api/job-board/{b['token']}", timeout=20).json()["jobs"]
    return [_role(company, j["title"], j.get("location"), j["jobUrl"], "ashby") for j in jobs if INTERN.search(j["title"])]


ICIMS_JOB = re.compile(r'href="(https://[a-z0-9-]+\.icims\.com/jobs/\d+/[^"?]+/job)[^"]*"[^>]*class="iCIMS_Anchor"[^>]*title="\d+ - ([^"]+)"')


def icims(company: str, b: dict, query: str = "intern") -> list[dict]:
    import html as h
    out = []
    for page in range(5):                                        # ponytail: 5 result pages per search
        r = httpx.get(f"https://{b['host']}/jobs/search", params={"ss": 1, "searchKeyword": query, "in_iframe": 1, "pr": page},
                      headers=UA, follow_redirects=True, timeout=20)
        found = ICIMS_JOB.findall(r.text)
        out += [_role(company, h.unescape(t), None, u, "icims") for u, t in found if INTERN.search(h.unescape(t))]
        if len(found) < 10:
            break
    return out


def ukg(company: str, b: dict, query: str = "intern") -> list[dict]:
    """UKG (UltiPro) Recruiting: the job board's own search endpoint."""
    body = {"opportunitySearch": {"Top": 50, "Skip": 0, "QueryString": query, "Filters": [],
                                  "OrderBy": [{"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}]},
            "matchCriteria": {"PreferredJobs": [], "Educations": [], "LicenseAndCertifications": [], "Skills": [],
                              "hasNoLicenses": False, "SkippedSkills": []}}
    base = f"https://{b['board']}"
    r = httpx.post(f"{base}/JobBoardView/LoadSearchResults", json=body, headers={**UA, "Accept": "application/json"}, timeout=20)
    out = []
    for o in r.json().get("opportunities", []):
        loc = (o.get("Locations") or [{}])[0].get("Address") or {}
        place = ", ".join(x for x in (loc.get("City"), (loc.get("State") or {}).get("Code")) if x)
        if INTERN.search(o["Title"]):
            out.append(_role(company, o["Title"], place or None, f"{base}/OpportunityDetail?opportunityId={o['Id']}", "ukg"))
    return out


def oracle(company: str, b: dict, query: str = "intern") -> list[dict]:
    """Oracle Cloud HCM candidate experience: the public requisitions REST resource its job site calls."""
    r = httpx.get(f"https://{b['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                  params={"onlyData": "true", "expand": "requisitionList",
                          "finder": f"findReqs;siteNumber={b['site']},keyword={query},limit=100"},
                  headers={**UA, "Accept": "application/json"}, timeout=20)
    items = r.json().get("items") or [{}]
    return [_role(company, x["Title"], x.get("PrimaryLocation"),
                  f"https://{b['host']}/hcmUI/CandidateExperience/en/sites/{b['site']}/job/{x['Id']}", "oracle")
            for x in items[0].get("requisitionList", []) if INTERN.search(x["Title"])]


def phenom(company: str, b: dict, query: str = "intern") -> list[dict]:
    """Phenom sites embed the search results in the page (phApp.ddo). Many apply links point at Workday."""
    import json
    r = httpx.get(f"{b['origin']}/{b['locale']}/search-results", params={"keywords": query}, headers=UA, follow_redirects=True, timeout=20)
    m = re.search(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp", r.text, re.S)
    if not m:
        return []
    jobs = json.loads(m[1]).get("eagerLoadRefineSearch", {}).get("data", {}).get("jobs", [])
    out = []
    for j in jobs:
        title = j.get("title") or ""
        page = f"{b['origin']}/{b['locale']}/job/{j['jobId']}" if j.get("jobId") else None
        url = page or j.get("applyUrl")
        if url and INTERN.search(title):
            place = ", ".join(x for x in (j.get("city"), j.get("state")) if x) or j.get("location")
            out.append(_role(company, title, place, url, "phenom"))
    return out


def _strip(t: str) -> str:
    import html as h
    return re.sub(r"\s+", " ", h.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def jobvite(company: str, b: dict, query: str = "intern") -> list[dict]:
    r = httpx.get(f"https://jobs.jobvite.com/{b['token']}/search", params={"q": query}, headers=UA, follow_redirects=True, timeout=20)
    out = []
    for href, body in re.findall(rf'<a[^>]+href="(/{re.escape(b["token"])}/job/[A-Za-z0-9]+)"[^>]*>(.*?)</a>', r.text, re.S):
        name = re.search(r'jv-job-list-name">(.*?)</div>', body, re.S)
        loc = re.search(r'jv-job-list-location">(.*?)</div>', body, re.S)
        title = _strip(name[1]) if name else _strip(body)
        if INTERN.search(title):
            out.append(_role(company, title, _strip(loc[1]) if loc else None, f"https://jobs.jobvite.com{href}", "jobvite"))
    return out


def jazzhr(company: str, b: dict, query: str = "intern") -> list[dict]:
    """JazzHR boards ({company}.applytojob.com) list every opening on one page."""
    r = httpx.get(f"https://{b['token']}.applytojob.com/apply", headers=UA, follow_redirects=True, timeout=20)
    out = []
    for href, title in re.findall(rf'href="(https://{re.escape(b["token"])}\.applytojob\.com/apply/[A-Za-z0-9]+/[^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
        title = _strip(title)
        if INTERN.search(title):
            out.append(_role(company, title, None, href, "jazzhr"))
    return out


def workable(company: str, b: dict, query: str = "intern") -> list[dict]:
    r = httpx.post(f"https://apply.workable.com/api/v3/accounts/{b['token']}/jobs",
                   json={"query": query, "location": [], "department": [], "worktype": [], "remote": []}, headers=UA, timeout=20)
    out = []
    for j in (r.json().get("results", []) if r.status_code == 200 else []):
        loc = j.get("location") or {}
        place = ", ".join(x for x in (loc.get("city"), loc.get("region")) if x) or ("Remote" if j.get("remote") else None)
        if INTERN.search(j["title"]):
            out.append(_role(company, j["title"], place, f"https://apply.workable.com/{b['token']}/j/{j['shortcode']}/", "workable"))
    return out


def successfactors(company: str, b: dict, query: str = "intern") -> list[dict]:
    """SuccessFactors' classic career site publishes its whole listing as XML, descriptions included."""
    r = httpx.get(f"https://{b['host']}/career", params={"company": b["company"], "career_ns": "job_listing_summary", "resultType": "XML"},
                  headers=UA, follow_redirects=True, timeout=60)
    out = []
    for job in re.findall(r"<Job>(.*?)</Job>", r.text, re.S):
        title = _strip(re.sub(r"^<!\[CDATA\[|\]\]>$", "", (re.search(r"<JobTitle>(.*?)</JobTitle>", job, re.S) or [""," "])[1].strip()))
        req = re.search(r"<ReqId>(\d+)</ReqId>", job)
        if not (req and INTERN.search(title)):
            continue
        val = lambda lab: (re.search(rf"<label>{lab}</label>\s*<value>(.*?)</value>", job, re.S) or [None, ""])[1].strip()
        place = ", ".join(x for x in (val("City"), val("State")) if x) or None
        desc = re.search(r"<Job-Description>(.*?)</Job-Description>", job, re.S)
        role = _role(company, re.sub(r"^\d+\s*-\s*#?\d*\s*", "", title) or title, place,
                     f"https://{b['host']}/career?company={b['company']}&career_ns=job_listing&career_job_req_id={req[1]}", "successfactors")
        role["description"] = text_of(re.sub(r"^<!\[CDATA\[|\]\]>$", "", desc[1].strip())) if desc else None
        out.append(role)
    return out


LIST = {"workday": workday, "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "icims": icims,
        "ukg": ukg, "oracle": oracle, "phenom": phenom, "jobvite": jobvite, "jazzhr": jazzhr, "workable": workable,
        "successfactors": successfactors}
SEARCHABLE = {"workday", "icims", "ukg", "oracle", "phenom", "jobvite", "workable"}   # keyword search: one title at a time


def _selfcheck() -> None:
    m = BOARD.search('<a href="https://otis.wd504.myworkdayjobs.com/en-US/REC_Ext_Gateway?q=x">')
    assert (m["wd"], m["n"], m["site"]) == ("otis", "wd504", "REC_Ext_Gateway"), m.groupdict()
    assert BOARD.search("https://job-boards.greenhouse.io/drivewealth/jobs/1")["gh"] == "drivewealth"
    assert detect_html('src="//job-boards.greenhouse.io/embed/job_board?for=westmonroe4"') == ("greenhouse", {"token": "westmonroe4"})
    assert detect_html('href="https://careers-berrydunn.icims.com/jobs/intro"') == ("icims", {"host": "careers-berrydunn.icims.com"})
    assert detect_html('href="https://www.icims.com/legal/privacy"') is None
    assert detect_html("https://recruiting2.ultipro.com/SOU1016SFBLI/JobBoard/adba73e4-f371-45d0-a5d2-32260abcd2f8/Opp") == \
        ("ukg", {"board": "recruiting2.ultipro.com/SOU1016SFBLI/JobBoard/adba73e4-f371-45d0-a5d2-32260abcd2f8"})
    assert detect_html("https://eofd.fa.us6.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/pages/x") == \
        ("oracle", {"host": "eofd.fa.us6.oraclecloud.com", "site": "CX_1001"})
    assert detect_html('href="https://jobs.jobvite.com/martinmarietta/search"') == ("jobvite", {"token": "martinmarietta"})
    assert detect_html("https://usginsurance.applytojob.com/apply") == ("jazzhr", {"token": "usginsurance"})
    assert detect_html("https://apply.workable.com/huggingface/") == ("workable", {"token": "huggingface"})
    assert detect_html("https://career4.successfactors.com/career?career_company=Gallo&lang=en_US&company=Gallo&site=") == \
        ("successfactors", {"host": "career4.successfactors.com", "company": "Gallo"})
    assert detect_html("https://career012.successfactors.eu/career?company=paccarinc&amp;site=V") == \
        ("successfactors", {"host": "career012.successfactors.eu", "company": "paccarinc"})
    assert detect_phenom("<script src=//cdn.phenompeople.com/x.js>", "https://careers.cboe.com/us/en/home") == \
        ("phenom", {"origin": "https://careers.cboe.com", "locale": "us/en"})
    a = '<a href="https://careers-x.icims.com/jobs/4066/summer-2027-consulting-internship/job?in_iframe=1" class="iCIMS_Anchor" title="4066 - Summer 2027 Consulting Internship">'
    assert ICIMS_JOB.findall(a) == [("https://careers-x.icims.com/jobs/4066/summer-2027-consulting-internship/job", "Summer 2027 Consulting Internship")]
    assert INTERN.search("Summer 2027 Internship") and INTERN.search("Co-Op, Strategy") and not INTERN.search("Internal Auditor")


if __name__ == "__main__":
    _selfcheck()
    print("ok")


# ---- descriptions ---------------------------------------------------------------------------------

def text_of(html: str) -> str:
    """HTML → plain text, enough for matching. Drops scripts/styles, keeps line breaks at block tags."""
    import html as h
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html or "")
    html = re.sub(r"(?i)<(br|/p|/li|/h\d|/div)\b[^>]*>", "\n", html)
    t = h.unescape(re.sub(r"<[^>]+>", " ", h.unescape(html)))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def _jsonld_description(html: str) -> str | None:
    """schema.org JobPosting, which most career sites embed for Google Jobs."""
    import json
    for block in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for d in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(d, dict) and d.get("@type") == "JobPosting" and d.get("description"):
                return text_of(d["description"])
    return None


def description(url: str) -> str | None:
    """Full posting text for a role URL, from the board's API when we know it, else the page itself."""
    if m := re.match(r"(https://([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)(/job/.+)", url):
        base, tenant, site, path = m.groups()
        r = httpx.get(f"{base}/wday/cxs/{tenant}/{site}{path}", headers={**UA, "Accept": "application/json"}, timeout=20)
        if r.status_code == 200:
            return text_of(r.json().get("jobPostingInfo", {}).get("jobDescription", "")) or None
    if m := re.match(r"https://(?:boards|job-boards)\.greenhouse\.io/([a-z0-9]+)/jobs/(\d+)", url):
        r = httpx.get(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}", timeout=20)
        if r.status_code == 200:
            return text_of(r.json().get("content", ""))
    if m := re.match(r"https://jobs\.lever\.co/([a-z0-9-]+)/([0-9a-f-]{36})", url):
        r = httpx.get(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}", timeout=20)
        if r.status_code == 200:
            j = r.json()
            return "\n".join([j.get("descriptionPlain", "")] + [f"{l['text']}\n{text_of(l['content'])}" for l in j.get("lists", [])])
    if m := re.match(r"https://apply\.workable\.com/([a-z0-9-]+)/j/([A-Z0-9]+)", url):
        r = httpx.get(f"https://apply.workable.com/api/v2/accounts/{m[1]}/jobs/{m[2]}", headers=UA, timeout=20)
        if r.status_code == 200:
            j = r.json()
            return text_of("\n".join(j.get(k) or "" for k in ("description", "requirements", "benefits")))
    if m := re.match(r"https://([a-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z]{2}/sites/(CX(?:_\d+)?)/job/(\d+)", url):
        r = httpx.get(f"https://{m[1]}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails",
                      params={"expand": "all", "onlyData": "true", "finder": f'ById;Id="{m[3]}",siteNumber={m[2]}'},
                      headers={**UA, "Accept": "application/json"}, timeout=20)
        items = r.json().get("items") if r.status_code == 200 else None
        if items:
            d = items[0]
            return text_of("\n".join(d.get(k) or "" for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")))
    r = httpx.get(url, headers=UA, follow_redirects=True, timeout=20)
    return _jsonld_description(r.text) if r.status_code == 200 else None
