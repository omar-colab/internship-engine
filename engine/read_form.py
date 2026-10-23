"""Read every question on a job application form, including the hidden ones.

Most autofill tools read the DOM once and miss anything that only exists after a
click: "Apply" buttons that reveal the form, and custom dropdowns (react-select,
Workday popups) whose options aren't in the page until opened. This walks the
accessibility tree, opens each combobox to list its options, then closes it.
It never types into or submits anything.

    uv run python -m engine.read_form <posting-url> [--headed]
"""
import ipaddress
import json
import re
import socket
import sys
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Page, sync_playwright

APPLY = re.compile(r"^\s*(apply|apply now|apply manually|apply for this job|start application|start your application)\s*$", re.I)   # never "Autofill with Resume": it uploads your file
FIELDS = "input:not([type=hidden]):not([type=submit]), textarea, select, [role=combobox]"


def allowed(url: str, _resolve=socket.getaddrinfo) -> bool:
    """Public HTTPS only: posting URLs come from shared feeds, so one could point at your router or this laptop."""
    u = urlsplit(url)
    if u.scheme in ("data", "blob") or url == "about:blank":
        return True
    if u.scheme != "https" or not u.hostname or u.port not in (None, 443):
        return False
    try:
        ips = {i[4][0].split("%")[0] for i in _resolve(u.hostname, 443, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError):
        return False
    return bool(ips) and all(ipaddress.ip_address(ip).is_global for ip in ips)


def guard(target, _resolve=socket.getaddrinfo) -> None:
    """Check every request a page or context makes. Navigations take redirects one hop at a time, each hop
    rechecked, because the browser would otherwise follow a public URL's redirect to a private one unchecked."""
    # ponytail: checks DNS, then Chromium resolves again; a rebinding attacker could still race it. Pin via proxy if it matters.
    seen: dict[str, bool] = {}
    def ok(url: str) -> bool:
        host = urlsplit(url).hostname or url
        if host not in seen or url.startswith(("data:", "blob:")):
            seen[host] = allowed(url, _resolve)
        return seen[host]
    def check(route):
        req = route.request
        if not ok(req.url):
            return route.abort("blockedbyclient")
        if not req.is_navigation_request():
            return route.continue_()
        r = route.fetch(max_redirects=0)
        loc = r.headers.get("location")
        if 300 <= r.status < 400 and loc and not ok(urljoin(req.url, loc)):
            return route.abort("blockedbyclient")
        route.fulfill(response=r)
    target.route("**/*", check)


def reveal_form(page: Page, max_clicks: int = 3) -> int:
    """Click through 'Apply' steps until form fields appear. Returns clicks used."""
    for i in range(max_clicks + 1):
        for _ in range(12 if i else 1):                  # after a click, give the next step up to 6 s to render
            if page.locator(FIELDS).filter(visible=True).count() >= 3:
                return i
            page.wait_for_timeout(500)
        btn = page.get_by_role("button", name=APPLY).or_(page.get_by_role("link", name=APPLY)).filter(visible=True)
        if not btn.count():
            return i
        btn.first.click()
    return max_clicks


LABEL_JS = """e => {
  const clean = t => (t || '').trim().replace(/\\s+/g, ' ');
  const own = el => clean([...el.childNodes].filter(n => n.nodeType === 3 || !n.querySelector?.('input,select,textarea')).map(n => n.textContent).join(' '));
  const LABELISH = 'label, legend, [class*=label], [class*=Label], [class*=title], [class*=question-text], [class*=prompt]';
  const group = (e.type === 'radio' || e.type === 'checkbox') && e.name;
  if (!group) {
    const byId = e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
    if (byId && clean(byId.innerText)) return clean(byId.innerText);
    if (e.getAttribute('aria-label')) return clean(e.getAttribute('aria-label'));
    const lb = (e.getAttribute('aria-labelledby') || '').split(' ').map(id => document.getElementById(id)?.innerText || '').join(' ');
    if (clean(lb)) return clean(lb);
  }
  // Walk up: the question is the nearest label-like text that isn't one of this question's own options.
  const mine = group ? [...document.querySelectorAll(`input[name="${CSS.escape(e.name)}"]`)] : [e];
  let n = e;
  for (let i = 0; i < 7 && n.parentElement; i++) {
    n = n.parentElement;
    if (group && !mine.every(x => n.contains(x))) continue;          // climb until the whole group is inside
    const cands = [...n.querySelectorAll(LABELISH)].filter(c => !mine.some(x => c.contains(x) || (x.id && c.getAttribute('for') === x.id)));
    const hit = cands.map(c => clean(c.innerText)).find(t => t && t.length < 400);
    if (hit) return hit;
    if (group && n.tagName === 'FIELDSET') break;
  }
  return clean(e.name || e.placeholder || '');
}"""


def label_of(page: Page, el) -> str:
    """The question an input belongs to (for a radio/checkbox: its group's question, not its own option)."""
    return el.evaluate(LABEL_JS)


def option_label(page: Page, el) -> str:
    """A radio/checkbox's own text: what you'd click."""
    return el.evaluate("""e => {
        const byId = e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
        return ((byId || e.closest('label') || e.parentElement).innerText || e.value || '').trim().replace(/\\s+/g, ' '); }""")


def combobox_options(page: Page, el) -> list[str]:
    """Open a custom dropdown, read its options, close it again."""
    try:
        el.click()
        page.wait_for_timeout(400)
        opts = page.get_by_role("option").filter(visible=True).all_inner_texts()
        page.keyboard.press("Escape")
        return [o.strip() for o in opts if o.strip()][:60]
    except Exception:
        return []


def read_form(page: Page, handles: bool = False) -> list[dict]:
    """Every question, in page order. handles=True keeps the element under "_el" for the filler."""
    out, seen = [], set()
    for el in page.locator(FIELDS).filter(visible=True).all():
        kind = el.evaluate("e => e.getAttribute('role') === 'combobox' ? 'combobox' : (e.type || e.tagName).toLowerCase()")
        name = el.get_attribute("name") or el.get_attribute("id") or ""
        if kind != "combobox" and el.evaluate("e => !!e.closest('[class*=select__control], [class*=select-shell]')"):
            continue                                # react-select's own inner <input>, already read as the combobox
        label = label_of(page, el)
        if kind in ("radio", "checkbox"):           # one entry per group, labelled by its question
            key = ("group", name or label)
        else:
            key = (label, name, kind)
        if key in seen:
            continue
        seen.add(key)
        q = {"label": label, "kind": kind, "name": name,
             "required": el.evaluate("e => e.required || e.getAttribute('aria-required') === 'true' || /\\*/.test(e.closest('.field, fieldset, div')?.innerText.slice(0, 200) || '')")}
        if kind == "select-one" or kind == "select-multiple":
            q["options"] = [o.strip() for o in el.locator("option").all_inner_texts() if o.strip()]
        elif kind == "combobox":
            q["options"] = combobox_options(page, el)
        elif kind in ("radio", "checkbox") and name:
            q["options"] = [option_label(page, b) for b in page.locator(f'input[name="{name}"]').all()]
        if handles:
            # a stable handle: by id, else name. Index-based handles drift as soon as a dropdown re-renders the form.
            fid = el.get_attribute("id")
            q["_el"] = page.locator(f'[id="{fid}"]').first if fid else (page.locator(f'[name="{name}"]').first if name else el)
        out.append(q)
    return out


def main(url: str, headed: bool = False) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        guard(page)
        page.goto(url, wait_until="networkidle")
        clicks = reveal_form(page)
        fields = read_form(page)
        browser.close()
    print(json.dumps({"url": url, "apply_clicks": clicks, "fields": fields}, indent=1, ensure_ascii=False))


def _selfcheck() -> None:
    fake = {"jobs.contoso.example": "203.0.113.9", "intranet.fabrikam.example": "10.0.0.7", "rebind.example": "127.0.0.1",
            "v6.northwind.example": "fe80::1%en0", "board.tailspin.example": "8.8.8.8"}
    def dns(host, *_a, **_k):
        if host not in fake:
            raise socket.gaierror(host)
        return [(0, 0, 0, "", (fake[host], 443))]
    assert allowed("https://board.tailspin.example/jobs/1", dns)
    assert not allowed("https://jobs.contoso.example/x", dns)          # TEST-NET: reserved, not global
    assert not allowed("http://board.tailspin.example/", dns)          # https only
    assert not allowed("https://board.tailspin.example:8443/", dns)    # 443 only
    for bad in ("https://intranet.fabrikam.example/", "https://rebind.example/", "https://v6.northwind.example/",
                "https://127.0.0.1/", "https://[::1]/", "https://unknown.example/", "file:///etc/passwd", "javascript:alert(1)"):
        assert not allowed(bad, dns), bad
    assert allowed("about:blank") and allowed("data:text/html,x")
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        guard(page, dns)
        for bad in ("http://127.0.0.1:8765/api/state", "https://intranet.fabrikam.example/"):
            try:
                page.goto(bad)
                raise AssertionError(f"navigated to {bad}")
            except Exception as e:
                assert "BLOCKED_BY_CLIENT" in str(e) or "blocked" in str(e).lower(), e
        b.close()


if __name__ == "__main__" and sys.argv[1:] == ["--selfcheck"]:
    _selfcheck()
    print("ok")
elif __name__ == "__main__":
    main(sys.argv[1], "--headed" in sys.argv)
