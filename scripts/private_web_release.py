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
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from daemon_lock import acquire_daemon_lock, release_daemon_lock

PRESERVE_NAMES = {"data", "logs"}
REQUIRED_RELEASE_FILES = {
    "START_PRIVATE_WEB_HOST.cmd",
    "STOP_PRIVATE_WEB.cmd",
    "server/server.py",
    "server/decision_store.py",
    "server/pulse_updates.py",
    "server/ai_local.py",
    "server/ai_routes.py",
    "src/ai/ai_runtime_client.js",
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
    "tests/test_ai_routes_stream.py",
    "tests/ai_panels_selftest.js",
    "tests/test_private_web_access.py",
    "tests/test_archify_artifacts.py",
    "stock_terminal_v2.html",
    "assets/vendor/pdfjs/6.3.289/pdf.min.mjs",
    "assets/vendor/pdfjs/6.3.289/pdf.worker.min.mjs",
    "assets/vendor/pdfjs/6.3.289/來源資訊.json",
    "tests/test_pdf_assets.py",
    "assets/vendor/html2canvas/1.4.1/html2canvas.min.js",
    "assets/vendor/html2canvas/1.4.1/LICENSE",
    "assets/vendor/html2canvas/1.4.1/來源資訊.json",
    "assets/vendor/jspdf/4.2.1/jspdf.umd.min.js",
    "assets/vendor/jspdf/4.2.1/LICENSE",
    "assets/vendor/jspdf/4.2.1/來源資訊.json",
    "tests/test_PDF匯出資產.py",
    "tests/test_官方對照來源.py",
    "tests/test_NHNL來源.py",
    "tests/test_投組市場代號.py",
    "tests/test_市場尾碼一致性.py",
    "tests/分類範圍標示_selftest.js",
    "tests/決策更新狀態_selftest.js",
    "tests/個股健診歷史分析_selftest.js",
}
PRIVATE_RELEASE_EXCLUDES = {"wavedeck", "START_WAVEDECK.cmd"}
MANIFEST_NAME = ".private_web_release.json"
TRANSITION_NAME = ".private_web_transition.json"


def _content_hashes(root: Path, *, include_runtime: bool = True,
                    include_manifest: bool = False,
                    exclude_regenerable_cache: bool = False) -> dict[str, str]:
    """暫存內容包含種子與位元組碼；前版另核對識別檔並排除執行期資料。"""
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not include_runtime and relative.parts[0] in PRESERVE_NAMES:
            continue
        if not include_manifest and relative.as_posix() == MANIFEST_NAME:
            continue
        if exclude_regenerable_cache and _is_regenerable_cache(path, root):
            continue
        if path.is_symlink() or not _within(path, root):
            raise RuntimeError(f"發布內容含有不受允許的連結：{relative}")
        if path.is_file():
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _program_hashes(root: Path) -> dict[str, str]:
    return _content_hashes(root, include_runtime=False, include_manifest=True,
                           exclude_regenerable_cache=True)


def _is_regenerable_cache(path: Path, root: Path) -> bool:
    if (path.parent.name != "__pycache__" or path.suffix != ".pyc"
            or path.is_symlink() or not _within(path, root)):
        return False
    try:
        source = Path(importlib.util.source_from_cache(str(path)))
    except ValueError:
        return False
    return source.is_file() and _within(source, root)


@contextmanager
def _release_lock(install_root: Path) -> Iterator[None]:
    handle = acquire_daemon_lock("private-web-release", lock_dir=install_root / ".locks")
    if handle is None:
        raise RuntimeError("另一個發布或回復程序正在執行，尚未變更目前版本")
    try:
        yield
    finally:
        release_daemon_lock(handle)


def _validate_integrity(root: Path, manifest: dict) -> None:
    commit = manifest.get("commit", "")
    release_id = manifest.get("releaseId", "")
    if (not isinstance(commit, str) or len(commit) != 40
            or any(ch not in "0123456789abcdef" for ch in commit)
            or not isinstance(release_id, str) or not release_id
            or not commit.startswith(release_id)):
        raise RuntimeError("發布識別資料無效，請重新暫存版本")
    expected = manifest.get("contentSha256")
    if not isinstance(expected, dict) or not expected:
        raise RuntimeError("暫存版本缺少受測內容雜湊，請重新暫存版本")
    actual = _content_hashes(root)
    if actual != expected:
        changed = sorted(key for key in actual.keys() | expected.keys()
                         if actual.get(key) != expected.get(key))
        raise RuntimeError("暫存版本內容與受測版本不符：" + ", ".join(changed[:8]))


def _write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _transition_path(install_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise RuntimeError("發布回復路徑無效")
    path = install_root / relative
    if (Path(relative).is_absolute() or ".." in Path(relative).parts
            or path.resolve() == install_root.resolve() or not _within(path, install_root)
            or path.name == "current"):
        raise RuntimeError("發布回復路徑超出允許範圍")
    return path


def recover_transition(install_root: Path) -> None:
    """在已授權的發布／回復流程中修復上次中斷的目錄切換。"""
    install_root = safe_install_root(install_root)
    with _release_lock(install_root):
        _recover_transition(install_root)


def _recover_transition(install_root: Path) -> None:
    journal = install_root / TRANSITION_NAME
    if not journal.exists():
        return
    state = _read_manifest(journal)
    candidate = _transition_path(install_root, state.get("candidate"))
    previous = _transition_path(install_root, state.get("previous"))
    current = install_root / "current"
    if current.exists() and not candidate.exists():
        # 候選目錄已完成改名；中斷發生於移除交易紀錄之前。
        if _program_hashes(current) != state.get("candidateContentSha256"):
            raise RuntimeError("發布交易狀態不明，保留所有目錄與交易紀錄")
        journal.unlink()
        return
    if not candidate.exists():
        raise RuntimeError("發布候選目錄遺失，保留交易紀錄等待回復")
    if _program_hashes(candidate) != state.get("candidateContentSha256"):
        raise RuntimeError("發布候選內容已改變，保留交易紀錄等待回復")
    if previous.exists() and not current.exists():
        if _program_hashes(previous) != state.get("previousContentSha256"):
            raise RuntimeError("發布前版內容已改變，保留交易紀錄等待回復")
        for name in PRESERVE_NAMES:
            source = candidate / name
            target = previous / name
            if source.exists() and not target.exists():
                source.rename(target)
        previous.rename(current)
    elif state.get("hadCurrent") and not current.exists():
        raise RuntimeError("發布中斷且找不到前版，保留交易紀錄等待回復")
    elif current.exists() and (previous.exists() or not state.get("hadCurrent")
                              or _program_hashes(current) != state.get("previousContentSha256")):
        raise RuntimeError("發布交易狀態不明，保留所有目錄與交易紀錄")
    journal.unlink()


def _switch_tree(install_root: Path, candidate: Path, previous: Path,
                 *, seed_source: Path | None = None) -> None:
    current = install_root / "current"
    journal = install_root / TRANSITION_NAME
    previous.parent.mkdir(parents=True, exist_ok=True)
    _write_json(journal, {
        "candidate": candidate.relative_to(install_root).as_posix(),
        "previous": previous.relative_to(install_root).as_posix(),
        "hadCurrent": current.exists(),
        "candidateContentSha256": _program_hashes(candidate),
        "previousContentSha256": _program_hashes(current) if current.exists() else None,
    })
    try:
        if current.exists():
            current.rename(previous)
        for name in PRESERVE_NAMES:
            source = previous / name
            if source.exists():
                source.rename(candidate / name)
        if seed_source is not None:
            _merge_missing_data(seed_source, candidate / "data")
        (candidate / "logs").mkdir(exist_ok=True)
        candidate.rename(current)
    except BaseException:
        _recover_transition(install_root)
        raise
    try:
        journal.unlink()
    except OSError:
        # 目錄切換已提交；下次發布會先核對並清除此筆交易。
        print("版本已切換；交易紀錄暫時無法清除，下次發布會先完成回復核對", file=sys.stderr)


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
    with _release_lock(install_root):
        return _stage_release(install_root, ref=ref, python=python, run_tests=run_tests)


def _stage_release(install_root: Path, *, ref: str, python: str, run_tests: bool) -> Path:
    commit, release_id = resolve_commit(ref)
    releases = install_root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    target = releases / release_id
    if target.exists():
        _validate_release(target)
        manifest = _read_manifest(target / ".private_web_release.json")
        if manifest.get("commit") != commit or manifest.get("releaseId") != release_id:
            raise RuntimeError(f"已暫存版本的識別資料不符：{target}")
        if manifest.get("tests") != "passed":
            raise RuntimeError(f"已暫存版本未通過測試，禁止重用：{target}")
        _validate_integrity(target, manifest)
        return target

    with tempfile.TemporaryDirectory(dir=str(install_root), prefix="stage-") as temp_name:
        temp = Path(temp_name)
        archive_path = temp / "release.zip"
        _run(_git_archive_argv(archive_path, commit), cwd=ROOT)
        extracted = temp / "tree"
        extracted.mkdir()
        _safe_extract(archive_path, extracted)
        _validate_release(extracted)

        _run([python, "build_v2.py"], cwd=extracted)
        tests = [
            "tests.test_ai_local",
            "tests.test_ai_routes_stream",
            "tests.test_台股即時報價",
            "tests.test_台股日線",
            "tests.test_突破觀察",
            "tests.test_突破影子紀錄",
            "tests.test_突破成交研究",
            "tests.test_server_http_security",
            "tests.test_daemon_lock",
            "tests.test_health_live",
            "tests.test_private_web_gateway",
            "tests.test_private_web_access",
            "tests.test_private_web_host",
            "tests.test_private_web_release",
            "tests.test_發布完整性",
            "tests.test_sync_private_web",
            "tests.test_決策資料品質",
            "tests.test_decision_context",
            "tests.test_決策持久提交",
            "tests.test_預警發布收據",
            "tests.test_Pulse更新佇列",
            "tests.test_Pulse讀寫分離",
            "tests.test_decision_http",
            "tests.test_runtime_revision",
            "tests.test_archify_artifacts",
            "tests.test_pdf_assets",
            "tests.test_PDF匯出資產",
            "tests.test_官方對照來源",
            "tests.test_NHNL來源",
            "tests.test_投組市場代號",
            "tests.test_市場尾碼一致性",
            "tests.test_tw_name_integrity",
            "tests.test_pulse_extras",
            "tests.test_pulse_intel",
            "tests.test_sector_flow",
            "tests.test_類股成員",
        ]
        if run_tests:
            _run([python, "-m", "unittest", "-b", *tests], cwd=extracted)
            node = shutil.which("node")
            if not node:
                raise RuntimeError("Node.js is required for ETF/UI release regression tests")
            for selftest in sorted((extracted / "tests").glob("*selftest.js"), key=lambda path: path.name):
                _run([node, selftest.relative_to(extracted).as_posix()], cwd=extracted)

        # 完整封存內容供所有自測使用；通過後才排除私人網站不出貨的執行內容。
        _strip_private_release_extras(extracted)
        # Tests may legitimately exercise refresh paths, but the release
        # artifact must keep committed public seeds byte-identical to Git.
        _restore_preserved_from_archive(archive_path, extracted)
        for path in sorted(extracted.rglob("*"), reverse=True):
            if path.suffix in {".pyc", ".pyo"} or path.name == "__pycache__":
                _remove_managed(path, extracted)

        managed = sorted(item.name for item in extracted.iterdir() if item.name not in PRESERVE_NAMES)
        manifest = {
            "releaseId": release_id,
            "commit": commit,
            "sourceRef": ref,
            "stagedAt": datetime.now(timezone.utc).isoformat(),
            "tests": "passed" if run_tests else "skipped",
            "managedTopLevel": managed,
            "contentSha256": _content_hashes(extracted),
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
    with _release_lock(install_root):
        return _promote_release(install_root, release_id=release_id)


def _promote_release(install_root: Path, *, release_id: str) -> Path:
    _recover_transition(install_root)
    if not release_id or any(ch not in "0123456789abcdef" for ch in release_id.lower()):
        raise ValueError("release id must be the staged hexadecimal commit prefix")
    release = install_root / "releases" / release_id.lower()
    if not release.is_dir() or not _within(release, install_root / "releases"):
        raise FileNotFoundError(f"staged release not found: {release_id}")
    _validate_release(release)
    release_manifest = _read_manifest(release / ".private_web_release.json")
    if release_manifest.get("tests") != "passed":
        raise RuntimeError("only a release with passed tests may be promoted")
    _validate_integrity(release, release_manifest)
    if release_manifest.get("releaseId") != release_id.lower():
        raise RuntimeError("暫存版本目錄與識別資料不符")

    current = install_root / "current"
    old_manifest = _read_manifest(current / ".private_web_release.json")
    old_managed = set(old_manifest.get("managedTopLevel") or [])
    new_managed = {
        item.name for item in release.iterdir() if item.name not in PRESERVE_NAMES
    }
    candidate = Path(tempfile.mkdtemp(prefix="candidate-", dir=install_root))
    seeds = Path(tempfile.mkdtemp(prefix="seeds-", dir=install_root))
    previous = install_root / "backups" / ("previous-" + uuid.uuid4().hex)
    try:
        for item in release.iterdir():
            _copy_item(item, candidate / item.name)
        _validate_integrity(candidate, release_manifest)
        for name in PRESERVE_NAMES:
            if (candidate / name).exists():
                (candidate / name).rename(seeds / name)
        # 舊版本沒有管理的使用者檔案仍留在作用中的目錄。
        if current.exists():
            for item in current.iterdir():
                if item.name not in old_managed | new_managed | PRESERVE_NAMES:
                    _copy_item(item, candidate / item.name)
        active_manifest = dict(release_manifest)
        active_manifest.update(
            promotedAt=datetime.now(timezone.utc).isoformat(),
            promotionId=uuid.uuid4().hex,
            managedTopLevel=sorted(new_managed),
            previousDirectory=previous.relative_to(install_root).as_posix() if current.exists() else None,
            previousContentSha256=_program_hashes(current) if current.exists() else None,
        )
        _write_json(candidate / MANIFEST_NAME, active_manifest)
        _switch_tree(install_root, candidate, previous, seed_source=seeds / "data")
    finally:
        _remove_managed(seeds, install_root)
        if candidate.exists() and not (install_root / TRANSITION_NAME).exists():
            _remove_managed(candidate, install_root)
    return current


def rollback_release(install_root: Path, *, approved: bool) -> Path:
    if not approved:
        raise PermissionError("回復版本需要 --approve")
    install_root = safe_install_root(install_root)
    with _release_lock(install_root):
        return _rollback_release(install_root)


def _rollback_release(install_root: Path) -> Path:
    _recover_transition(install_root)
    current = install_root / "current"
    manifest = _read_manifest(current / MANIFEST_NAME)
    previous = _transition_path(install_root, manifest.get("previousDirectory"))
    if not _within(previous, install_root / "backups") or not previous.is_dir():
        raise RuntimeError("找不到可回復的前版目錄")
    if _program_hashes(previous) != manifest.get("previousContentSha256"):
        raise RuntimeError("前版內容已改變，拒絕回復")
    for path in previous.rglob("*.pyc"):
        if _is_regenerable_cache(path, previous):
            path.unlink()
    failed = install_root / "backups" / ("failed-" + uuid.uuid4().hex)
    _switch_tree(install_root, previous, failed)
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
    rollback = sub.add_parser("rollback", help="回復前版並保留最新執行期資料")
    rollback.add_argument("--approve", action="store_true")
    recover = sub.add_parser("recover", help="修復中斷的發布目錄交易")
    recover.add_argument("--approve", action="store_true")
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
    elif args.command == "rollback":
        path = rollback_release(args.install_root, approved=args.approve)
        print(json.dumps({"current": str(path)}, ensure_ascii=False, indent=2))
    elif args.command == "recover":
        if not args.approve:
            raise PermissionError("修復發布交易需要 --approve")
        recover_transition(args.install_root)
        print(json.dumps(release_status(args.install_root), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(release_status(args.install_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
