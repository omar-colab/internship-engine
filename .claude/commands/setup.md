---
description: Set up Internship Engine for a new user, from their resume to the first ranked list
---
Set up the Internship Engine for the person you're talking to. Keep it to about ten minutes and do the work yourself.

1. Create `data/`. Ask for their resume (a PDF path). Extract its text to `data/resume.txt` and copy the PDF to `data/resume.pdf`
   (`uv run --with pypdf python -c ...`; read the PDF's link annotations too, for their LinkedIn URL).
2. Copy `resume.example.json` to `data/resume.json`, then fill it in, preserving the sections → entries → bullets and skill lines
   structure. Keep the person's wording, employers, roles, dates, skills, and numbers faithful to the PDF; ask about
   anything unclear instead of filling gaps. Show them the extracted version and get their corrections.
3. Build `data/profile.json` from `profile.example.json`. Every value must come from the resume or from their answer:
   name, email, phone, LinkedIn, city/state, school (and a short name), degree, major, graduation (YYYY-MM),
   class standing, strengths (distinctive skills that appear on the resume), and a one-sentence `hook`
   (a true sentence from the resume, under 80 characters). Never add a skill, number or claim that isn't there.
   If the degree line doesn't match the major they're enrolled in, stop and ask them to fix the resume first.
4. Ask, in one message: tracks they want (from the three in the example, or suggest a fourth), locations, whether
   they're open to relocating, work authorization (US citizen / permanent resident / needs sponsorship), and how they
   want self-identification questions answered (default: decline). Write the answers into the profile.
5. Run `uv run python -m engine daily` and show the top 10 roles by fit with their reasons. Ask if 8 of 10 are roles
   they'd apply to; if not, adjust `tracks`/`strengths` and rescore with `uv run python -m engine score`.
6. Start the dashboard (`uv run python -m engine serve`), run `uv run python -m engine schedule`, and walk them through
   the Chrome extension: chrome://extensions → Developer mode → Load unpacked → the `extension` folder → paste the
   token from `uv run python -m engine token`.
7. Optional: Gmail app password (`uv run python -m engine gmail`, they type it themselves) and the LinkedIn
   connections export at `data/contacts.csv` for the warm lane.

Everything personal stays in `data/`, which git ignores. Never commit it, never send it anywhere.
