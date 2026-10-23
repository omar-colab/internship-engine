"""Build a fictional tracker for Chrome Web Store screenshots."""
import argparse
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


COMPANIES = ("Contoso", "Northwind", "Fabrikam", "Tailspin", "Litware", "Adatum", "Wide World Importers")
STAGES = ("submitted", "submitted", "submitted", "assessment", "assessment", "interview", "offer", "rejected")
TITLES = ("AI Strategy Intern", "Business Analyst Intern", "Data Analytics Intern", "Digital Transformation Intern",
          "Product Operations Intern", "Technology Consulting Intern", "Market Insights Intern", "Automation Intern")
DESCRIPTION = ("Join our internship team to support AI strategy, process automation, and data analysis. "
               "Work with Python, SQL, Tableau, dashboards, and client teams. Graduation in 2027 or 2028. "
               "Compensation is $35-40 per hour.")


def build(directory: Path) -> Path:
    if directory.exists() and any(directory.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty demo directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)

    # Import after setting the override so the engine can never touch the user's data directory.
    import os
    os.environ["INTERNSHIP_ENGINE_DATA"] = str(directory)
    from engine import db

    con = db.connect()
    p = {"first_name": "Sample", "last_name": "Applicant", "graduation": "2028-05", "degree_level": "bachelors",
         "class_standing": "junior", "open_to": [], "work_authorization": "authorized",
         "tracks": ["ai-consulting", "transformation", "data-analytics"],
         "strengths": ["python", "sql", "tableau", "consulting", "ai", "automation"], "locations": ["CT", "NY", "Remote"],
         "resume": "data/resume.txt", "resume_pdf": "data/resume.pdf"}
    (directory / "profile.json").write_text(json.dumps(p, indent=2) + "\n")
    (directory / "resume.txt").write_text("Sample Applicant\nSkills: Python, SQL, Tableau, analytics, consulting, automation.\n")

    ids = []
    for i in range(40):
        company = COMPANIES[i % len(COMPANIES)]
        title = TITLES[i % len(TITLES)]
        city = ("Stamford, CT", "New York, NY", "Remote")[i % 3]
        url = f"https://careers.{company.lower().replace(' ', '')}.example/roles/{i + 1}"
        db.upsert_role(con, {"key": url, "company": company, "title": title, "location": city, "work_model": "Hybrid",
                             "url": url, "source": "greenhouse", "ats": "greenhouse", "track": ("ai-consulting", "transformation", "data-analytics")[i % 3],
                             "found_on": (date.today() - timedelta(days=i % 10)).isoformat(), "description": DESCRIPTION,
                             "homepage": None, "posted": None})
        row = con.execute("select id from roles where key = ?", (url,)).fetchone()
        ids.append(row["id"])
        status = STAGES[i] if i < len(STAGES) else ("queued" if i < 12 else "new")
        con.execute("update roles set status = ?, fit = ?, fit_why = ?, eligible = 1, track = ?, pay = '$35–40/hr', keywords = ? where id = ?",
                    (status, 5 - i % 3, "AI consulting role · Python and SQL experience · in your area",
                     ("ai-consulting", "transformation", "data-analytics")[i % 3],
                     json.dumps({"asked": ["python", "sql", "tableau", "automation"], "have": ["python", "sql", "tableau"], "missing": ["automation"], "coverage": 75}), row["id"]))
        if i < len(STAGES):
            applied = (date.today() - timedelta(days=2 + i)).isoformat()
            con.execute("update roles set applied_on = ?, applied_by = 'you' where id = ?", (applied, row["id"]))
            con.execute("insert into events (role_id, at, type, summary) values (?, ?, 'note', ?)",
                        (row["id"], f"{applied} 10:00:00", f"Moved to {status}"))

    for name, company, status in (("Contoso Alumni Contact", "Contoso", "to_message"),
                                  ("Northwind Team Contact", "Northwind", "messaged"),
                                  ("Fabrikam Team Contact", "Fabrikam", "replied")):
        con.execute("insert into contacts (name, company, title, notes, status, source) values (?, ?, ?, ?, ?, 'manual')",
                    (name, company, "University Recruiting", "Fictional demo contact", status))
    con.execute("insert into runs (job, started, found, new) values ('find', datetime('now'), 40, 40)")
    con.execute("insert into runs (job, started, found, new) values ('listen', datetime('now'), 3, 0)")
    con.commit()
    # A prepared preview for the first queued role, using only placeholder answers.
    prep = {"filled": 2, "fields": 3, "answers": [
        {"label": "First Name", "result": "filled", "answer": "Sample"},
        {"label": "Last Name", "result": "filled", "answer": "Applicant"},
        {"label": "Why do you want to join Contoso?", "result": "needs_you", "suggest": ["I am interested in the role."], "options": []}]}
    prep_dir = directory / "prep"
    prep_dir.mkdir(exist_ok=True)
    (prep_dir / f"{ids[8]}.json").write_text(json.dumps(prep, indent=2) + "\n")
    con.close()
    return directory


def _selfcheck() -> None:
    with tempfile.TemporaryDirectory(prefix="ie-demo-check-") as tmp:
        path = build(Path(tmp) / "data")
        import os
        os.environ["INTERNSHIP_ENGINE_DATA"] = str(path)
        from engine import db
        con = db.connect()
        assert con.execute("select count(*) from roles").fetchone()[0] == 40
        assert con.execute("select count(*) from roles where status in ('submitted','assessment','interview','offer','rejected')").fetchone()[0] == 8
        assert con.execute("select count(*) from contacts").fetchone()[0] == 3
        assert {r[0] for r in con.execute("select distinct company from roles")} <= set(COMPANIES)
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _selfcheck()
        print("ok")
    else:
        target = args.data_dir or Path(tempfile.mkdtemp(prefix="internship-engine-store-")) / "data"
        print(build(target))
