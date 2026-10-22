#!/usr/bin/env python3
"""Create and verify a release ZIP from tracked extension files only."""

import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}\Z")


def _inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _source_files(extension: Path, names: list[str]) -> list[tuple[str, Path]]:
    files = []
    extension_root = extension.resolve()
    for name in sorted(set(names)):
        parts = name.split("/")
        if (
            not name
            or "\\" in name
            or ":" in parts[0]
            or any(part in ("", ".", "..") for part in parts)
        ):
            raise ValueError("invalid extension path")
        if "data" in parts:
            raise ValueError("extension package contains a forbidden data path")
        if any(part.startswith(".") for part in parts) or parts[-1] == "README.md":
            continue

        source = extension
        for part in parts:
            source /= part
            if source.is_symlink():
                raise ValueError("extension package contains a symlink")
        if not source.is_file() or not source.resolve().is_relative_to(extension_root):
            raise ValueError("extension package contains an invalid source file")
        files.append(("/".join(parts), source))
    return files


def _validate_members(names: list[str], expected: set[str]) -> None:
    if len(names) != len(set(names)):
        raise ValueError("extension ZIP contains duplicate paths")
    for name in names:
        parts = name.split("/")
        if (
            not name
            or name.startswith("/")
            or "\\" in name
            or ":" in parts[0]
            or any(part in ("", ".", "..") or part.startswith(".") for part in parts)
            or "data" in parts
        ):
            raise ValueError("extension ZIP contains a forbidden path")
    if set(names) != expected or "manifest.json" not in expected:
        raise ValueError("extension ZIP contents do not match tracked extension files")


def package(extension: Path, output: Path, version: str, tracked_names: list[str]) -> None:
    if not VERSION.fullmatch(version):
        raise ValueError("tag version is invalid")
    files = _source_files(extension, tracked_names)
    manifests = {name: path.read_bytes() for name, path in files if name == "manifest.json"}
    if len(manifests) != 1:
        raise ValueError("extension package must contain one manifest.json")
    manifest = json.loads(next(iter(manifests.values())))
    if not isinstance(manifest, dict):
        raise ValueError("extension manifest must be a JSON object")
    if manifest.get("version") != version:
        raise ValueError("tag version does not match manifest version")
    if manifest.get("manifest_version") != 3:
        raise ValueError("extension manifest version must be 3")

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, source in files:
            archive.write(source, name)

    with zipfile.ZipFile(output) as archive:
        _validate_members(archive.namelist(), {name for name, _ in files})
        archived_manifest = json.loads(archive.read("manifest.json"))
        if (
            not isinstance(archived_manifest, dict)
            or archived_manifest.get("version") != version
            or archived_manifest.get("manifest_version") != 3
        ):
            raise ValueError("packaged manifest does not match the release tag")


def self_check() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        extension = Path(temporary) / "extension"
        extension.mkdir()
        (extension / "manifest.json").write_text(
            '{"manifest_version": 3, "version": "1.2.3"}', encoding="utf-8"
        )
        (extension / "popup.html").write_text("<main></main>", encoding="utf-8")
        (extension / ".hidden").write_text("skip", encoding="utf-8")
        (extension / "README.md").write_text("skip", encoding="utf-8")
        output = Path(temporary) / "release.zip"
        assert _inside(output, Path(temporary))
        assert not _inside(Path(temporary).parent / "outside.zip", Path(temporary))
        package(extension, output, "1.2.3", ["manifest.json", "popup.html", ".hidden", "README.md"])
        with zipfile.ZipFile(output) as archive:
            assert set(archive.namelist()) == {"manifest.json", "popup.html"}
        try:
            package(extension, output, "1.2.4", ["manifest.json", "popup.html"])
        except ValueError:
            pass
        else:
            raise AssertionError("a mismatched tag version was accepted")
        for path in ("../outside", ".env", "data/profile.json", "C:/outside"):
            try:
                _validate_members([path], {path})
            except ValueError:
                continue
            raise AssertionError("an unsafe archive path was accepted")
        try:
            _validate_members(["manifest.json", "extra.js"], {"manifest.json"})
        except ValueError:
            pass
        else:
            raise AssertionError("an unexpected archive file was accepted")
        try:
            _source_files(extension, ["data/profile.json"])
        except ValueError:
            pass
        else:
            raise AssertionError("a data source path was accepted")
        (Path(temporary) / "outside.txt").write_text("outside", encoding="utf-8")
        (extension / "linked.txt").symlink_to(Path(temporary) / "outside.txt")
        try:
            _source_files(extension, ["linked.txt"])
        except ValueError:
            pass
        else:
            raise AssertionError("a symlinked source file was accepted")


def main() -> int:
    if sys.argv[1:] == ["--self-check"]:
        self_check()
        print("extension packager self-check passed")
        return 0
    if len(sys.argv) != 3:
        print("usage: package_extension.py VERSION OUTPUT.zip", file=sys.stderr)
        return 2

    output = (ROOT / sys.argv[2]).resolve()
    extension = ROOT / "extension"
    if (
        not _inside(output, ROOT)
        or _inside(output, extension)
        or extension.is_symlink()
        or not _inside(extension, ROOT)
    ):
        print(
            "release paths must stay inside the repository; extension/ cannot be a symlink",
            file=sys.stderr,
        )
        return 2
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "extension"], cwd=ROOT)
    names = []
    for raw_path in tracked.split(b"\0"):
        if not raw_path:
            continue
        path = os.fsdecode(raw_path)
        if not path.startswith("extension/"):
            print("tracked extension path is invalid", file=sys.stderr)
            return 2
        names.append(path[len("extension/") :])
    try:
        package(extension, output, sys.argv[1], names)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"extension packaging failed: {error}", file=sys.stderr)
        return 1
    with zipfile.ZipFile(output) as archive:
        count = len(archive.namelist())
    print(f"packaged {count} extension files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
