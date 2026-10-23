"""Keep learned answers safe on the extension's applied event."""
import json
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "fill" / "learned-payload.html"
CONTENT_SCRIPT = ROOT / "extension" / "content.js"

MOCK_EXTENSION = """
window.__messages = [];
document.addEventListener("submit", event => event.preventDefault());
const attachShadow = Element.prototype.attachShadow;
Element.prototype.attachShadow = function (options) {
  const root = attachShadow.call(this, options);
  window.__extensionRoot = root;
  return root;
};
window.chrome = { runtime: { sendMessage(message, callback) {
  window.__messages.push(message);
  if (!callback) return;
  callback(message.path === "/ext/lookup" ? { role: null }
    : message.path === "/ext/answers"
      ? { answers: message.body.questions.map(() => ({ status: "needs_you" })) }
      : {});
} } };
"""


class LearnedPayloadTests(unittest.TestCase):
    def test_applied_payload_omits_sensitive_answers_and_limits_combobox(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            try:
                page.add_init_script(MOCK_EXTENSION)
                page.goto(FIXTURE.as_uri())
                page.locator("#resume").set_input_files({
                    "name": "fictional-resume.pdf", "mimeType": "application/pdf", "buffer": b"fictional pdf",
                })
                page.locator("#team").fill("Tailspin")
                page.add_script_tag(path=str(CONTENT_SCRIPT))
                page.wait_for_function("window.__extensionRoot?.querySelector('.fill')")
                page.evaluate("window.__extensionRoot.querySelector('.fill').click()")
                page.wait_for_function("window.__messages.some(m => m.path === '/ext/answers')")
                page.wait_for_function("window.__extensionRoot.querySelector('.body').innerText.includes('Filled')")
                page.locator("button[type=submit]").click()

                applied = page.evaluate("window.__messages.find(m => m.path === '/ext/applied')")
                self.assertIsNotNone(applied)
                learned = applied["body"]["learned"]
                encoded = json.dumps(applied)
                for secret in ("Fictional essay sentinel", "password sentinel", "fictional-resume.pdf", "fictional pdf"):
                    self.assertNotIn(secret, encoded)
                self.assertNotIn("essay", [item["label"] for item in learned])
                self.assertNotIn("Resume", [item["label"] for item in learned])
                self.assertNotIn("Account password", [item["label"] for item in learned])

                combo = next(item for item in learned if item["label"] == "Preferred team")
                questions = next(m["body"]["questions"] for m in page.evaluate("window.__messages")
                                 if m["path"] == "/ext/answers")
                combo_question = next(q for q in questions if q["label"] == "Preferred team")
                self.assertIn(combo["answer"], combo_question["options"])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
