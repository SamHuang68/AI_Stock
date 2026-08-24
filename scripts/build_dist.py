#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build and verify a share-safe Stock Terminal distribution archive.

The build is allow-list based. It excludes local databases, history snapshots,
logs, editor/agent memory, internal notes and credential files, then scans both
the staged tree and the final ZIP for common secret and personal-path patterns.

Usage:
  python scripts/build_dist.py
  python scripts/build_dist.py --out /path/to/Stock_Terminal_v5.0.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE_NAME = "Stock_Terminal"
ZIP_NAME = "Stock_Terminal_v5.0.zip"
TRACE_PATH = ROOT / "logs" / "build_dist.jsonl"


def read_version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "5.0"
    except OSError:
        return "5.0"


VERSION = read_version()

# Block these basenames anywhere in the staged tree. The list includes private
# state as well as internal development context that recipients do not need.
BLOCKED_BASENAMES = {
    "ai_key.txt",
    "ai_key.bin",
    "alert_secrets.bin",
    "alert_config.json",
    "alert_rules.json",
    "watch_rules.json",
    "watch_state.json",
    "draw_store.json",
    "secrets.json",
    "credentials.json",
    "positions_backup.json",
    "watches_backup.json",
    "stock_python.path",
    "wavedeck_bus.json",
    "runtime_state.json",
    "wavedeck.port",
    "llm_gate.json",
    "private_web.json",
    "private_web_owner.token",
    "private_web_read.token",
    "private_web_access_requests.json",
    "private_web_gateway.pid",
    "private_web_host.pid",
    ".cursorrules",
    "tip_branch",
    # Internal handoff, audit and work-in-progress notes.
    "revision.md",
    "antigravity_handoff_audit.md",
    "nav_overlap_audit.md",
    "visual_text_upgrade_plan.md",
    "macro_market_risk_observations.md",
}
BLOCKED_BASENAMES_LOWER = {name.lower() for name in BLOCKED_BASENAMES}

SECRET_SUFFIXES = (
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
)
SECRET_PREFIXES = (".env",)

# Directory names skipped anywhere while walking an allowed source tree.
SKIP_DIR_NAMES = {
    "__pycache__",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    ".agent",
    ".agents",
    ".codex",
    "Stock_Terminal",
    "logs",
    "scratch",
    "installer",  # installer toolchain is not needed for the source ZIP
    "dist",
}

# Public files that make a new install useful before its first refresh.
DATA_ALLOW_FILES = {
    "etf_catalog.json",
    "universe.json",
    "tw_names_backup.json",
    "cbc_policy_rates.csv",
    "cbc_policy_rate_changes.csv",
    "tw_margin_mix_daily.csv",
    "txf_daily.csv",
    "margin_ratio_history.csv",
    "twoii_daily.csv",
    "tai50_daily.csv",
}

# All local databases are deliberately excluded, including WAL/SHM companions.
DATA_BLOCK_FILES = {
    "market.db",
    "market.db-wal",
    "market.db-shm",
    "macro_track.db",
    "macro_track.db-wal",
    "macro_track.db-shm",
    "pulse_history.db",
    "pulse_history.db-wal",
    "pulse_history.db-shm",
    "tdcc_holders.db",
    "tdcc_holders.db-wal",
    "tdcc_holders.db-shm",
    "margin_cycle.db",
    "margin_cycle.db-wal",
    "margin_cycle.db-shm",
    "override_alpha.db",
    "override_alpha.db-wal",
    "override_alpha.db-shm",
    "decision_history.db",
    "decision_history.db-wal",
    "decision_history.db-shm",
    "options_structure_cache.json",
    "options_structure_history.json",
}

ROOT_ALLOW_FILES = (
    "stock_terminal.html",
    "stock_terminal_v2.html",
    "build_v2.py",
    "build_order.py",
    "daily_morning_brief.py",
    "etf_report.py",
    "etf_report_email.py",
    "README.md",
    "LICENSE",
    "START_TIP.cmd",
    "START_WAVEDECK.cmd",
    "VERSION",
    ".gitignore",
)

TREE_ALLOW = (
    "src",
    "server",
    "scripts",
    "docs",
    "assets",
    "tests",
    "wavedeck",
    ".github",
)

# The personal Web deployment overlay stays out of the ordinary single-machine
# share ZIP.  It is released separately by private_web_release.py from an exact
# committed revision.
PRIVATE_WEB_ONLY_PATHS = {
    "server": ("private_web_gateway.py", "private_web_access.py"),
    "scripts": (
        "private_web_host.py",
        "private_web_release.py",
        "setup_private_web.py",
    ),
    "tests": (
        "test_private_web_gateway.py",
        "test_private_web_access.py",
        "test_private_web_host.py",
        "test_private_web_release.py",
    ),
    "docs": ("private_web_st.md", "private_web_login_guide.md"),
}

# Runtime and documentation added as one feature must travel together.  The
# distribution remains Git allow-list based; this list makes an incomplete
# working tree a hard preflight failure instead of silently producing a ZIP
# that cannot provide the documented feature.
REQUIRED_SHARE_FILES = (
    "README.md",
    "LICENSE",
    "START_TIP.cmd",
    "stock_terminal.html",
    "server/server.py",
    "server/daemon_lock.py",
    "server/atomic_store.py",
    "server/deadline.py",
    "server/http_boundary.py",
    "server/keystats_resolution.py",
    "server/secret_store.py",
    "server/decision_context.py",
    "server/decision_routes.py",
    "server/exposure_lab.py",
    "server/benchmark_research.py",
    "server/international_fundamental.py",
    "server/key_levels.py",
    "server/news_impact.py",
    "server/options_exposure.py",
    "server/options_routes.py",
    "server/overnight_intraday.py",
    "server/overnight_intraday_routes.py",
    "server/sector_flow.py",
    "server/sector_history.py",
    "src/core/market_data_v5.js",
    "src/core/app_kernel_v5.js",
    "src/core/decision_data_v5.js",
    "src/core/market_intel_v5.js",
    "src/core/table_sort_v5.js",
    "src/ui/chart_visual_v5.js",
    "src/ui/pulse_v5.js",
    "src/ui/decision_v5.js",
    "src/ui/visual_system_v5.js",
    "scripts/replay_decisions.py",
    "docs/STRATEGIC_COMMAND_CENTER_PLAN.md",
    "docs/ST_ARCHITECTURE_REMEDIATION_2026-08-16.md",
    "docs/OVERNIGHT_INTRADAY_RESEARCH.md",
    "tests/fixtures/decision_replay.json",
    "tests/test_decision_context.py",
    "tests/test_exposure_lab.py",
    "tests/test_benchmark_research.py",
    "tests/test_options_exposure.py",
    "tests/test_overnight_intraday.py",
    "tests/test_atomic_store.py",
    "tests/test_build_reproducibility.py",
    "tests/test_datastore_market_identity.py",
    "tests/test_deadline.py",
    "tests/test_http_boundary.py",
    "tests/test_launcher_safety.py",
    "tests/test_secret_migration.py",
    "tests/test_secret_store.py",
    "tests/test_server_http_security.py",
    "tests/layout_visual_v5_selftest.js",
)

TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".css",
    ".html",
    ".md",
    ".txt",
    ".json",
    ".csv",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".ps1",
    ".bat",
    ".cmd",
    ".sh",
    ".iss",
}
TEXT_BASENAMES = {".gitignore", "VERSION"}

# These patterns intentionally target concrete credential formats. Placeholder
# examples such as "your-api-key" do not match.
SENSITIVE_CONTENT_RULES = (
    (
        "windows-user-path",
        re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+(?!Public\b|Default\b)[^\\/\r\n\"']+"),
    ),
    (
        "mac-user-path",
        re.compile(r"(?i)(?<![\w/])/" + r"Users/(?!Shared\b)[^/\s\"']+"),
    ),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("openai-anthropic-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("aws-access-key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("telegram-token", re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")),
    ("credential-in-url", re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]+@")),
    (
        "email-address",
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    ),
)


def git_tracked_files() -> set[str] | None:
    """Return tracked paths when building from a checkout; otherwise None."""
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
        return {
            item.replace("\\", "/")
            for item in result.stdout.decode("utf-8", "surrogateescape").split("\0")
            if item
        }
    except (OSError, subprocess.CalledProcessError):
        return None


TRACKED_FILES = git_tracked_files()


def trace_build(run_id: str, event: str, **details: object) -> None:
    """Persist a sanitized, append-only build trace outside the share ZIP."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": "build_dist",
        "event": event,
        "correlationId": run_id,
        **details,
    }
    try:
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        # Diagnostics must never weaken or mask the privacy-safe build result.
        pass


def validate_required_share_files() -> None:
    """Reject missing or untracked feature files before staging an archive."""
    missing = [rel for rel in REQUIRED_SHARE_FILES if not (ROOT / rel).is_file()]
    untracked = [
        rel for rel in REQUIRED_SHARE_FILES
        if (ROOT / rel).is_file() and not is_tracked(ROOT / rel)
    ]
    problems = []
    if missing:
        problems.append("missing: " + ", ".join(missing))
    if untracked:
        problems.append("not in Git index: " + ", ".join(untracked))
    if problems:
        raise RuntimeError("share preflight failed (" + "; ".join(problems) + ")")


def is_blocked_name(name: str) -> bool:
    lower = name.lower()
    if lower in BLOCKED_BASENAMES_LOWER or lower in DATA_BLOCK_FILES:
        return True
    if lower.startswith("options_structure_history.json.") and lower.endswith(".tmp"):
        return True
    if any(lower.endswith(suffix) for suffix in SECRET_SUFFIXES):
        return True
    if any(lower.startswith(prefix) for prefix in SECRET_PREFIXES):
        return True
    return False


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES or name.endswith(".egg-info")


def is_tracked(path: Path) -> bool:
    if TRACKED_FILES is None:
        return True
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:
        return False
    return rel in TRACKED_FILES


def copy_tree_filtered(
    src: Path,
    dst: Path,
    *,
    skip_rel_prefixes: tuple[str, ...] = (),
) -> int:
    """Copy an allowed tree while rejecting untracked and sensitive files."""
    if not src.is_dir():
        return 0
    count = 0
    dst.mkdir(parents=True, exist_ok=True)
    normalized_prefixes = tuple(p.strip("/").lower() for p in skip_rel_prefixes)
    for root, dirs, files in os.walk(src, followlinks=False):
        root_path = Path(root)
        rel = root_path.relative_to(src)
        dirs[:] = [
            name
            for name in dirs
            if not should_skip_dir(name)
            and not (root_path / name).is_symlink()
            and not any(
                (rel / name).as_posix().lower() == prefix
                or (rel / name).as_posix().lower().startswith(prefix + "/")
                for prefix in normalized_prefixes
            )
        ]
        out_dir = dst / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        for filename in files:
            source = root_path / filename
            rel_source = source.relative_to(src).as_posix().lower()
            if source.is_symlink() or not is_tracked(source):
                continue
            if any(
                rel_source == prefix or rel_source.startswith(prefix + "/")
                for prefix in normalized_prefixes
            ):
                continue
            if is_blocked_name(filename):
                continue
            if filename.lower().endswith(
                (".pyc", ".pyo", ".log", ".bak", ".tmp", ".orig")
            ):
                continue
            shutil.copy2(source, out_dir / filename)
            count += 1
    return count


def stage_data(stage: Path) -> int:
    """Copy only public seeds and create empty personal-history directories."""
    data_src = ROOT / "data"
    data_dst = stage / "data"
    data_dst.mkdir(parents=True, exist_ok=True)
    count = 0
    if not data_src.is_dir():
        return count

    for filename in sorted(DATA_ALLOW_FILES):
        source = data_src / filename
        if source.is_file() and not source.is_symlink() and is_tracked(source):
            shutil.copy2(source, data_dst / filename)
            count += 1
            print(f"  + data/{filename}")

    seeds_src = data_src / "macro_seeds"
    seeds_dst = data_dst / "macro_seeds"
    if seeds_src.is_dir():
        seeds_dst.mkdir(parents=True, exist_ok=True)
        for source in sorted(seeds_src.iterdir()):
            if (
                source.is_file()
                and not source.is_symlink()
                and is_tracked(source)
                and not is_blocked_name(source.name)
                and source.suffix.lower() in {".csv", ".json", ".txt", ".md"}
            ):
                shutil.copy2(source, seeds_dst / source.name)
                count += 1

    history_notes = {
        "etf_history": (
            "ETF holding snapshots are generated locally after the tracker runs.\n"
            "Share builds intentionally omit all history snapshots.\n"
        ),
        "chip_history": (
            "Institutional snapshots are generated locally after the tracker runs.\n"
            "Share builds intentionally omit all history snapshots.\n"
        ),
    }
    for dirname, note in history_notes.items():
        target = data_dst / dirname / "README.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(note, encoding="utf-8")
        count += 1

    return count


def stage_wavedeck_runtime(stage: Path) -> None:
    target = stage / "wavedeck" / "data" / "README.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "WaveDeck runtime state, audit logs, port files and execution records are generated locally.\n"
        "They are intentionally absent from the share build.\n",
        encoding="utf-8",
    )


def scrub_blocked_names(stage: Path) -> list[str]:
    removed: list[str] = []
    for root, dirs, files in os.walk(stage):
        dirs[:] = [name for name in dirs if not should_skip_dir(name)]
        for filename in files:
            if is_blocked_name(filename):
                path = Path(root) / filename
                removed.append(path.relative_to(stage).as_posix())
                path.unlink(missing_ok=True)
    return removed


def is_text_path(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_BASENAMES


def scan_text(relative_name: str, text: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for rule, pattern in SENSITIVE_CONTENT_RULES:
        for match in pattern.finditer(text):
            value = match.group(0)
            if rule == "email-address" and value.lower().endswith("@example.com"):
                continue
            issues.append({"path": relative_name, "rule": rule})
            break
    return issues


def scan_stage_content(stage: Path) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for path in sorted(stage.rglob("*")):
        if not path.is_file() or not is_text_path(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        issues.extend(scan_text(path.relative_to(stage).as_posix(), text))
    return issues


def make_zip(stage: Path, zip_path: Path) -> int:
    if zip_path.exists():
        zip_path.unlink()
    file_count = 0
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for root, dirs, files in os.walk(stage):
            dirs[:] = sorted(name for name in dirs if not should_skip_dir(name))
            for filename in sorted(files):
                if is_blocked_name(filename):
                    continue
                full = Path(root) / filename
                arcname = full.relative_to(stage.parent).as_posix()
                info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100644 & 0xFFFF) << 16
                info.create_system = 3
                archive.writestr(info, full.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                file_count += 1
    return file_count


def verify_archive(zip_path: Path) -> list[dict[str, str]]:
    """Re-scan names, personal histories and text after compression."""
    issues: list[dict[str, str]] = []
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            archive_path = Path(info.filename)
            filename = archive_path.name
            if is_blocked_name(filename):
                issues.append({"path": info.filename, "rule": "blocked-filename"})
                continue
            parts_lower = [part.lower() for part in archive_path.parts]
            if any(part in {"chip_history", "etf_history"} for part in parts_lower):
                if filename.lower() != "readme.txt":
                    issues.append({"path": info.filename, "rule": "personal-history"})
            if "wavedeck" in parts_lower and "data" in parts_lower:
                if filename.lower() != "readme.txt":
                    issues.append({"path": info.filename, "rule": "wavedeck-runtime"})
            if archive_path.suffix.lower() in TEXT_SUFFIXES or filename in TEXT_BASENAMES:
                try:
                    text = archive.read(info).decode("utf-8")
                except UnicodeDecodeError:
                    continue
                issues.extend(scan_text(info.filename, text))
    return issues


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_paths(zip_path: Path) -> tuple[Path, Path]:
    checksum_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    manifest_path = zip_path.with_name(zip_path.stem + ".manifest.json")
    return checksum_path, manifest_path


def remove_artifacts(zip_path: Path) -> None:
    checksum_path, manifest_path = sidecar_paths(zip_path)
    for path in (zip_path, checksum_path, manifest_path):
        path.unlink(missing_ok=True)


def write_sidecars(zip_path: Path, file_count: int) -> tuple[Path, Path, str]:
    checksum_path, manifest_path = sidecar_paths(zip_path)
    digest = sha256_file(zip_path)
    checksum_path.write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    manifest = {
        "artifact": zip_path.name,
        "version": VERSION,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "topFolder": STAGE_NAME,
        "bytes": zip_path.stat().st_size,
        "files": file_count,
        "sha256": digest,
        "includes": [
            "Stock Terminal source and generated HTML",
            "tests and CI workflow",
            "WaveDeck optional subproject",
            "public market seed data",
        ],
        "privacyChecks": {
            "blockedFilenames": "passed",
            "personalHistories": "passed",
            "personalPaths": "passed",
            "commonCredentialFormats": "passed",
            "archiveRescan": "passed",
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return checksum_path, manifest_path, digest


def build(out: Path | None = None) -> Path:
    os.chdir(ROOT)
    run_id = uuid.uuid4().hex
    zip_path = (Path(out).resolve() if out else ROOT / ZIP_NAME)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    remove_artifacts(zip_path)
    trace_build(run_id, "command_received", outputName=zip_path.name)

    print("=" * 60)
    print(f" Build Stock Terminal share archive (v{VERSION})")
    print("=" * 60)

    build_temp = Path(tempfile.mkdtemp(prefix='st-dist-build-'))
    generated_html = build_temp / 'stock_terminal_v2.html'
    try:
        print("[1/7] Validating required tracked inputs ...")
        validate_required_share_files()
        trace_build(run_id, "preflight_success", requiredFiles=len(REQUIRED_SHARE_FILES))

        print("[2/7] Rebuilding generated HTML ...")
        started = time.perf_counter()
        trace_build(run_id, "subprocess_start", process="build_v2.py")
        result = subprocess.run(
            [sys.executable, str(ROOT / "build_v2.py"), "--out", str(generated_html)],
            cwd=ROOT)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        trace_build(
            run_id,
            "subprocess_end",
            process="build_v2.py",
            exitCode=result.returncode,
            elapsedMs=elapsed_ms,
        )
        if result.returncode != 0:
            raise RuntimeError("build_v2.py failed; distribution was not created")

        stage = ROOT / STAGE_NAME
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)

        print("[3/7] Staging allow-listed project files ...")
        file_count = 0
        for dirname in TREE_ALLOW:
            skip = list(PRIVATE_WEB_ONLY_PATHS.get(dirname, ()))
            if dirname == "wavedeck":
                skip.append("data")
            file_count += copy_tree_filtered(
                ROOT / dirname,
                stage / dirname,
                skip_rel_prefixes=tuple(skip),
            )

        for filename in ROOT_ALLOW_FILES:
            source = generated_html if filename == 'stock_terminal_v2.html' else ROOT / filename
            if (
                source.is_file()
                and not source.is_symlink()
                and not is_blocked_name(filename)
                and (filename == 'stock_terminal_v2.html' or is_tracked(source))
            ):
                shutil.copy2(source, stage / filename)
                file_count += 1
            else:
                print(f"  [MISS] {filename}")

        file_count += stage_data(stage)
        stage_wavedeck_runtime(stage)
        file_count += 1

        removed = scrub_blocked_names(stage)
        for relative in removed:
            print(f"  - scrubbed {relative}")

        trace_build(run_id, "staging_success", files=file_count)
        print("[4/7] Scanning staged filenames and text content ...")
        stage_issues = scan_stage_content(stage)
        if stage_issues:
            for issue in stage_issues:
                print(f"  [BLOCK] {issue['path']} ({issue['rule']})")
            raise RuntimeError("sensitive or personalized content found in staged files")

        print("[5/7] Compressing share archive ...")
        file_count = make_zip(stage, zip_path)

        print("[6/7] Re-scanning final ZIP ...")
        archive_issues = verify_archive(zip_path)
        if archive_issues:
            for issue in archive_issues:
                print(f"  [BLOCK] {issue['path']} ({issue['rule']})")
            remove_artifacts(zip_path)
            raise RuntimeError("final archive failed privacy verification")

        print("[7/7] Writing checksum and privacy manifest ...")
        checksum_path, manifest_path, digest = write_sidecars(zip_path, file_count)
        trace_build(
            run_id,
            "terminal_success",
            files=file_count,
            bytes=zip_path.stat().st_size,
            sha256=digest,
        )
    except Exception as exc:
        trace_build(run_id, "terminal_failure", errorType=type(exc).__name__, error=str(exc))
        remove_artifacts(zip_path)
        raise
    finally:
        shutil.rmtree(ROOT / STAGE_NAME, ignore_errors=True)
        shutil.rmtree(build_temp, ignore_errors=True)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print()
    print(f"[OK] {zip_path.name} ({size_mb:.1f} MB, {file_count} files)")
    print(f"[OK] SHA-256 {digest}")
    print(f"[OK] checksum: {checksum_path.name}")
    print(f"[OK] manifest: {manifest_path.name}")
    print("Private state, local DBs, logs, editor memory and internal notes are absent.")
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a verified Stock Terminal share ZIP")
    parser.add_argument("--out", type=Path, default=None, help="Output ZIP path")
    args = parser.parse_args()
    try:
        build(args.out)
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
