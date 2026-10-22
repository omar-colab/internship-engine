---
description: Reword your resume for one role, honestly (every line must trace to your master)
argument-hint: <role id>
---
Tailor the resume for role $ARGUMENTS.

1. `uv run python -m engine resume tailor $ARGUMENTS` (reorders only; writes `data/resumes/$ARGUMENTS.json` and `.pdf`).
2. Read the posting: `sqlite3 data/engine.db "select company, title, description from roles where id=$ARGUMENTS"`.
3. In `data/resumes/$ARGUMENTS.json`, you MAY reword a bullet to use the posting's language for something the bullet
   already says (e.g. "workflow" → "process" when that's what it was). You MAY NOT add a number, tool, employer,
   result, or skill that isn't in `data/resume.json`. Don't touch names, roles or dates.
4. Run `uv run python -m engine resume check data/resumes/$ARGUMENTS.json`. If it reports any problem, undo that
   change. Repeat until it says `"honest": true`.
5. Show the person every reworded line, before → after. Only on their yes, render it:
   `uv run python -c "import json; from engine import resume; resume.render(json.load(open('data/resumes/$ARGUMENTS.json')), resume.OUT / '$ARGUMENTS.pdf')"`
