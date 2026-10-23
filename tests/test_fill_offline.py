"""Offline snapshots for the public form structures handled by the filler."""
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from engine import answers, fill, read_form

FIXTURES = Path(__file__).parent / "fixtures" / "fill"
PROFILE = {
    "first_name": "Ana", "last_name": "Example", "email": "ana@example.com",
    "phone": "555-0100", "linkedin": "https://example.com/ana", "city": "Hartford", "state": "CT",
    "country": "United States", "school": "State U", "degree_type": "Bachelor's", "major": "Economics",
    "graduation": "2028-05", "work_authorization": "unknown", "needs_sponsorship": "unknown",
    "open_to_relocation": False, "heard_about": "Company site", "eeo": "decline", "resume_pdf": "",
}
OBSERVE = """
window.__submitClicks = 0;
window.__enterInField = 0;
document.addEventListener('click', e => {
  if (e.target instanceof Element && e.target.closest('button[type=submit],button:not([type]),input[type=submit]'))
    window.__submitClicks++;
}, true);
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.target instanceof Element && e.target.closest('input,textarea,select,[role=combobox]'))
    window.__enterInField++;
}, true);
"""


class OfflineFillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def open_fixture(self, filename):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.add_init_script(OBSERVE)
        page.goto((FIXTURES / filename).resolve().as_uri())
        return page

    def fill_visible_fields(self, page):
        fields = read_form.read_form(page, handles=True)
        plan = answers.answer_all(fields, PROFILE, "", bank={})
        filled, needs_you = 0, []
        for field, answer in zip(fields, plan):
            if answer["status"] == "auto":
                self.assertEqual(fill.fill_one(page, field, answer, upload=False), "filled", answer["label"])
                self.assertTrue(fill.verify(page, field, answer), answer["label"])
                filled += 1
            elif answer["status"] == "needs_you":
                needs_you.append(answer["label"])
        return filled, needs_you

    def assert_safe(self, page):
        self.assertEqual(page.evaluate("window.__submitClicks"), 0)
        self.assertEqual(page.evaluate("window.__enterInField"), 0)

    def test_greenhouse(self):
        page = self.open_fixture("greenhouse.html")
        self.assertEqual(self.fill_visible_fields(page), (3, ["Why do you want to join Contoso?"]))
        self.assertIsNone(fill.next_step(page))
        self.assert_safe(page)

    def test_lever(self):
        page = self.open_fixture("lever.html")
        self.assertEqual(self.fill_visible_fields(page), (5, ["What interests you about this Northwind role?"]))
        self.assertIsNone(fill.next_step(page))
        self.assert_safe(page)

    def test_ashby(self):
        page = self.open_fixture("ashby.html")
        self.assertEqual(self.fill_visible_fields(page), (4, ["Are you legally eligible to work in the United States?"]))
        self.assertIsNone(fill.next_step(page))
        self.assert_safe(page)

    def test_workday_save_and_continue(self):
        page = self.open_fixture("workday-step.html")
        self.assertEqual(self.fill_visible_fields(page), (3, []))
        next_button = fill.next_step(page)
        self.assertEqual(next_button.inner_text(), "Save and Continue")
        next_button.click()
        self.assertEqual(self.fill_visible_fields(page), (0, ["Why are you interested in working at Contoso?"]))
        self.assertIsNone(fill.next_step(page))
        self.assert_safe(page)

    def test_react_select_combobox(self):
        page = self.open_fixture("react-select.html")
        self.assertEqual(self.fill_visible_fields(page), (2, ["What interests you about Fabrikam?"]))
        self.assertIsNone(fill.next_step(page))
        self.assert_safe(page)

    def test_password_wall_stops_headless(self):
        page = self.open_fixture("password-wall.html")
        self.assertFalse(fill.wait_for_sign_in(page, headed=False))
        self.assert_safe(page)


if __name__ == "__main__":
    unittest.main()
