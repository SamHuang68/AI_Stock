#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build a shareable Stock Terminal v5.0 zip.

Strips private user data (API keys, watches, alert config, draw store,
personal chip snapshots), regenerable local DBs, and internal revision notes.

Usage:
  python scripts/build_dist.py
  python scripts/build_dist.py --out /path/to/Stock_Terminal_v5.0.zip
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE_NAME = "Stock_Terminal"
ZIP_NAME = "Stock_Terminal_v5.0.zip"

# Never copy these basenames anywhere under the stage tree
SECRET_BASENAMES = {
    "ai_key.txt",
    "alert_config.json",
    "alert_rules.json",
    "watch_rules.json",
    "watch_state.json",
    "draw_store.json",
    "secrets.json",
    "positions_backup.json",
    "watches_backup.json",
    "revision.md",  # internal changelog / personal notes
}

SECRET_SUFFIXES = (".key", ".pem")
SECRET_PREFIXES = (".env",)

# Directory names to skip entirely while walking
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
    "Stock_Terminal",
    "logs",
    "scratch",
    "installer",  # heavy PyInstaller tooling; not needed to run
}

# Under data/: only allow these (plus empty history folders + README)
# 刻意不含：market.db / pulse_history.db / tdcc_holders.db / margin_cycle.db（可重建大庫）
DATA_ALLOW_FILES = {
    "etf_catalog.json",
    "universe.json",
    "tw_names_backup.json",
    # public market seeds / caches (not user identity)
    "macro_track.db",
    "cbc_policy_rates.csv",
    "cbc_policy_rate_changes.csv",
    "tw_margin_mix_daily.csv",
    "txf_daily.csv",
    "margin_ratio_history.csv",
    "twoii_daily.csv",
}

# Hard-block regenerable / personal DBs even if listed elsewhere
DATA_BLOCK_FILES = {
    "market.db",
    "market.db-wal",
    "market.db-shm",
    "pulse_history.db",
    "pulse_history.db-wal",
    "pulse_history.db-shm",
    "tdcc_holders.db",
    "tdcc_holders.db-wal",
    "tdcc_holders.db-shm",
    "margin_cycle.db",
    "margin_cycle.db-wal",
    "margin_cycle.db-shm",
}

DATA_ALLOW_DIRS = {
    "macro_seeds",
    "etf_history",  # only README — json snapshots skipped
    "chip_history",  # only README — personal snapshots skipped
}

HISTORY_SKIP_SUFFIXES = (".json", ".csv", ".txt")  # under etf_history / chip_history
HISTORY_KEEP = {"readme.txt"}


def is_secret_name(name: str) -> bool:
    lower = name.lower()
    if lower in {s.lower() for s in SECRET_BASENAMES}:
        return True
    if lower in {s.lower() for s in DATA_BLOCK_FILES}:
        return True
    if any(lower.endswith(suf) for suf in SECRET_SUFFIXES):
        return True
    if any(lower.startswith(pref) for pref in SECRET_PREFIXES):
        return True
    return False


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES or name.endswith(".egg-info")


def copy_tree_filtered(src: Path, dst: Path) -> int:
    """Copy src→dst skipping caches and secret basenames. Returns file count."""
    n = 0
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]
        rel = Path(root).relative_to(src)
        out_dir = dst / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        for fn in files:
            if is_secret_name(fn):
                continue
            if fn.endswith((".pyc", ".pyo", ".log", ".bak", ".tmp", ".orig")):
                continue
            shutil.copy2(Path(root) / fn, out_dir / fn)
            n += 1
    return n


def stage_data(stage: Path) -> None:
    data_src = ROOT / "data"
    data_dst = stage / "data"
    data_dst.mkdir(parents=True, exist_ok=True)

    if not data_src.is_dir():
        print("[WARN] no data/ directory")
        return

    for fn in DATA_ALLOW_FILES:
        src = data_src / fn
        if src.is_file():
            shutil.copy2(src, data_dst / fn)
            print(f"  + data/{fn}")
        else:
            print(f"  · skip missing data/{fn}")

    # macro_seeds — public CSVs only
    seeds_src = data_src / "macro_seeds"
    if seeds_src.is_dir():
        seeds_dst = data_dst / "macro_seeds"
        seeds_dst.mkdir(parents=True, exist_ok=True)
        for p in seeds_src.iterdir():
            if p.is_file() and not is_secret_name(p.name) and p.suffix.lower() in {
                ".csv", ".json", ".txt", ".md"
            }:
                shutil.copy2(p, seeds_dst / p.name)
                print(f"  + data/macro_seeds/{p.name}")

    # empty history dirs with README only (no personal snapshots)
    for hist in ("etf_history", "chip_history"):
        hdst = data_dst / hist
        hdst.mkdir(parents=True, exist_ok=True)
        readme = hdst / "README.txt"
        if hist == "etf_history":
            readme.write_text(
                "ETF holding snapshots appear here after running server/etf_delta_tracker.py\n",
                encoding="utf-8",
            )
        else:
            readme.write_text(
                "Institutional chip daily snapshots appear here after chip scheduler/tracker runs.\n"
                "Share builds intentionally omit personal history JSON files.\n",
                encoding="utf-8",
            )
        print(f"  + data/{hist}/README.txt (history JSON omitted)")

    # Safety net: delete any secret that slipped in
    for root, _dirs, files in os.walk(data_dst):
        for fn in files:
            if is_secret_name(fn) or (
                Path(root).name in ("etf_history", "chip_history")
                and fn.lower() not in HISTORY_KEEP
                and fn.lower().endswith(HISTORY_SKIP_SUFFIXES)
            ):
                p = Path(root) / fn
                p.unlink(missing_ok=True)
                print(f"  - scrubbed {p.relative_to(stage)}")


def scrub_stage(stage: Path) -> None:
    """Final pass: remove any secret-named file anywhere in stage."""
    for root, dirs, files in os.walk(stage):
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]
        for fn in files:
            if is_secret_name(fn):
                p = Path(root) / fn
                p.unlink(missing_ok=True)
                print(f"  - scrubbed {p.relative_to(stage)}")


def make_zip(stage: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(stage):
            dirs[:] = sorted(d for d in dirs if not should_skip_dir(d))
            for fn in sorted(files):
                if is_secret_name(fn):
                    continue
                full = Path(root) / fn
                arc = full.relative_to(stage.parent)
                zf.write(full, arcname=str(arc).replace("\\", "/"))


def verify_no_secrets(zip_path: Path) -> list[str]:
    bad = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if is_secret_name(name):
                bad.append(info.filename)
            # chip/etf history must not contain json snapshots
            parts = Path(info.filename).parts
            if len(parts) >= 3 and parts[-2] in ("chip_history", "etf_history"):
                if name.lower() != "readme.txt" and name.lower().endswith((".json", ".csv")):
                    bad.append(info.filename)
    return bad


def build(out: Path | None = None) -> Path:
    os.chdir(ROOT)
    print("=" * 50)
    print(" Build Stock_Terminal distribution zip (v5.0)")
    print("=" * 50)

    # Fresh v2 HTML if sources present
    if (ROOT / "stock_terminal.html").exists() and (ROOT / "build_v2.py").exists():
        print("Building v2 ...")
        rc = os.system(f'"{sys.executable}" build_v2.py')
        if rc != 0:
            print("[WARN] build_v2.py exited non-zero; continuing with existing HTML")

    stage = ROOT / STAGE_NAME
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    print("Staging src / server / scripts / docs / assets ...")
    n = 0
    n += copy_tree_filtered(ROOT / "src", stage / "src")
    n += copy_tree_filtered(ROOT / "server", stage / "server")
    n += copy_tree_filtered(ROOT / "scripts", stage / "scripts")
    # docs without revision.md (filtered by SECRET_BASENAMES)
    if (ROOT / "docs").is_dir():
        n += copy_tree_filtered(ROOT / "docs", stage / "docs")
    if (ROOT / "assets").is_dir():
        n += copy_tree_filtered(ROOT / "assets", stage / "assets")

    print("Staging root files ...")
    for fn in (
        "stock_terminal.html",
        "stock_terminal_v2.html",
        "build_v2.py",
        "build_order.py",
        "README.md",
        "START_TIP.cmd",
        "TIP_BRANCH",
        "VERSION",
        ".cursorrules",
        ".gitignore",
    ):
        src = ROOT / fn
        if src.is_file():
            shutil.copy2(src, stage / fn)
            print(f"  + {fn}")
            n += 1
        else:
            print(f"  [MISS] {fn}")

    print("Staging data (public only) ...")
    stage_data(stage)
    print("Final secret scrub ...")
    scrub_stage(stage)

    zip_path = Path(out) if out else (ROOT / ZIP_NAME)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Compressing → {zip_path} ...")
    make_zip(stage, zip_path)
    shutil.rmtree(stage)

    bad = verify_no_secrets(zip_path)
    if bad:
        print("[FAIL] secrets or personal history found in zip:")
        for b in bad:
            print("  ", b)
        zip_path.unlink(missing_ok=True)
        sys.exit(1)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print()
    print(f"[OK] {zip_path.name}  ({size_mb:.1f} MB)")
    print("Recipient: unzip → read docs/TIP_UX.md → START_TIP.cmd (or scripts\\go.bat)")
    print("Private data stripped: API keys, watches, alerts, draw_store,")
    print("  chip/etf history JSON, market/pulse/tdcc/margin local DBs.")
    return zip_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Build shareable Stock Terminal zip")
    ap.add_argument("--out", type=Path, default=None, help="Output zip path")
    args = ap.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
