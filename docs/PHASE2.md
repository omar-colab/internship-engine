# Phase 2: resolve, score, warm lane, schedule (Oct 21, 2026)

## What runs every morning at 7:00 (`engine daily`, launchd)

| Step | What it does | Today's numbers |
|------|--------------|-----------------|
| find | Employer boards from `companies.json` + JobRight's public lists, US/remote only, cross-source dedupe | 487 roles |
| resolve | List row → employer's own posting: homepage → careers page → board → title match. Boards found by link, by guessing the company slug (Greenhouse/Lever/Ashby), or by loading the page in a headless browser and watching its network calls. Workday and iCIMS are searched per title. Cached weekly per company | 60 of 226 list rows resolved; 66 boards known |
| score | Fetches each posting's full text (Workday/Greenhouse/Lever APIs, else the page's schema.org JobPosting), then eligibility + fit against `data/profile.json` | 314 descriptions; 46 ineligible, 94 "check first", 73 at fit 4–5 |
| warm | `data/contacts.csv` (LinkedIn export) → roles at companies where you know someone, with a <200-character note built only from profile facts | waits for the export |

`engine listen` joins the schedule (every 2 hours) once `engine gmail` has stored an app password in the Keychain.

## Eligibility (hard gates, read from the posting)
Graduate-only titles or descriptions · graduation windows that exclude your year · "class of 20XX" ·
freshman/sophomore programs · seasons already past → hidden. Co-ops and US-citizenship/clearance
requirements → shown with "Check first".

## Fit (1–5, with the reasons)
Title track (+1.5) or a description with 2+ strong track signals (+0.6) · distinctive strengths found in
the posting (+0.35 each, max 5) · generic ones (+0.1, max 4) · business/analytics title (+0.4) · in your
area or remote (+0.3) · named hard requirements you don't list (Java, C++, CPA…: −0.5 each).
Off-field titles (engineering, science, clinical, legal, tax/audit, underwriting…) are 1.

## Gate
Of the top 10 queued roles, at least 8 should be ones you'd actually apply to. Judge it on the dashboard.

## Known gaps → next
- 88 companies still have no detected board (SuccessFactors, UKG, ADP, Phenom, Oracle, custom). Each is a
  small adapter; their roles keep a "Find posting" search link meanwhile.
- Scores are pattern-based. An optional Claude re-rank of the top 30 fits the Phase 3 prep session.
- US citizenship is unknown in the profile, so 94 roles say "Check first". Set `work_authorization`.
