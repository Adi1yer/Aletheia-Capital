#!/usr/bin/env python3
"""Archive stale performance/ledger artifacts when starting a fresh paper account."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ARCHIVE_DIRS = (
    "data/performance",
    "data/scan_cache",
    "data/cache",
    "data/biotech",
    "data/hedge",
    "data/options_income",
    "data/congressional",
    "data/macro_etf",
    "data/crypto",
    "data/daily_snapshots",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm archive (required to mutate files).",
    )
    args = parser.parse_args()
    if not args.yes:
        print("Dry run — pass --yes to archive existing state under data/archive/")
        for rel in ARCHIVE_DIRS:
            p = ROOT / rel
            if p.exists():
                print(f"  would archive: {rel}")
        return

    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dest_root = ROOT / "data" / "archive" / f"pre_reset_{stamp}"
    dest_root.mkdir(parents=True, exist_ok=True)
    for rel in ARCHIVE_DIRS:
        src = ROOT / rel
        if not src.exists():
            continue
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        (ROOT / rel).mkdir(parents=True, exist_ok=True)
        print(f"archived {rel} -> {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
