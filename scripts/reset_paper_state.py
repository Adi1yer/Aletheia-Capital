#!/usr/bin/env python3
"""Archive stale performance/ledger artifacts when starting a fresh paper account.

Also prints the wheel-10k account reset checklist (Alpaca is manual).
"""

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

CHECKLIST = """
Wheel-10k paper reset checklist
--------------------------------
1. Alpaca paper: cancel open orders, liquidate all positions (or create a new paper account).
2. Reset buying power / equity to $10,000.
3. Confirm options trading is enabled on the account.
4. If new account: update GitHub secrets ALPACA_API_KEY / ALPACA_SECRET_KEY / ALPACA_BASE_URL.
5. Run: poetry run python scripts/reset_paper_state.py --yes
6. Push wheel-10k workflow (already on weekly-scan.yml) then Actions → Weekly Scan → Run workflow
   mid-morning ET (manual dispatch bypasses holiday gate; RTH gate still applies).
7. Expect email sections: WHEEL HYBRID + Covered Calls / CSP (not Beat SPY concentrated book).
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm archive (required to mutate files).",
    )
    parser.add_argument(
        "--checklist-only",
        action="store_true",
        help="Print the account reset checklist and exit.",
    )
    args = parser.parse_args()
    print(CHECKLIST.strip() + "\n")
    if args.checklist_only:
        return
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
