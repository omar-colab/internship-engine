"""Exercise the shipped extension content script against offline ATS snapshots."""
import json
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from engine import answers

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "fill"
CONTENT_SCRIPT = ROOT / "extension" / "content.js"
PROFILE = json.loads((ROOT / "profile.example.json").read_text())


class ExtensionFillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.messages = []

    def mock_message(self, message):
        self.messages.append(message)
        if message.get("type") == "resume":
            return {"error": "offline"}
        if message.get("path") == "/ext/lookup":
            return {"role": None}
        if message.get("path") == "/ext/answers":
            questions = message["body"]["questions"]
            return {"answers": answers.answer_all(questions, PROFILE, "", bank={})}
        return {"error": "unexpected extension request"}

    def open_fixture(self, filename):
        page = self.browser.new_page()
        page.set_default_timeout(5000)
        self.addCleanup(page.close)
        page.expose_function("__extensionMessage", self.mock_message)
        page.add_init_script("""
          window.__submitClicks = 0;
          window.__sentMessages = [];
          document.addEventListener("click", event => {
            if (event.target instanceof Element && event.target.closest("[type=submit]")) window.__submitClicks++;
          }, true);
          const attachShadow = Element.prototype.attachShadow;
          Element.prototype.attachShadow = function(options) {
            const root = attachShadow.call(this, options);
            if (this.id === "internship-engine-root") window.__testShadowRoot = root;
            return root;
          };
          window.chrome = {runtime: {sendMessage(message, callback) {
            window.__sentMessages.push(message);
            window.__extensionMessage(message).then(callback);
          }}};
        """)
        page.goto((FIXTURES / filename).resolve().as_uri())
        page.add_script_tag(path=str(CONTENT_SCRIPT))
        page.wait_for_function("window.__testShadowRoot?.querySelector('button.fill')")
        return page

    def fill_application(self, page):
        page.evaluate("window.__testShadowRoot.querySelector('button.fill').click()")
        page.wait_for_function("window.__testShadowRoot?.querySelector('.body')?.innerText.includes('Filled')")

    def assert_requests(self, *, resume=False):
        paths = [message.get("path") for message in self.messages]
        self.assertEqual({path for path in paths if path}, {"/ext/lookup", "/ext/answers"})
        self.assertEqual(paths.count("/ext/lookup"), 1)
        self.assertEqual(paths.count("/ext/answers"), 1)
        self.assertEqual(paths.count("/ext/applied"), 0)
        self.assertEqual(sum(message.get("type") == "resume" for message in self.messages), int(resume))

    def assert_no_submit(self, page):
        self.assertEqual(page.evaluate("window.__submitClicks"), 0)

    def test_greenhouse_react_select_phone_mask_and_resume_guard(self):
        page = self.open_fixture("greenhouse.html")
        self.fill_application(page)
        self.assertEqual(page.locator("#first_name").input_value(), PROFILE["first_name"])
        self.assertEqual(page.locator("#last_name").input_value(), PROFILE["last_name"])
        self.assertEqual(page.locator("#email").input_value(), PROFILE["email"])
        self.assertEqual(page.locator("#phone").input_value(), "(555) 555-5555")
        self.assertEqual(page.locator("#school").input_value(), PROFILE["school"])
        self.assertEqual(page.locator("#why").input_value(), "")
        self.assertEqual(page.locator("#resume").input_value(), "")
        self.assert_requests(resume=True)
        self.assert_no_submit(page)

    def test_lever_text_url_and_select_fields(self):
        page = self.open_fixture("lever.html")
        self.fill_application(page)
        self.assertEqual(page.locator("#first_name").input_value(), PROFILE["first_name"])
        self.assertEqual(page.locator("#last_name").input_value(), PROFILE["last_name"])
        self.assertEqual(page.locator("#email").input_value(), PROFILE["email"])
        self.assertEqual(page.locator("#linkedin").input_value(), PROFILE["linkedin"])
        self.assertEqual(page.locator("#country").input_value(), "United States")
        self.assertEqual(page.locator("#why").input_value(), "")
        self.assert_requests()
        self.assert_no_submit(page)

    def test_ashby_radio_choice_and_unknown_eligibility_are_safe(self):
        page = self.open_fixture("ashby.html")
        self.fill_application(page)
        self.assertEqual(page.locator("#gender").input_value(), "I don't wish to answer")
        self.assertFalse(page.locator('input[name="eligibility"]:checked').count())
        self.assert_requests()
        self.assert_no_submit(page)

    def test_page_script_cannot_fake_an_application_submit(self):
        page = self.open_fixture("greenhouse.html")
        page.evaluate("""() => {
          const button = document.createElement('button');
          button.id = 'test-submit';
          button.textContent = 'Submit application';
          document.body.append(button);
          button.click();
        }""")
        self.assertEqual(page.evaluate("window.__sentMessages.filter(m => m.path === '/ext/applied').length"), 0)
        page.locator("#test-submit").click()
        page.wait_for_function("window.__sentMessages.some(m => m.path === '/ext/applied')")
        self.assertEqual(page.evaluate("window.__sentMessages.filter(m => m.path === '/ext/applied').length"), 1)


if __name__ == "__main__":
    unittest.main()
