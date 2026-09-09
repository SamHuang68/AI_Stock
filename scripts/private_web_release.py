#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage and explicitly promote committed ST revisions to Private Web ST.

The release flow never copies the dirty development worktree.  ``stage`` uses
``git archive`` for an exact commit, rebuilds the generated UI and runs the
private-Web regression tests.  ``promote`` requires an explicit approval flag
and preserves the production ``data`` and ``logs`` directories.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
PRESERVE_NAMES = {"data", "logs"}
REQUIRED_RELEASE_FILES = {
    "START_PRIVATE_WEB_HOST.cmd",
    "STOP_PRIVATE_WEB.cmd",
    "server/server.py",
    "server/ai_local.py",
    "server/ai_routes.py",
    "server/overnight_intraday.py",
    "server/overnight_intraday_routes.py",
    "server/daemon_lock.py",
    "server/private_web_gateway.py",
    "server/private_web_access.py",
    "scripts/private_web_host.py",
    "scripts/setup_private_web.py",
    "docs/PRIVATE_WEB_ST.md",
    "docs/PRIVATE_WEB_LOGIN_GUIDE.md",
    "docs/architecture/archify-manifest.json",
    "docs/architecture/st-decision-evidence-lineage.dataflow.json",
    "docs/architecture/st-private-web-trust-ai-execution.architecture.json",
    "docs/architecture/st-private-web-release-gate.workflow.json",
    "docs/architecture/st-pulse-refresh-degradation.sequence.json",
    "docs/architecture/st-responsive-shell-ownership.workflow.json",
    "docs/architecture/st-signal-passport-early-warning.lifecycle.json",
    "assets/docs/archify/st-decision-evidence-lineage.html",
    "assets/docs/archify/st-private-web-trust-ai-execution.html",
    "assets/docs/archify/st-private-web-release-gate.html",
    "assets/docs/archify/st-pulse-refresh-degradation.html",
    "assets/docs/archify/st-responsive-shell-ownership.html",
    "assets/docs/archify/st-signal-passport-early-warning.html",
    "tests/test_health_live.py",
    "tests/test_daemon_lock.py",
    "tests/test_private_web_host.py",
    "tests/test_ai_local.py",
    "tests/test_private_web_access.py",
    "tests/test_archify_artifacts.py",
    "stock_terminal_v2.html",
}
PRIVATE_RELEASE_EXCLUDES = {"wavedeck", "START_WAVEDECK.cmd"}


def default_install_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "StockTerminalPrivateWeb"
    return Path.home() / ".stock-terminal-private-web"


def safe_install_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    drive_root = Path(resolved.anchor).resolve()
    forbidden = {drive_root, Path.home().resolve(), ROOT.resolve()}
    if resolved in forbidden or len(resolved.parts) < 3:
        raise ValueError(f"unsafe install root: {resolved}")
    return resolved


def _run(argv: list[str], *, cwd: Path, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )


def resolve_commit(ref: str) -> tuple[str, str]:
    result = _run(["git", "rev-parse", f"{ref}^{{commit}}"], cwd=ROOT, capture=True)
    commit = result.stdout.strip().lower()
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit):
        raise RuntimeError(f"could not resolve a full commit for {ref!r}")
    return commit, commit[:12]


def _git_archive_argv(archive_path: Path, commit: str) -> list[str]:
    """Build an archive from Git blobs without host checkout/EOL filters."""
    return [
        "git",
        "-c",
        "core.autocrlf=false",
        "archive",
        "--format=zip",
        "--output",
        str(archive_path),
        commit,
    ]


def _safe_extract(archive_path: Path, target: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            pure = PurePosixPath(info.filename)
            if pure.is_absolute() or ".." in pure.parts:
                raise RuntimeError(f"unsafe archive member: {info.filename}")
        archive.extractall(target)


def _restore_preserved_from_archive(archive_path: Path, target: Path) -> None:
    """Restore preserved seed trees byte-for-byte after release tests.

    Some integration tests import the live server and may refresh files below
    ``data``.  A staged release must still represent the exact Git archive;
    runtime/test writes are never allowed to become release inputs.
    """
    resolved_target = target.resolve()
    if not resolved_target.is_dir():
        raise FileNotFoundError(f"release tree is missing: {resolved_target}")

    with zipfile.ZipFile(archive_path, "r") as archive:
        preserved_members = []
        for info in archive.infolist():
            pure = PurePosixPath(info.filename)
            if pure.is_absolute() or ".." in pure.parts:
                raise RuntimeError(f"unsafe archive member: {info.filename}")
            if pure.parts and pure.parts[0] in PRESERVE_NAMES:
                preserved_members.append(info)

        for name in sorted(PRESERVE_NAMES):
            destination = (resolved_target / name).resolve()
            try:
                destination.relative_to(resolved_target)
            except ValueError as exc:
                raise RuntimeError(f"unsafe preserved path: {destination}") from exc
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            elif destination.exists() or destination.is_symlink():
                destination.unlink()

        for info in preserved_members:
            archive.extract(info, resolved_target)


def _validate_release(path: Path) -> None:
    missing = sorted(rel for rel in REQUIRED_RELEASE_FILES if not (path / rel).is_file())
    if missing:
        raise RuntimeError("commit is not Private-Web ready; missing: " + ", ".join(missing))


def _strip_private_release_extras(path: Path) -> None:
    for name in PRIVATE_RELEASE_EXCLUDES:
        target = path / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def stage_release(
    install_root: Path,
    *,
    ref: str,
    python: str = sys.executable,
    run_tests: bool = True,
) -> Path:
    install_root = safe_install_root(install_root)
    commit, release_id = resolve_commit(ref)
    releases = install_root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    target = releases / release_id
    if target.exists():
        raise FileExistsError(f"release already staged: {target}")

    with tempfile.TemporaryDirectory(dir=str(install_root), prefix="stage-") as temp_name:
        temp = Path(temp_name)
        archive_path = temp / "release.zip"
        _run(_git_archive_argv(archive_path, commit), cwd=ROOT)
        extracted = temp / "tree"
        extracted.mkdir()
        _safe_extract(archive_path, extracted)
        _strip_private_release_extras(extracted)
        _validate_release(extracted)

        _run([python, "build_v2.py"], cwd=extracted)
        tests = [
            "tests.test_ai_local",
            "tests.test_daemon_lock",
            "tests.test_health_live",
            "tests.test_private_web_gateway",
            "tests.test_private_web_access",
            "tests.test_private_web_host",
            "tests.test_private_web_release",
            "tests.test_archify_artifacts",
        ]
        if run_tests:
            _run([python, "-m", "unittest", "-b", *tests], cwd=extracted)
            node = shutil.which("node")
            if not node:
                raise RuntimeError("Node.js is required for ETF/UI release regression tests")
            _run([node, "tests/etf_flow_v3_selftest.js"], cwd=extracted)
            _run([node, "tests/shell_v5_selftest.js"], cwd=extracted)

        # Tests may legitimately exercise refresh paths, but the release
        # artifact must keep committed public seeds byte-identical to Git.
        _restore_preserved_from_archive(archive_path, extracted)

        managed = sorted(item.name for item in extracted.iterdir() if item.name not in PRESERVE_NAMES)
        manifest = {
            "releaseId": release_id,
            "commit": commit,
            "sourceRef": ref,
            "stagedAt": datetime.now(timezone.utc).isoformat(),
            "tests": "passed" if run_tests else "skipped",
            "managedTopLevel": managed,
        }
        (extracted / ".private_web_release.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        shutil.move(str(extracted), str(target))
    return target


def _within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _remove_managed(path: Path, install_root: Path) -> None:
    if not _within(path, install_root):
        raise ValueError(f"refusing to remove path outside install root: {path}")
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _copy_item(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def _merge_missing_data(source: Path, target: Path) -> None:
    if not source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        return
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def _read_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def promote_release(install_root: Path, *, release_id: str, approved: bool) -> Path:
    if not approved:
        raise PermissionError("promotion requires --approve")
    install_root = safe_install_root(install_root)
    if not release_id or any(ch not in "0123456789abcdef" for ch in release_id.lower()):
        raise ValueError("release id must be the staged hexadecimal commit prefix")
    release = install_root / "releases" / release_id.lower()
    if not release.is_dir() or not _within(release, install_root / "releases"):
        raise FileNotFoundError(f"staged release not found: {release_id}")
    _validate_release(release)
    release_manifest = _read_manifest(release / ".private_web_release.json")
    if release_manifest.get("tests") != "passed":
        raise RuntimeError("only a release with passed tests may be promoted")

    current = install_root / "current"
    current.mkdir(parents=True, exist_ok=True)
    old_manifest = _read_manifest(current / ".private_web_release.json")
    old_managed = set(old_manifest.get("managedTopLevel") or [])
    new_managed = {
        item.name for item in release.iterdir() if item.name not in PRESERVE_NAMES
    }
    for name in sorted(old_managed | new_managed):
        if name in PRESERVE_NAMES or name in {".", ".."}:
            continue
        candidate = current / name
        if candidate.exists() or candidate.is_symlink():
            _remove_managed(candidate, install_root)
    for item in release.iterdir():
        if item.name in PRESERVE_NAMES:
            continue
        _copy_item(item, current / item.name)

    _merge_missing_data(release / "data", current / "data")
    (current / "logs").mkdir(parents=True, exist_ok=True)
    active_manifest = dict(release_manifest)
    active_manifest["promotedAt"] = datetime.now(timezone.utc).isoformat()
    active_manifest["managedTopLevel"] = sorted(new_managed)
    (current / ".private_web_release.json").write_text(
        json.dumps(active_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return current


def release_status(install_root: Path) -> dict:
    install_root = safe_install_root(install_root)
    releases_path = install_root / "releases"
    releases = sorted(
        path.name for path in releases_path.iterdir() if path.is_dir()
    ) if releases_path.is_dir() else []
    active = _read_manifest(install_root / "current" / ".private_web_release.json")
    return {"installRoot": str(install_root), "active": active or None, "staged": releases}


def main() -> None:
    parser = argparse.ArgumentParser(description="Private Web ST release gate")
    parser.add_argument("--install-root", type=Path, default=default_install_root())
    sub = parser.add_subparsers(dest="command", required=True)

    stage = sub.add_parser("stage", help="build and test an exact committed revision")
    stage.add_argument("--ref", required=True, help="commit, tag or branch to stage")
    stage.add_argument("--skip-tests", action="store_true")

    promote = sub.add_parser("promote", help="make a staged release current")
    promote.add_argument("--release", required=True)
    promote.add_argument("--approve", action="store_true")

    sub.add_parser("status", help="show staged and active revisions")
    args = parser.parse_args()
    if args.command == "stage":
        path = stage_release(
            args.install_root,
            ref=args.ref,
            run_tests=not args.skip_tests,
        )
        print(json.dumps({"staged": str(path)}, ensure_ascii=False, indent=2))
    elif args.command == "promote":
        path = promote_release(
            args.install_root,
            release_id=args.release,
            approved=args.approve,
        )
        print(json.dumps({"current": str(path)}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(release_status(args.install_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
