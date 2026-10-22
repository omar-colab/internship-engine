---
description: Write a short cover letter for one role, only from your resume (honesty-checked)
argument-hint: <role id>
---
Only write one if the application asks for it; most internship forms don't, and a weak letter hurts.

1. Read the role: `sqlite3 data/engine.db "select company, title, description from roles where id=$ARGUMENTS"`, and `data/resume.json`.
2. Write at most 180 words to `data/covers/$ARGUMENTS.txt`: why this role (from the posting's words), two proofs (each one a
   bullet from the resume, in your own words, with its real numbers), and a one-line close. No flattery, no "I am passionate".
3. Run `uv run python -m engine resume check-text data/covers/$ARGUMENTS.txt`. Fix every problem it reports by cutting the
   claim or replacing it with something the resume actually says. Repeat until `"honest": true`.
4. Show it to the person. Never send it or attach it yourself.
