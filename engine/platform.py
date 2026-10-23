"""Small OS-specific integrations: credentials, scheduled jobs, and notifications."""
import html
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from . import db

ROOT = Path(__file__).resolve().parent.parent
KEYCHAIN = "internship-engine-gmail"
JOBS = ("daily", "listen", "digest")


def get_secret() -> tuple[str, str]:
    if sys_platform() == "darwin":
        acct = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN], capture_output=True, text=True).stdout
        import re
        match = re.search(r'"acct"<blob>="([^"]+)"', acct)
        password = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN, "-w"], capture_output=True, text=True).stdout.strip()
        return (match[1] if match else ""), password
    import keyring
    try:
        address = keyring.get_password(KEYCHAIN, "address")
        password = keyring.get_password(KEYCHAIN, "password")
    except keyring.errors.NoKeyringError:
        return "", ""
    return address or "", password or ""


def set_secret(address: str, password: str) -> None:
    if sys_platform() == "darwin":
        subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN, "-a", address, "-w", password], check=True)
    else:
        import keyring
        keyring.set_password(KEYCHAIN, "address", address)
        keyring.set_password(KEYCHAIN, "password", password)


def sys_platform() -> str:
    import sys
    return sys.platform


def plist_text(job: str, uv: str, root: str, logs: str) -> str:
    when = {"daily": {"StartCalendarInterval": {"Hour": 7, "Minute": 0}},
            "listen": {"StartInterval": 7200},
            "digest": {"StartCalendarInterval": {"Weekday": 0, "Hour": 18, "Minute": 0}}}[job]
    return plistlib.dumps({"Label": label(job), "ProgramArguments": [uv, "run", "python", "-m", "engine", job],
                           "WorkingDirectory": root, "StandardOutPath": f"{logs}/{job}.log",
                           "StandardErrorPath": f"{logs}/{job}.log", "RunAtLoad": False, **when}).decode()


def label(job: str) -> str:
    return f"com.internship-engine.{job}"


def systemd_text(job: str, uv: str, root: str) -> tuple[str, str]:
    service = f"[Unit]\nDescription=Internship Engine {job}\n\n[Service]\nType=oneshot\nWorkingDirectory={root}\nExecStart={uv} run python -m engine {job}\n"
    when = {"daily": "OnCalendar=*-*-* 07:00:00", "listen": "OnBootSec=5min\nOnUnitActiveSec=2h",
            "digest": "OnCalendar=Sun *-*-* 18:00:00"}[job]
    timer = f"[Unit]\nDescription=Internship Engine {job} timer\n\n[Timer]\n{when}\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"
    return service, timer


def task_xml(job: str, uv: str, root: str) -> str:
    schedule = {"daily": '<CalendarTrigger><StartBoundary>2026-01-01T07:00:00</StartBoundary><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>',
                "listen": '<TimeTrigger><Repetition><Interval>PT2H</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>2026-01-01T00:00:00</StartBoundary></TimeTrigger>',
                "digest": '<CalendarTrigger><StartBoundary>2026-01-04T18:00:00</StartBoundary><ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Sunday/></DaysOfWeek></ScheduleByWeek></CalendarTrigger>'}[job]
    return f'<?xml version="1.0" encoding="UTF-16"?><Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Triggers>{schedule}</Triggers><Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals><Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings><Actions Context="Author"><Exec><Command>{html.escape(uv)}</Command><Arguments>run python -m engine {job}</Arguments><WorkingDirectory>{html.escape(root)}</WorkingDirectory></Exec></Actions></Task>'


def schedule_install() -> list[str]:
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    logs = db.DATA / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    from . import listener
    try:
        listener.gmail_login()
        gmail = True
    except SystemExit:
        gmail = False
    done = []
    if sys_platform() == "darwin":
        agents = Path.home() / "Library/LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        for job in JOBS:
            if job == "listen" and not gmail: continue
            path = agents / f"{label(job)}.plist"
            path.write_text(plist_text(job, uv, str(ROOT), str(logs)))
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
            subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], check=True)
            done.append(label(job))
    elif sys_platform() == "linux":
        unitdir = Path.home() / ".config/systemd/user"
        unitdir.mkdir(parents=True, exist_ok=True)
        jobs = [job for job in JOBS if job != "listen" or gmail]
        for job in jobs:
            service, timer = systemd_text(job, uv, str(ROOT))
            (unitdir / f"internship-engine-{job}.service").write_text(service)
            (unitdir / f"internship-engine-{job}.timer").write_text(timer)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        for job in jobs:
            subprocess.run(["systemctl", "--user", "enable", "--now", f"internship-engine-{job}.timer"], check=True)
            done.append(job)
    elif sys_platform() == "win32":
        for job in JOBS:
            if job == "listen" and not gmail: continue
            path = Path(os.environ.get("TEMP", str(Path.home()))) / f"internship-engine-{job}.xml"
            path.write_text(task_xml(job, uv, str(ROOT)), encoding="utf-16")
            subprocess.run(["schtasks", "/Create", "/F", "/TN", f"Internship Engine {job}", "/XML", str(path)], check=True)
            path.unlink()
            done.append(job)
    return done


def schedule_remove() -> list[str]:
    done = []
    if sys_platform() == "darwin":
        agents = Path.home() / "Library/LaunchAgents"
        for job in JOBS:
            path = agents / f"{label(job)}.plist"
            if path.exists():
                subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
                path.unlink(); done.append(label(job))
    elif sys_platform() == "linux":
        unitdir = Path.home() / ".config/systemd/user"
        for job in JOBS:
            subprocess.run(["systemctl", "--user", "disable", "--now", f"internship-engine-{job}.timer"], capture_output=True)
            for suffix in ("service", "timer"):
                path = unitdir / f"internship-engine-{job}.{suffix}"
                if path.exists(): path.unlink(); done.append(job)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    elif sys_platform() == "win32":
        for job in JOBS:
            result = subprocess.run(["schtasks", "/Delete", "/F", "/TN", f"Internship Engine {job}"], capture_output=True)
            if result.returncode == 0: done.append(job)
    return sorted(set(done))


def notify(title: str, text: str) -> None:
    if sys_platform() == "darwin" and shutil.which("osascript"):
        subprocess.run(["osascript", "-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
                        "-e", "end run", text, title], capture_output=True)
    elif sys_platform() == "linux" and shutil.which("notify-send"):
        subprocess.run(["notify-send", "--", title, text], capture_output=True)
    elif sys_platform() == "win32" and shutil.which("powershell"):
        script = "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] > $null; $xml=New-Object Windows.Data.Xml.Dom.XmlDocument; $xml.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>" + html.escape(title) + "</text><text>" + html.escape(text) + "</text></binding></visual></toast>'); [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Internship Engine').Show((New-Object Windows.UI.Notifications.ToastNotification $xml))"
        subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)


def _selfcheck() -> None:
    for job in JOBS:
        plist = plist_text(job, "/uv", "/repo", "/logs")
        parsed = plistlib.loads(plist.encode())
        assert parsed["ProgramArguments"] == ["/uv", "run", "python", "-m", "engine", job]
        expected = {"daily": {"Hour": 7, "Minute": 0}, "listen": 7200,
                    "digest": {"Weekday": 0, "Hour": 18, "Minute": 0}}[job]
        assert (parsed["StartInterval"] if job == "listen" else parsed["StartCalendarInterval"]) == expected
        service, timer = systemd_text(job, "/uv", "/repo")
        assert "ExecStart=/uv run python -m engine " + job in service
        assert ("07:00:00" in timer if job == "daily" else "2h" in timer if job == "listen" else "Sun" in timer)
        task = task_xml(job, "/uv", "/repo")
        assert "<Command>/uv</Command>" in task and f"engine {job}" in task
        assert {"daily": "07:00:00", "listen": "PT2H", "digest": "<Sunday/>"}[job] in task
    calls = []
    actual = sys_platform, shutil.which, subprocess.run
    try:
        globals()["sys_platform"] = lambda: "darwin"
        shutil.which = lambda _: "/usr/bin/osascript"
        subprocess.run = lambda args, **kwargs: calls.append(args)
        notify("Internship Engine", 'Contoso"\ndo shell script "bad')
    finally:
        globals()["sys_platform"], shutil.which, subprocess.run = actual
    assert len(calls) == 1 and calls[0][-2:] == ['Contoso"\ndo shell script "bad', "Internship Engine"]
    assert not any('Contoso"' in arg for arg in calls[0][:-2])

    import tempfile
    from unittest.mock import patch
    import keyring
    import engine.platform as platform_module
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        with patch.object(platform_module, "sys_platform", return_value="linux"), \
             patch.object(platform_module.db, "DATA", home / "data"), \
             patch.object(Path, "home", return_value=home), \
             patch.object(platform_module.shutil, "which", return_value="/uv"), \
             patch.object(platform_module.subprocess, "run"), \
             patch.object(keyring, "get_password", side_effect=keyring.errors.NoKeyringError), \
             patch.dict(platform_module.os.environ, {"GMAIL_ADDRESS": "", "GMAIL_APP_PASSWORD": ""}):
            assert platform_module.schedule_install() == ["daily", "digest"]


if __name__ == "__main__":
    _selfcheck()
    print("ok")
