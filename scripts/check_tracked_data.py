#!/usr/bin/env python3
"""Reject personal data and unexpected email addresses in tracked files."""

import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
EMAIL = re.compile(
    rb"[A-Z0-9.!#$%&'*+/=?^_{|}~-]+@"
    rb"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    rb"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+",
    re.IGNORECASE,
)
ALLOWED_EMAIL = "272296338+omar-colab@users.noreply.github.com"
ALLOWED_DOMAINS = {
    "example.com",
    "contoso.com",
    "northwind.com",
    "fabrikam.com",
    "tailspin.com",
    "litware.com",
    "adatum.com",
    "wideworldimporters.com",
}
RESTRICTED_SUFFIXES = {".db", ".pdf", ".png"}
RESTRICTED_FILE_PREFIXES = ("site/", "extension/", "tests/fixtures/")


def path_violations(path: str) -> list[str]:
    violations = []
    if path == "data" or path.startswith("data/"):
        violations.append("tracked under data/")
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in RESTRICTED_SUFFIXES and not path.startswith(RESTRICTED_FILE_PREFIXES):
        violations.append(f"{suffix} outside allowed fixture/site/extension paths")
    return violations


def has_unapproved_email(contents: bytes) -> bool:
    for match in EMAIL.finditer(contents):
        address = match.group().decode("ascii").lower()
        if address == ALLOWED_EMAIL:
            continue
        domain = address.rsplit("@", 1)[1]
        if domain in ALLOWED_DOMAINS or domain.endswith(".example"):
            continue
        if domain.endswith(".example.com"):
            continue
        return True
    return False


def self_check() -> None:
    assert path_violations("data/profile.json") == ["tracked under data/"]
    assert path_violations("extension/icon.png") == []
    assert path_violations("resume.pdf") == [".pdf outside allowed fixture/site/extension paths"]
    assert not has_unapproved_email(b"272296338+omar-colab@users.noreply.github.com")
    assert not has_unapproved_email(b"person@northwind.com person@jobs.example")
    assert not has_unapproved_email(b"person@mail.example.com")
    assert has_unapproved_email(b"person@" + b"unapproved.test")
    assert not has_unapproved_email(b"uses: actions/checkout@v7")
    assert not has_unapproved_email(b"font: opsz@9..96")


def main() -> int:
    if sys.argv[1:] == ["--self-check"]:
        self_check()
        print("tracked-data guard self-check passed")
        return 0
    if sys.argv[1:]:
        print("usage: check_tracked_data.py [--self-check]", file=sys.stderr)
        return 2

    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    failures = []
    for raw_path in paths:
        if not raw_path:
            continue
        path = os.fsdecode(raw_path)
        reasons = path_violations(path)
        if reasons:
            failures.extend((path, reason) for reason in reasons)
            continue
        file_path = ROOT / path
        if file_path.is_symlink() or not file_path.is_file():
            continue
        try:
            if has_unapproved_email(file_path.read_bytes()):
                reasons.append("unapproved email address")
        except OSError:
            reasons.append("could not read tracked file")
        failures.extend((path, reason) for reason in reasons)

    if failures:
        for path, reason in failures:
            print(f"{path}: {reason}")
        return 1
    print("tracked-data guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
