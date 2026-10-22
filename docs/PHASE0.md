# Phase 0 — spike results (Oct 21, 2026)

Goal: prove the unknowns before building. Each line is a gate.

| # | Unknown | Result | Evidence |
|---|---------|--------|----------|
| 1 | Read JobRight's public lists as a feed | ✅ 251 roles (90 consulting, 64 BA, 97 data), deduped | `engine/feed.py` |
| 2 | Resolve a list row to the employer's own posting | ❌ via JobRight — public job page hides the apply link (private API only, off-limits). ✅ via employer boards instead (#3, #4) | — |
| 3 | Greenhouse / Lever / Ashby public APIs for targets | ⚠️ Work, but only 1 of 21 seed firms is on them (DriveWealth). Big 4, IBM, Accenture, Synchrony, Cigna, RTX… are not | probe in PHASE0 notes |
| 4 | Workday public career-site search | ✅ `POST https://{t}.{wd}.myworkdayjobs.com/wday/cxs/{t}/{site}/jobs` with `Accept: application/json` — Synchrony: 43 intern postings | — |
| 5 | Read every question on a real form, incl. click-to-reveal dropdowns | ✅ DriveWealth Greenhouse form: 23 questions, every react-select opened and its options listed; nothing typed or submitted | `engine/read_form.py` |
| 6 | Classify real application email | ✅ 30 threads → 23 application emails (confirm / assess / reject), 7 noise; all decidable from subject + snippet | Gmail search, one real inbox |
| 7 | Title-only track tagging | ❌ 141 of 251 untagged; "Process Risk" mis-tagged. Needs the job description → depends on #2 | `engine/feed.py` |

## What changes in the plan

- **Workday is the main road, not November.** Nearly every target employer runs it. Finder polls
  Workday career sites directly; applying on Workday needs a per-company account (still a human step until the
  keychain flow ships).
- **The form reader is the differentiator.** It walks the accessibility tree and opens each combobox, so
  "hidden until clicked" options are known before a single answer is drafted. Next: async typeaheads
  (city, school) need a typed query to list options; multi-page flows (Workday) need a page loop.
- **Inbox: sender-first query.** JobRight alerts are ~20/day and drown keyword search; the listener
  excludes alert senders, then classifies. Alerts become a *source*, not noise.
- **Fit scoring needs descriptions,** so resolution (company → its board → matching posting) comes
  before scoring.

## Boundaries kept

No decompiling JobRight's extension, no private API, nothing behind a login, no copied prompts/branding,
no CAPTCHA solving. We study what the product *does* from its public pages and build our own.
