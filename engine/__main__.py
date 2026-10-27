"""uv run python -m engine <command>

  daily              find → expire → resolve → score → warm (what the 7:00 run does)
  find | expire | resolve | score | warm    one step
  listen             read the inbox over IMAP (read-only) and update statuses
  import <mail.json> same, from emails Claude pulled with its Gmail connector
  gmail              save a Gmail app password to the OS credential store
  schedule [off]     install / remove the OS scheduled jobs
  fill <id> [--dry-run]   open the posting, fill what your profile backs, stop before Submit
  digest             this week in one page (data/digest/) + a notification; Sundays at 18:00 when scheduled
  resume variants | tailor <id> | check <file.json> | check-text <file.txt>   honest resumes and cover letters
  boards             share the job boards you've found: writes boards.json
  feed-build         build the shared daily feed (GitHub Actions runs this)
  token              the key to paste into the browser extension's settings
  serve              dashboard at http://127.0.0.1:8765
"""
import json
import sys

from . import db, expire, finder, listener, resolve, schedule, score, server, warm

cmd, args = (sys.argv[1] if len(sys.argv) > 1 else "serve"), sys.argv[2:]
out = lambda x: print(json.dumps(x, indent=1))
if cmd == "daily":
    out({"find": finder.run(), "expire": expire.run(), "resolve": resolve.run(), "score": score.run(), "warm": warm.run()})
    from . import report
    report.new_match_alert()
elif cmd in ("find", "expire", "resolve", "score", "warm"):
    out({"find": finder, "expire": expire, "resolve": resolve, "score": score, "warm": warm}[cmd].run())
elif cmd == "listen":
    recent = db.connect().execute("select 1 from runs where job = 'listen' and started > datetime('now', '-3 days')").fetchone()
    out(listener.run(listener.fetch_imap(days=3 if recent else 14)))   # every 2h: just the new mail; after a gap: catch up
elif cmd == "import":
    out(listener.run(json.loads(open(args[0]).read())))
elif cmd == "gmail":
    listener.save_gmail_login()
elif cmd == "schedule":
    out({"removed": schedule.remove()} if args[:1] == ["off"] else {"installed": schedule.install()})
elif cmd == "fill":
    from . import fill
    dry = "--dry-run" in args
    r = fill.prep(int(args[0]), headed=not dry, upload=not dry)
    out({k: r[k] for k in ("fields", "filled", "needs_you") if k in r} | ({"blocked": r["blocked"]} if "blocked" in r else {}))
elif cmd == "digest":
    from . import report
    print(report.digest())
elif cmd == "resume":
    from . import resume
    sub = args[0] if args else "variants"
    if sub == "check-text":
        problems = resume.check_text(resume.master(), open(args[1]).read())
        out({"honest": not problems, "problems": problems})
    elif sub == "check":
        problems = resume.check(resume.master(), json.loads(open(args[1]).read()))
        out({"honest": not problems, "problems": problems})
    else:
        out(resume.variants() if sub == "variants" else resume.tailor(int(args[1])))
elif cmd in ("boards", "feed-build"):
    from . import shared
    out(shared.export_boards() if cmd == "boards" else shared.build_feed(shared._previous_feed()))
elif cmd == "token":
    print(server.token())
elif cmd == "serve":
    server.serve()
else:
    sys.exit(__doc__)
