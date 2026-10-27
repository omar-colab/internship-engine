"""Exercise the no-install web app against an offline fictional feed."""
import json
import shutil
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "site"
        shutil.copytree(ROOT / "site", site)
        shutil.copyfile(ROOT / "tests/fixtures/webapp_feed.json", site / "feed.json")
        handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=str(site), **kwargs)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                except Exception:
                    browser = p.chromium.launch(channel="chrome")
                try:
                    page = browser.new_page(viewport={"width": 1280, "height": 900}, accept_downloads=True)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(f"http://127.0.0.1:{server.server_port}/") else route.abort())
                    page.goto(f"http://127.0.0.1:{server.server_port}/app/")

                    page.locator("#name").fill("Intern")
                    page.get_by_role("button", name="Continue").click()
                    page.locator('label.chip', has=page.locator('input[value="finance"]')).click()
                    page.locator("#places").fill("Fabrikam City")
                    page.get_by_role("button", name="Continue").click()
                    page.get_by_role("button", name="Show my matches").click()
                    page.locator(".job").first.wait_for()
                    assert page.locator(".job").count() >= 1

                    job = page.locator(".job").first
                    job.locator('button[data-act="open"]').click()
                    page.locator('#jobBody button[data-act="save"]').click()
                    page.keyboard.press("Escape")
                    page.get_by_role("button", name="Tracker").click()
                    card = page.locator(".app").filter(has_text="Finance Intern Summer 2027").first
                    card.wait_for()
                    card.locator('select[data-act="stage"]').select_option("interview")
                    page.reload()
                    page.get_by_role("button", name="Tracker").click()
                    card = page.locator(".app").filter(has_text="Finance Intern Summer 2027").first
                    assert card.locator('select[data-act="stage"]').input_value() == "interview"

                    page.locator("#addApp").click()
                    page.locator('#addForm [name="company"]').fill("Tailspin")
                    page.locator('#addForm [name="title"]').fill("Manual Finance Application")
                    page.locator('#addForm button[value="ok"]').click()
                    page.locator(".app").filter(has_text="Manual Finance Application").wait_for()
                    with page.expect_download() as download:
                        page.locator("#exportBtn").click()
                    backup = json.loads(Path(download.value.path()).read_text())
                    assert backup["apps"]
                    assert any(a["title"] == "Manual Finance Application" for a in backup["apps"].values())

                    page.get_by_role("button", name="Jobs").click()
                    page.locator("#field").select_option("all")
                    duplicate = page.locator(".job").filter(has_text="Finance Intern Summer 2027")
                    assert duplicate.count() == 1
                    assert "+1 more" in duplicate.inner_text()
                    assert page.locator(".job").filter(has_text="MBA Summer Intern").count() == 0
                    page.locator('label.chip', has=page.locator('#grad')).click()
                    assert page.locator(".job").filter(has_text="MBA Summer Intern").count() == 1

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(100)
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    assert not errors, errors
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


class WebappTests(unittest.TestCase):
    def test_webapp_flow(self):
        main()


if __name__ == "__main__":
    unittest.main()
