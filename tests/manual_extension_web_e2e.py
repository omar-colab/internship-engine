"""Manual check (not in CI): python tests/manual_extension_web_e2e.py — needs site/app/ (#47) and `playwright install chromium`."""
# Real extension, real web app, fictional Greenhouse form: the friend's whole path with no engine.
import json, tempfile, re
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"
APP = (ROOT / "site/app/index.html").read_text()
FORM = (ROOT / "tests/fixtures/fill/greenhouse.html").read_text()
FEED = {"built": "2026-10-26T10:00:00Z", "roles": [{"company": "Contoso", "title": "Data Intern", "location": "Remote", "url": "https://boards.greenhouse.io/contoso/jobs/1", "ats": "greenhouse"}]}
APP_URL = "https://omar-colab.github.io/internship-engine/app/"
with sync_playwright() as p, tempfile.TemporaryDirectory() as prof:
    ctx = p.chromium.launch_persistent_context(prof, channel="chromium", headless=True,
        args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
    ctx.route("https://omar-colab.github.io/**", lambda r: r.fulfill(json=FEED) if r.request.url.endswith("feed.json") else r.fulfill(body=APP, content_type="text/html") if "/app/" in r.request.url else r.fulfill(status=404))
    ctx.route("https://boards.greenhouse.io/**", lambda r: r.fulfill(body=FORM, content_type="text/html"))
    errs = []
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(APP_URL); pg.fill("#name", "Alex Contoso")
    for _ in range(3): pg.click("text=Continue")
    for k, v in {"last_name": "Contoso", "email": "alex@contoso.example", "phone": "555-0100", "city": "Hartford", "state": "CT", "school": "Fabrikam University", "major": "Economics"}.items():
        pg.fill(f"#af_{k}", v)
    pg.click("text=Show my matches"); pg.wait_for_selector("text=Extension connected", timeout=10000)
    print("app: extension connected")
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    for _ in range(50):
        stored = sw.evaluate("chrome.storage.local.get('profile').then(x => x.profile)")
        if stored: break
        pg.wait_for_timeout(100)
    print("ext profile:", {k: stored.get(k) for k in ("first_name", "last_name", "email", "school", "graduation", "work_authorization", "eeo")})
    qs = [{"label": "First Name*", "kind": "text", "required": True}, {"label": "Email*", "kind": "text", "required": True},
          {"label": "School", "kind": "combobox", "options": [], "required": True},
          {"label": "Are you open to relocation?", "kind": "combobox", "options": ["Yes", "No"], "required": True},
          {"label": "Social Security Number", "kind": "text", "required": True},
          {"label": "Gender", "kind": "combobox", "options": ["Male", "Female", "Decline to self-identify"], "required": False}]
    res = sw.evaluate("qs => webCall('/ext/answers', {questions: qs})", qs)
    for q, a in zip(qs, res["answers"]): print(f"  {q['label']!r:40} -> {a['status']:9} {a['answer']!r}")
    sw.evaluate("webCall('/ext/applied', {url: 'https://boards.greenhouse.io/contoso/jobs/1', company: 'Contoso', title: 'Data Intern', learned: [{label: 'Favorite tool?', answer: 'SQL'}]})")
    print("queued:", sw.evaluate("chrome.storage.local.get('events').then(x => x.events)"))
    pg.evaluate("window.addEventListener('message', e => (window.__m = window.__m || []).push(e.data))")
    pg.bring_to_front(); pg.reload(); pg.wait_for_selector("text=Good"); pg.wait_for_timeout(1500)
    print("after reload queued:", sw.evaluate("chrome.storage.local.get('events').then(x => x.events)"), "app apps:", pg.evaluate("Object.keys(S.apps)"))
    pg.click("[data-tab=tracker]"); print("tracker applied lane:", pg.inner_text(".lane[data-stage=applied]").split("\n")[:3])
    print("errors:", errs)
    ctx.close()
