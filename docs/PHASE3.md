# Phase 3: answers + form filler (Oct 22, 2026)

**Prep application** (dashboard button, or `engine fill <id>`) opens the posting in a visible browser,
clicks through to the form, fills every question your profile backs, checks that each answer stuck, and
stops. You read it, answer what's flagged, and click Submit. The engine never clicks Submit.

## How a question gets answered (`engine/answers.py`)
- A rule matches the question and a profile field backs it → filled, with its source recorded
  (`profile.school`, `profile.eeo=decline`, …).
- A fixed list of options must contain the answer, or nothing is chosen.
- No backing (work authorization unknown, "can you commute to our Chicago office?", compensation,
  "why us?") → **yours**, listed on the dashboard; written questions come with the closest resume lines.
- Optional with no backing → left blank. Nothing is guessed.
- Self-identification (gender, race, veteran, disability, orientation) → "decline" unless you change
  `eeo` in your profile.

## Why it gets through forms other autofills miss (`engine/fill.py`, `engine/read_form.py`)
- **Click-through:** follows Apply → Apply Manually (never "Autofill with Resume") until the form appears,
  waiting for slow single-page apps between steps.
- **Hidden options:** opens every custom dropdown and reads that dropdown's own menu; long lists and
  search-as-you-type fields get one typed word, then the matching option (first line only, apostrophes ignored).
- **Stable handles:** fields are found by id/name, not position, so a form that re-renders after a choice
  doesn't shift answers into the wrong boxes.
- **Verify, then refill:** every answer is re-read at the end. Example: choosing a phone country redraws
  and empties the phone box; the second pass catches it and refills.
- **Multi-page forms (Workday):** fills a page, continues only if nothing on it was left for you, and stops
  at any page that has Submit.
- **Sign-in walls:** a password field → row goes to Blocked ("sign-in needed"); the window stays open for you
  to sign in or create the account. The browser profile in `data/browser` remembers the login.
- **Enter is never pressed** in a form (it can submit).

## Tested (headless dry runs, dummy profile, no upload, nothing submitted)
| Board | Filled | Left for you |
|-------|--------|--------------|
| Greenhouse (DriveWealth AI CAP) | 19 of 23 | work authorization, sponsorship, office commute (+ resume upload skipped in dry run) |
| Ashby (Ibotta BI Intern) | 10 of 16 | compensation, "how did you hear" (options load on click) |
| Lever (WisdomTree Research Intern) | 6 of 12 | compensation; the rest optional |
| Workday (Synchrony) | blocked correctly at the create-account page | sign in |

## Not yet
- Workday pages after sign-in run through the multi-page loop but haven't been tested on a real
  account. The first real Workday prep should be watched.
- Written answers ("why this firm?") are yours. Claude Code can draft them from your resume lines in chat,
  under the same rule: no fact that isn't on the resume.
