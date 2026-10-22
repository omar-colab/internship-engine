# Internship Engine

Finds internships on employers' own job boards, ranks them against your resume, fills the application forms
other autofills give up on, and tracks everything from your inbox. Free, open source, and it runs on your laptop:
your resume, tracker and email never leave it.

**New here?** Start with the [quick setup guide](#set-up). The Chrome extension is in [GitHub Releases](https://github.com/omar-colab/internship-engine/releases/latest); it connects to an engine running on your own computer.

## What it does

| | |
|---|---|
| **Find** | Reads Workday, Greenhouse, Lever, Ashby, iCIMS, UKG, Oracle Cloud and Phenom boards directly, plus public internship lists. Any company it meets once gets watched from then on. |
| **Rank** | Fetches every posting in full and scores it 1–5 against your resume with a one-line reason. Graduate-only roles, the wrong class year and past seasons are hidden. |
| **Fill** | Clicks through to the real form, opens every dropdown to read hidden options, types into search-as-you-type fields, attaches your resume, verifies each answer and refills what the page wiped. Works from the dashboard (a browser window it drives) or the Chrome extension (on the page you're on). |
| **Track** | Confirmation, assessment, interview and rejection emails update each application. Quiet for two weeks → a follow-up reminder. |
| **Warm leads** | Your LinkedIn connections export flags roles where you know someone, with a short note built from your real experience. |
| **Resumes** | Variants per track and a tailored PDF per role. Only your own lines, reordered for the posting; rewording (Claude Code `/tailor`) must pass an honesty check that rejects any new number, tool, employer or skill. |
| **Measure** | Reply and interview rates by track and source, plus a Sunday digest. |

## Three rules it never breaks

1. **It never clicks Submit.** You read every application and press the button yourself.
2. **It never invents.** Every answer points at a field in your profile or a line in your resume. No backing, no answer.
3. **It never pretends to be you.** No CAPTCHA solving, no LinkedIn automation, no sending messages. Drafts only.

## Set up

Needs macOS or Linux, Chrome, and [uv](https://docs.astral.sh/uv/). Claude Code is optional for the assisted `/setup` flow.

```sh
git clone https://github.com/omar-colab/internship-engine
cd internship-engine
uv sync
mkdir -p data
cp profile.example.json data/profile.json
# edit data/profile.json, then start the engine
uv run python -m engine serve
```

For application filling or resume PDF generation, install the browser once with `uv run playwright install chromium`.
For assisted setup, run `claude` in the repository and type `/setup`; it builds `data/profile.json` and `data/resume.json` from your resume, then asks about tracks, locations and work authorization. Review both before using them; the resume schema is shown in [`resume.example.json`](resume.example.json).

To run the daily job search after editing your profile:

```sh
uv run python -m engine daily                    # find → resolve → score → warm
uv run python -m engine serve                    # dashboard at http://127.0.0.1:8765
uv run python -m engine schedule                 # every morning at 7:00, inbox every 2 h, digest Sundays
```

**Chrome extension:** Follow [the extension install guide](extension/README.md). GitHub Releases provides a ready-to-load ZIP. Chrome requires Developer mode for GitHub-hosted ZIPs; true one-click installation needs a Chrome Web Store listing.

**Inbox (optional):** `uv run python -m engine gmail` stores a Gmail app password in your macOS Keychain. The listener
reads your inbox and never sends, labels or deletes anything.

**Warm leads (optional):** put LinkedIn's connections export at `data/contacts.csv`.

## Commands

```
daily | find | resolve | score | warm     the morning pipeline, or one step of it
listen | import <mail.json>               inbox → application statuses
fill <role id> [--dry-run]                fill an application in a visible browser; you submit
resume variants | tailor <id> | check <f>  honest resume variants and per-role PDFs
digest                                    this week in one page
gmail | token | schedule [off] | serve
```

In Claude Code: `/setup`, `/rank` (Claude re-reads your top 30 roles against your resume), and `/tailor <id>`
(rewords for one posting, checked line by line against your master resume). Your master resume lives at
`data/resume.json`: sections → entries (org, role, dates, bullets) → skill lines; `/setup` builds it from your PDF.

## Privacy

Everything personal lives in `data/`, which git ignores. The dashboard and the engine's API listen on
`127.0.0.1` only. The extension talks to the engine with a key only you have, and web pages never see it.
See the hosted [extension privacy notice](https://omar-colab.github.io/internship-engine/privacy.html).

## The shared feed

Every morning at 6:00 ET, GitHub reads every board in `boards.json` and publishes the postings (company, title,
location, link; nothing personal) at `site/feed.json` on the website. Your 7:00 run pulls it first, so a new
install starts with 900+ roles, and only boards not in the feed get polled from your laptop.
Found boards the feed doesn't have? `uv run python -m engine boards` adds them to `boards.json`; send a pull request.

## Add a company

Put it in `companies.json` with its careers page URL; the engine detects which job board it uses. Or just
save one of its postings with the extension.

## Contributing

Every module has a self-check (`uv run python -m engine.<module>`); CI runs them all. New job-board adapters go in
`engine/ats.py`: a lister, a detection pattern, and a self-check line.

MIT licensed. Not affiliated with JobRight or any job board.
