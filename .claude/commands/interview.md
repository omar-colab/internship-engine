---
description: Prepare for an interview: likely questions from the posting, answers built from your real experience
argument-hint: <role id>
---
1. Read the role (`sqlite3 data/engine.db "select company, title, description from roles where id=$ARGUMENTS"`),
   `data/resume.json`, and any `data/notes/*.md` about the company.
2. Write `data/interviews/$ARGUMENTS.md` with:
   - **What they'll test:** the 4–5 skills or traits the posting stresses, in its own words.
   - **Likely questions:** 8 (3 behavioral, 3 role-specific, 2 "why us / why this team").
   - **Your stories:** for each behavioral question, a STAR outline built from ONE resume bullet. Situation, Task, Action,
     Result, with only the facts and numbers the bullet has. Mark where the person should add a detail only they know.
   - **Gaps to own:** skills the posting names that the resume doesn't show (see the dashboard's skills panel), with an honest
     one-line answer for each ("I haven't used X yet; here's the closest thing I've done").
   - **Questions to ask them:** 3, specific to this team.
3. Offer a mock interview: ask one question at a time, wait for the answer, give one line of feedback.
