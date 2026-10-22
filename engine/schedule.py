"""Run the engine on a timer with launchd (macOS). Laptop asleep = the run waits until it wakes.

    uv run python -m engine schedule        # install: daily at 7:00, inbox every 2 hours
    uv run python -m engine schedule off    # remove both
"""
import plistlib
import shutil
import subprocess
from pathlib import Path

from . import db

ROOT = Path(__file__).resolve().parent.parent
AGENTS = Path.home() / "Library/LaunchAgents"
JOBS = {
    "daily": {"StartCalendarInterval": {"Hour": 7, "Minute": 0}},
    "listen": {"StartInterval": 7200},
    "digest": {"StartCalendarInterval": {"Weekday": 0, "Hour": 18, "Minute": 0}},    # Sunday evening
}


def label(job: str) -> str:
    return f"com.internship-engine.{job}"


def install() -> list[str]:
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    logs = db.DATA / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    done = []
    for job, when in JOBS.items():
        if job == "listen" and not _has_gmail():
            continue                                  # added by the next `schedule` after `engine gmail`
        plist = AGENTS / f"{label(job)}.plist"
        plistlib.dump({"Label": label(job), "ProgramArguments": [uv, "run", "python", "-m", "engine", job],
                       "WorkingDirectory": str(ROOT), "StandardOutPath": str(logs / f"{job}.log"),
                       "StandardErrorPath": str(logs / f"{job}.log"), "RunAtLoad": False, **when}, plist.open("wb"))
        subprocess.run(["launchctl", "bootout", f"gui/{_uid()}", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{_uid()}", str(plist)], check=True)
        done.append(label(job))
    return done


def remove() -> list[str]:
    done = []
    for job in JOBS:
        plist = AGENTS / f"{label(job)}.plist"
        if plist.exists():
            subprocess.run(["launchctl", "bootout", f"gui/{_uid()}", str(plist)], capture_output=True)
            plist.unlink()
            done.append(label(job))
    return done


def _has_gmail() -> bool:
    from . import listener
    try:
        listener.gmail_login()
        return True
    except SystemExit:
        return False


def _uid() -> int:
    import os
    return os.getuid()
