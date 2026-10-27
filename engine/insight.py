"""Per-posting insight: which skills it asks for that your resume shows (and which it doesn't), and the pay.

Keyword-overlap "match scores" are what Teal and Jobscan sell; here the gaps are shown, never written into your
resume. A gap is something to learn, or a reason to skip the role, not a word to paste in.
"""
import re

# Skills and tools postings ask for by name. Matched as whole words/phrases, case-insensitive.
SKILLS = [
    "python", "sql", "r", "sas", "spss", "stata", "excel", "vba", "powerpoint", "word", "google sheets", "tableau", "power bi",
    "looker", "alteryx", "snowflake", "databricks", "dbt", "aws", "azure", "gcp", "salesforce", "hubspot", "sap", "oracle",
    "servicenow", "jira", "confluence", "figma", "git", "javascript", "java", "c++", "swift", "html", "api",
    "etl", "machine learning", "deep learning", "generative ai", "llm", "prompt engineering", "nlp", "computer vision",
    "a/b testing", "statistics", "regression", "forecasting", "financial modeling", "valuation", "data visualization",
    "data cleaning", "dashboards", "automation", "process improvement", "lean", "six sigma", "agile", "scrum",
    "project management", "change management", "stakeholder management", "market research", "due diligence",
    "competitive analysis", "crm", "erp", "google ads", "seo", "public speaking", "presentation", "writing",
]
PAY = re.compile(r"\$\s?(\d{2,3}(?:[.,]\d{1,2})?)\s?(k)?\s?(?:/\s?(?:hr|hour|yr|year)|per\s+(?:hour|year))?\s*(?:-|–|to)\s*\$?\s?(\d{2,3}(?:[.,]\d{1,2})?)\s?(k)?\s?(/\s?(?:hr|hour|yr|year)|per\s+(?:hour|year)|hourly|an hour|annually)?", re.I)


def _has(skill: str, text: str) -> bool:
    stem = re.escape(skill[:-1] if skill.endswith("s") and len(skill) > 4 else skill)      # dashboard ↔ dashboards
    return bool(re.search(rf"(?<![a-z0-9]){stem}s?(?![a-z0-9])", text, re.I))


def keywords(description: str, resume: str) -> dict:
    asked = [s for s in SKILLS if _has(s, description or "")]
    have = [s for s in asked if _has(s, resume)]
    return {"asked": asked, "have": have, "missing": [s for s in asked if s not in have],
            "coverage": round(100 * len(have) / len(asked)) if asked else None}


def pay(description: str) -> str | None:
    """'$35-40 per hour' → '$35–40/hr'. None when the posting doesn't say."""
    m = PAY.search(description or "")
    if not m:
        return None
    lo, k1, hi, k2, unit = m.groups()
    lo, hi = (re.sub(r"[.,]00$", "", x) for x in (lo, hi))
    unit = (unit or "").lower()
    yearly = bool(k1 or k2) or "yr" in unit or "year" in unit or "annual" in unit
    k = "K" if k1 or k2 else ""
    return f"${lo}{k}{'' if lo == hi else f'–{hi}{k}'}/{'yr' if yearly else 'hr'}"


if __name__ == "__main__":
    k = keywords("Use SQL, Tableau and Power BI; Java a plus. Strong presentation skills.", "SQL and Tableau dashboards; presentation")
    assert k["have"] == ["sql", "tableau", "presentation"] and k["missing"] == ["power bi", "java"], k
    assert keywords("", "x")["coverage"] is None
    assert not _has("r", "our team works remotely")            # "r" only as a word
    assert _has("dashboards", "built a dashboard") and _has("presentation", "presentations")
    assert pay("Compensation will be set at an hourly rate of $35-40 per hour.") == "$35–40/hr"
    assert pay("$20/hr - $34/hr in Cary") == "$20–34/hr"
    assert pay("$54K/yr - $81K/yr") == "$54K–81K/yr"
    assert pay("No pay info") is None
    assert pay("$36.00 - $36.00 per hour") == "$36/hr" and pay("$19.13 - $34.17 per hour") == "$19.13–34.17/hr"
    print("ok")
