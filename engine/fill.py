"""Filler: open a posting, reveal the form, fill every question that has a backed answer. Never submits.

Review mode (the default) opens a visible browser and leaves it with you: read it, fix anything, click
Submit yourself. The listener records the confirmation email afterwards, so nothing else to log.

    uv run python -m engine fill <role id>               # visible browser, you submit
    uv run python -m engine fill <role id> --dry-run     # headless check: fill, verify, close (no resume upload)
"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from . import answers, db, read_form, score

ROOT = Path(__file__).resolve().parent.parent
SUBMIT = re.compile(r"submit|send application|apply$", re.I)
NEXT = re.compile(r"^\s*(save and continue|continue|next|save & continue)\s*$", re.I)
MAX_STEPS = 8
SIGN_IN_MINUTES = 10


def next_step(page: Page):
    """The button to the next page of a multi-page form, or None. None whenever a Submit is on screen:
    the last page is always yours."""
    if page.get_by_role("button", name=SUBMIT).filter(visible=True).count():
        return None
    btn = page.get_by_role("button", name=NEXT).filter(visible=True)
    return btn.first if btn.count() else None


def search_text(answer: str) -> str:
    """One word to type into a dropdown's search: the longest, so it's a real substring of the option."""
    return max(re.findall(r"[A-Za-z0-9]+", answer), key=len, default=answer)


def _menu(page: Page, el):
    """The options of THIS dropdown only (its aria-controls listbox), so a menu left open elsewhere can't confuse it."""
    lb = el.get_attribute("aria-controls") or el.get_attribute("aria-owns")
    if lb:
        return page.locator(f'[id="{lb}"] [role=option]')
    # react-select renders its menu next to the input: the closest ancestor holding options is this field's menu
    return el.locator("xpath=ancestor::*[.//*[@role='option']][1]//*[@role='option']")


def _wait_options(page: Page, el, ms: int) -> list:
    for _ in range(ms // 250):
        opts = _menu(page, el).all()
        if opts:
            return opts
        page.wait_for_timeout(250)
    return []


def choose_combobox(page: Page, el, answer: str, options: list[str]) -> bool:
    """React-select style. Short list: open it and click. Long list, search-as-you-type, or no match in what's shown:
    type one word, then click the match. Options are compared on their first line ("University of X\nUnited States").
    Never press Enter: in a form, Enter can submit."""
    page.keyboard.press("Escape")                     # close anything a previous field left open
    el.scroll_into_view_if_needed()
    el.focus()
    page.keyboard.press("ArrowDown")                  # opens the menu without a click something might be covering
    want, city = answers.plain(answer), answers.plain(answer.split(",")[0])
    first_line = lambda o: answers.plain(o.inner_text().split("\n")[0])
    typed = False
    for _ in range(2):
        if typed or not options or len(options) > 15:
            el.fill("")
            el.press_sequentially(search_text(answer.split(",")[0]), delay=40)   # real keystrokes: autocompletes listen
            typed = True
        opts = _wait_options(page, el, 5000 if typed else 2500)
        lines = [first_line(o) for o in opts]
        i = next((k for k, t in enumerate(lines) if t == want), None)
        if i is None and typed:                       # "Hartford, CT" → "Hartford, Connecticut, United States"
            i = next((k for k, t in enumerate(lines) if t.startswith(city)), None)
        if i is not None:
            opts[i].click()
            return True
        if typed:
            break
        typed = True                                  # not in the short list it showed: search for it
    page.keyboard.press("Escape")
    return False


def fill_one(page: Page, f: dict, a: dict, upload: bool) -> str:
    """Returns filled | failed | skipped. A failure's reason goes in a["error"] for the prep log."""
    el, kind, ans = f["_el"], f["kind"], a["answer"]
    try:
        if kind == "file":
            if not upload:
                return "skipped"
            el.set_input_files(str(ans if Path(ans).is_absolute() else ROOT / ans))
        elif kind in ("select-one", "select-multiple"):
            el.select_option(label=ans)
        elif kind == "combobox":
            if not choose_combobox(page, el, ans, f.get("options") or []):
                a["error"] = "no matching option"
                return "failed"
        elif kind in ("radio", "checkbox"):
            boxes = page.locator(f'input[name="{f["name"]}"]').all() if f["name"] else [el]
            hit = next((b for b in boxes if answers.plain(read_form.option_label(page, b)) == answers.plain(str(ans))), None)
            if not hit:
                return "failed"
            hit.check()
        else:
            el.fill(str(ans))
            if el.input_value() != str(ans):
                return "failed"
        return "filled"
    except Exception as e:
        a["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"
        return "failed"


def verify(page: Page, f: dict, a: dict) -> bool:
    """Is the answer still there? Fields can be wiped by a later one (choosing a phone country redraws the phone box)."""
    el, kind, ans = f["_el"], f["kind"], str(a["answer"])
    try:
        if kind in ("radio", "checkbox"):
            boxes = page.locator(f'input[name="{f["name"]}"]').all() if f["name"] else [el]
            return any(b.is_checked() and answers.plain(read_form.option_label(page, b)) == answers.plain(ans) for b in boxes)
        if kind == "combobox":                         # react-select shows the choice next to its input
            shown = el.evaluate("""e => { let n = e;                       // nearest ancestor that shows any text
                for (let i = 0; i < 5 && n.parentElement; i++) { n = n.parentElement; if (n.innerText.trim()) return n.innerText; }
                return ''; }""")
            code = re.search(r"\+\d{1,3}$", ans)       # phone-country pickers show "🇺🇸 +1", not the name
            value = el.input_value() if el.evaluate("e => 'value' in e") else ""     # some keep the choice in the input
            return any(answers.plain(ans.split(",")[0]) in answers.plain(t) for t in (shown, value)) or bool(code and code[0] in shown)
        if kind in ("select-one", "select-multiple"):
            return answers.plain(el.evaluate("e => e.options[e.selectedIndex]?.text || ''")) == answers.plain(ans)
        if kind == "file":
            return el.evaluate("e => e.files.length > 0")
        v = el.input_value()                           # autocompletes may expand it: "State U" → "State U - Main Campus"
        if kind == "tel" or re.search(r"phone|mobile", f["label"], re.I):     # formatters: "555-5555" → "(555) 555-5555"
            return re.sub(r"\D", "", v).endswith(re.sub(r"\D", "", ans))
        return v == ans or bool(ans) and answers.plain(ans) in answers.plain(v)
    except Exception:
        return False


def wait_for_sign_in(page, headed: bool, minutes: int = SIGN_IN_MINUTES) -> bool:
    """You sign in (or make the account) in the open window; filling carries on once the password box is gone.
    The engine never types a password: it only watches. Closed window or timeout → False."""
    if not headed:
        return False
    print(f"This site needs you to sign in. Do it in the window; filling continues when you're in (waiting {minutes} min).")
    for _ in range(minutes * 30):
        try:
            page.wait_for_timeout(2000)
            if not page.locator("input[type=password]").filter(visible=True).count():
                page.wait_for_timeout(2500)              # the post-login redirect settles
                read_form.reveal_form(page)
                if not page.locator("input[type=password]").filter(visible=True).count():
                    return True
        except Exception:                                # you closed the window
            return False
    return False


def prep(role_id: int, headed: bool = True, upload: bool = True, profile: dict | None = None) -> dict:
    con = db.connect()
    role = con.execute("select * from roles where id = ?", (role_id,)).fetchone()
    if not role or not role["url"]:
        raise SystemExit("That role has no posting link yet.")
    p = profile or score.load_profile()
    tailored = db.DATA / "resumes" / f"{role_id}.pdf"
    if tailored.exists() and profile is None:              # a resume ordered for this posting, if you made one
        p = {**p, "resume_pdf": str(tailored.relative_to(ROOT)) if tailored.is_relative_to(ROOT) else str(tailored)}
    resume = (ROOT / p.get("resume", "data/resume.txt")).read_text() if (ROOT / p.get("resume", "data/resume.txt")).exists() else ""
    with sync_playwright() as pw:
        # a persistent profile keeps your logins (Workday, etc.) between runs; it lives in data/, never committed
        ctx = pw.chromium.launch_persistent_context(str(db.DATA / "browser"), headless=not headed, viewport={"width": 1280, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(role["url"], wait_until="load")
        page.wait_for_timeout(2500)                       # some boards never go network-idle (analytics polling)
        read_form.reveal_form(page)
        if page.locator("input[type=password]").filter(visible=True).count() and not wait_for_sign_in(page, headed):
            # Workday and friends: an account first. The login is remembered next time (persistent profile).
            con.execute("update roles set status = 'blocked', blocked_reason = 'sign-in needed: sign in, then Prep again' where id = ?", (role_id,))
            con.commit()
            ctx.close()
            return {"role_id": role_id, "blocked": "sign-in needed", "fields": 0, "filled": 0, "needs_you": []}
        plan: list[dict] = []
        for step in range(MAX_STEPS):                     # one pass per page of a multi-page form (Workday)
            fields = read_form.read_form(page, handles=True)
            page_plan = answers.answer_all(fields, p, resume)
            for f, a in zip(fields, page_plan):
                a["result"] = fill_one(page, f, a, upload) if a["status"] == "auto" else a["status"]
            for attempt in range(2):                      # re-check everything; refill what a later field wiped
                for f, a in zip(fields, page_plan):
                    if a["result"] == "filled" and not verify(page, f, a):
                        a["result"] = fill_one(page, f, a, upload) if attempt == 0 else "failed"
                        a.setdefault("error", "was cleared after filling")
            plan += [{**a, "page": step + 1} for a in page_plan]
            nxt = next_step(page)
            # continue only when this page is complete and you're watching; an unanswered question stops here
            if not (headed and nxt) or any(a["result"] in ("needs_you", "failed") for a in page_plan):
                break
            nxt.click()
            page.wait_for_timeout(2500)
        submit = page.get_by_role("button", name=SUBMIT).filter(visible=True)
        if submit.count():
            submit.first.scroll_into_view_if_needed()      # show you where Submit is; never click it
        summary = {"role_id": role_id, "url": role["url"], "fields": len(plan),
                   "filled": sum(a["result"] == "filled" for a in plan),
                   "needs_you": [a["label"] for a in plan if a["result"] in ("needs_you", "failed")],
                   "answers": [{k: v for k, v in a.items() if k != "options" or a["result"] == "needs_you"} for a in plan]}
        con.execute("update roles set next_action = ?, notes = coalesce(notes, '') where id = ?",
                    (f"Prepped {summary['filled']}/{summary['fields']}; you: {len(summary['needs_you'])} question(s), then Submit", role_id))
        con.execute("insert into events (role_id, at, type, summary) values (?, datetime('now'), 'note', ?)",
                    (role_id, f"Prepped form: {summary['filled']} of {summary['fields']} filled"))
        (db.DATA / "prep").mkdir(exist_ok=True)
        (db.DATA / "prep" / f"{role_id}.json").write_text(json.dumps(summary, indent=1, default=str))
        con.commit()
        if headed:
            print("Review the form in the browser, answer the flagged questions, then click Submit yourself.")
            page.wait_for_event("close", timeout=0)        # stays open until you close the tab
        ctx.close()
    return summary


def _selfcheck() -> None:
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content("<form><input id=a><button type=button>Save and Continue</button></form>")
        assert next_step(page).inner_text() == "Save and Continue"
        page.set_content("<form><input id=a><button type=button>Back</button><button type=submit>Submit</button></form>")
        assert next_step(page) is None                     # a Submit on screen: stop, it's yours
        page.set_content("<form><input id=a></form>")
        assert next_step(page) is None
        page.set_content("<input type=password id=pw><script>setTimeout(() => pw.remove(), 2500)</script>")
        assert wait_for_sign_in(page, True, minutes=1)     # you signed in: the password box went away
        page.set_content("<input type=password>")
        assert not wait_for_sign_in(page, False)           # headless: nobody to sign in, block
        b.close()


if __name__ == "__main__" and sys.argv[1:] == ["--selfcheck"]:
    _selfcheck()
    print("ok")
elif __name__ == "__main__":
    rid = int(sys.argv[1])
    dry = "--dry-run" in sys.argv
    out = prep(rid, headed=not dry, upload=not dry)
    print(json.dumps({k: out[k] for k in ("fields", "filled", "needs_you")}, indent=1))
