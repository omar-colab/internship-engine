"""Capture fictional Chrome Web Store screenshots (requires Playwright Chromium)."""
import argparse
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "store"
FIXTURE = ROOT / "tests" / "fixtures" / "fill" / "greenhouse.html"
SCREENSHOTS = ("today.png", "jobs.png", "applications.png", "extension-panel.png")


def _selfcheck() -> None:
    assert FIXTURE.is_file()
    assert len(SCREENSHOTS) == 4 and len(set(SCREENSHOTS)) == 4
    assert OUT == ROOT / "site" / "store"


def capture(data_dir: Path) -> None:
    env = os.environ | {"INTERNSHIP_ENGINE_DATA": str(data_dir)}
    OUT.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen([sys.executable, "-m", "engine", "serve"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Dashboard exited before it was ready (is port 8765 already in use?)")
            try:
                urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("Dashboard did not become ready at http://127.0.0.1:8765")

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800}, color_scheme="light", reduced_motion="reduce")
            page.route("**/*", lambda route: route.abort() if route.request.url.startswith(("https://", "http://"))
                       and not route.request.url.startswith(("http://127.0.0.1:8765/", "https://fonts.googleapis.com/", "https://fonts.gstatic.com/"))
                       else route.continue_())                      # fonts only: the shots should show the real typeface
            page.goto("http://127.0.0.1:8765", wait_until="domcontentloaded")
            page.locator("#main .hero").wait_for()
            page.screenshot(path=OUT / "today.png")

            page.locator('[data-view="jobs"]').click()
            page.locator('.item.click[data-open]').first.click()
            page.locator("#drawer[aria-hidden=false]").wait_for()
            page.screenshot(path=OUT / "jobs.png")
            page.keyboard.press("Escape")
            page.locator("#drawer[aria-hidden=true]").wait_for(state="attached")

            page.locator('[data-view="applied"]').click()
            page.locator('[data-apps="board"]').click()
            page.locator(".board").wait_for()
            page.screenshot(path=OUT / "applications.png")
            form = browser.new_page(viewport={"width": 1280, "height": 800}, color_scheme="light", reduced_motion="reduce")
            form.add_init_script("""
              window.chrome = { runtime: { sendMessage(message, callback) {
                const result = message.path === '/ext/lookup' ? { role: {
                  company: 'Contoso', title: 'Operations Intern', fit: 5,
                  fit_why: 'AI consulting role · Python and SQL experience', pay: '$35–40/hr',
                  keywords: JSON.stringify({ asked: ['python','sql','tableau'], have: ['python','sql'], missing: ['tableau'] }),
                  eligible: 1, status: 'new'
                } } : { answers: [] };
                if (callback) queueMicrotask(() => callback(result));
              } } };
            """)
            form.route("**/*", lambda route: route.abort() if route.request.url.startswith("https://") else route.continue_())
            form.goto(FIXTURE.as_uri(), wait_until="domcontentloaded")
            # the fixture is bare markup for tests; dress it like a real application page for the store shot
            form.add_style_tag(content="body{font:15px/1.5 -apple-system,'Segoe UI',sans-serif;color:#0A2540;max-width:640px;margin:56px auto;padding:0 24px}"
                               "h1{font-size:28px;letter-spacing:-.02em}label{display:block;margin:18px 0 6px;font-weight:600;font-size:14px}"
                               "input,textarea,select{display:block;width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #E3E8EE;border-radius:8px;font:inherit}"
                               "button[type=submit]{margin-top:24px;padding:10px 18px;border:0;border-radius:99px;background:#0A2540;color:#fff;font:600 14px/1 inherit}")
            form.add_script_tag(path=str(ROOT / "extension" / "content.js"))
            form.locator("#internship-engine-root").wait_for(state="attached")   # zero-size host; the panel inside is position: fixed
            form.wait_for_timeout(300)
            form.screenshot(path=OUT / "extension-panel.png")
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="use an existing demo data directory")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _selfcheck()
        print("ok")
    else:
        with tempfile.TemporaryDirectory(prefix="internship-engine-store-") as tmp:
            data_dir = args.data_dir or (Path(tmp) / "data")
            if args.data_dir is None:
                subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_data.py"), "--data-dir", str(data_dir)],
                               cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
            elif not (data_dir / "engine.db").is_file():
                raise SystemExit(f"No demo tracker found in {data_dir}; run scripts/demo_data.py --data-dir {data_dir}")
            capture(data_dir)
            print(f"Screenshots saved to {OUT}")
