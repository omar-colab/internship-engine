# Working on this repo (for Codex, Claude Code, and humans)

Two AI agents build this project in parallel: **Codex** (PRs from `codex/*` branches) and **Claude Code** (commits on
`main`). This file is how we stay out of each other's way. Read it before every task.

## How work is handed out

- Tasks for Codex are **GitHub issues labeled `codex`**. Take the oldest open one labeled `priority` first, then the oldest open one.
  Comment on the issue when you start, open a PR that says `Closes #N`, and keep one issue per PR.
- Claude Code works on whatever isn't claimed by an open `codex` issue. Issues labeled `claude` are Claude Code's.
- A PR labeled `changes-requested` has a review comment from Claude Code. Fix that before starting anything new,
  then remove the label in the same push. Claude Code and Codex share one GitHub account, so reviews arrive as comments.
- Found something outside your task? Open an issue instead of fixing it in your PR.

## Who owns what (so two agents never edit the same file at once)

| Area | Owner | Files |
|------|-------|-------|
| Scoring, eligibility, answers, resumes, insight | Claude Code | `engine/score.py`, `engine/answers.py`, `engine/resume.py`, `engine/insight.py`, `engine/warm.py` |
| Dashboard | Claude Code | `web/index.html`, `engine/server.py` |
| Form reading/filling (Python) | Claude Code | `engine/fill.py`, `engine/read_form.py` |
| Job-board adapters | **Codex** (while a `codex` adapter issue is open) | `engine/ats.py` (add functions + self-check lines; don't reorder existing code) |
| Extension packaging, store listing, release workflow | **Codex** | `extension/manifest.json`, `extension/README.md`, `.github/workflows/extension-release.yml`, `docs/CHROME_WEB_STORE.md` |
| Extension test harness | **Codex** | `tests/`, `tests/fixtures/` |
| Cross-platform setup (Linux/Windows) | **Codex** | `engine/schedule.py`, `engine/platform.py` (new) |
| Shared feed and boards | either; coordinate in the issue | `engine/shared.py`, `boards.json`, `.github/workflows/site.yml` |
| Website | either | `site/` |

Need to touch a file you don't own? Say so in the issue and keep the change minimal.

## Rules that never bend

1. **No personal data, ever.** Nothing from `data/` gets committed, printed in a PR, or pasted in an issue. Test data is
   fictional: Contoso, Northwind, Fabrikam, Tailspin, Litware, Adatum, Wide World Importers. Never use a real
   person's name, email, phone, school, or the companies someone actually applied to.
2. **Commit as** `272296338+omar-colab@users.noreply.github.com`, never a personal address:
   `git config user.email "272296338+omar-colab@users.noreply.github.com"`.
3. **The product never clicks Submit, never presses Enter in a form, never guesses an answer, never solves a CAPTCHA,
   never automates LinkedIn, never sends a message.** Anything that would cross one of these lines is out of scope.
4. **No decompiling or copying another product's code** (JobRight, Simplify, Teal, Huntr…). Build from public behavior
   and public APIs only. If a site answers automated requests with 403 or a bot wall, stop; don't evade it.
5. **Every module keeps its self-check.** New logic gets one assert-based check in its `__main__` / `_selfcheck`.
   CI runs `.github/workflows/check.yml`; add your module there.
6. **Rebase on `main` before you push**, and keep PRs small.
7. **Match the code around you:** standard library first, plain functions, short comments that say *why*.

## Running things

```sh
uv sync && uv run playwright install chromium
for m in engine.ats engine.feed engine.finder engine.listener engine.resolve engine.score engine.warm \
         engine.answers engine.report engine.resume engine.shared engine.insight engine.server; do uv run python -m $m; done
uv run python -m engine.fill --selfcheck
```

Network-dependent checks belong in a manual script, not in a module's self-check.
