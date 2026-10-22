"""Finder: shared feed + every company's own board → new rows in roles.

    uv run python -m engine find
"""
import json
import re
from pathlib import Path

from . import ats, db, feed

SEED = Path(__file__).resolve().parent.parent / "companies.json"
STATES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC "
          "ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()
US = re.compile(r"\bUSA?\b|\b(" + "|".join(STATES) + r")\b")      # case-sensitive: "IN" is Indiana, "in" isn't
FOREIGN = re.compile(r"emea|apac|latam|canada|brazil|brasil|mexico|méxico|united kingdom|\buk\b|england|ireland|germany|france|spain|"
                     r"italy|poland|netherlands|india|china|japan|korea|singapore|philippines|australia|morocco|"
                     r"egypt|turkey|türkiye|uae|dubai|israel|south africa|argentina|colombia|chile|romania|hungary|"
                     r"czech|portugal|switzerland|sweden|belgium|austria|vietnam|malaysia|indonesia|thailand")


def in_us(location: str | None) -> bool:
    """ponytail: US + remote only; make it a per-user setting when a friend outside the US joins."""
    if not location:
        return True
    low = location.lower()
    if "united states" in low or US.search(location):
        return True
    return not FOREIGN.search(low)                  # bare "Chicago" stays; "Casablanca, Morocco" / "EMEA - Remote" go


def board_for(con, c: dict) -> tuple[str, dict] | None:
    """Known board from the seed, else a cached detection, else detect now and cache it."""
    if "board" in c:
        b = dict(c["board"])
        return b.pop("ats"), b
    row = con.execute("select ats, board from companies where name = ?", (c["name"],)).fetchone()
    if row:
        return (row["ats"], json.loads(row["board"])) if row["ats"] else None
    found = ats.detect(c["careers_url"]) if c.get("careers_url") else None
    con.execute("insert or replace into companies values (?, ?, ?, ?)",
                (c["name"], c.get("careers_url"), found and found[0], found and json.dumps(found[1])))
    return found


def run() -> dict:
    con = db.connect()
    found = new = 0
    errors: list[str] = []
    seed = json.loads(SEED.read_text())["companies"]
    from . import shared
    pulled = shared.pull_feed()                    # fresh shared feed → no need to poll the boards it covers
    covered = set(pulled["covered"]) if pulled else set()
    for r in pulled["roles"] if pulled else []:
        found += 1
        new += db.upsert_role(con, {**r, "key": r["url"], "source": r["ats"]})
    seed = [c for c in seed if c["name"] not in covered]
    seed += [{"name": b["name"], "board": {k: v for k, v in b.items() if k != "name"}} for b in shared.load_boards()
             if b["name"] not in covered and b["name"] not in {c["name"] for c in seed}]
    names = {c["name"] for c in seed} | covered
    # the list grows itself: every company whose board the resolver found is polled directly from now on
    learned = [{"name": r["name"], "board": {"ats": r["ats"], **json.loads(r["board"])}}
               for r in con.execute("select name, ats, board from companies where ats is not null and board is not null")
               if r["name"] not in names]
    for c in seed + learned:
        try:
            b = board_for(con, c)
            if not b:
                errors.append(f"{c['name']}: no job board detected")
                continue
            for r in ats.LIST[b[0]](c["name"], b[1]):
                if not in_us(r["location"]):
                    continue
                r["track"] = feed.track(r["title"])
                found += 1
                new += db.upsert_role(con, r)
        except Exception as e:                     # one broken board never stops the run
            errors.append(f"{c['name']}: {e}")
    try:
        for r in feed.build():
            if not in_us(r["location"]):
                continue
            found += 1
            # the employer's own board already has it (with a real apply URL) → skip the list copy
            if con.execute("select 1 from roles where lower(company) = lower(?) and lower(title) = lower(?) and source not like 'jobright:%'",
                           (r["company"], r["title"])).fetchone():
                continue
            new += db.upsert_role(con, {**r, "key": feed.dedupe_key(r)})
            con.execute("update roles set homepage = ? where key = ? and homepage is null", (r["homepage"], feed.dedupe_key(r)))
    except Exception as e:
        errors.append(f"feed: {e}")
    con.commit()
    db.log_run(con, "find", found, new, errors)
    return {"found": found, "new": new, "errors": errors}


def _selfcheck() -> None:
    for ok in ("Stamford, CT", "Boston, MA, United States", "Remote", "Hartford Connecticut USA", None, "Chicago"):
        assert in_us(ok), ok
    for bad in ("Vancouver, BC, Canada", "São Paulo, Brazil", "Casablanca,Morocco", "EMEA - Remote", "Office - Hyderabad, India"):
        assert not in_us(bad), bad


if __name__ == "__main__":
    _selfcheck()
    print("ok")
