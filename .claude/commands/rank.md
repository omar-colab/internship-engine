---
description: Re-rank the top roles by actually reading them against the resume
---
The pattern scorer is fast but shallow. Read the 30 highest-fit new roles and judge them properly.

1. `sqlite3 data/engine.db "select id, company, title, fit, fit_why, substr(description,1,2500) from roles where status='new' and coalesce(eligible,1)>0 order by fit desc limit 30"`
2. Read `data/resume.txt`. For each role, decide a fit from 1 to 5 using only what the resume shows and what the
   posting asks for. Note any hard requirement the resume can't meet (a degree, a language, citizenship, a tool).
3. Show the person a table: role, old fit, your fit, one-line reason. Ask before writing anything.
4. On their yes, write the changes:
   `sqlite3 data/engine.db "update roles set fit = <n>, fit_why = '<reason, claude-read>' where id = <id>"`
   (escape single quotes). Your reason must not claim anything the resume doesn't say.
