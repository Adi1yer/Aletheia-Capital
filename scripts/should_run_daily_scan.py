#!/usr/bin/env python3
"""GitHub Actions gate: run daily wheel jobs on every NYSE open weekday."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Allow `python3 scripts/...` before Poetry install (stdlib calendar only).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.trading.us_equity_calendar import should_run_daily_trading_session  # noqa: E402

ET = ZoneInfo("America/New_York")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        help="Override ET calendar day as YYYY-MM-DD (default: now in America/New_York)",
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="Write should_run / reason to $GITHUB_OUTPUT",
    )
    args = parser.parse_args()

    if args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        day = datetime.now(tz=ET).date()

    should_run, reason = should_run_daily_trading_session(day)
    print(f"should_run={str(should_run).lower()} reason={reason}")

    if args.github_output:
        out = os.environ.get("GITHUB_OUTPUT")
        if not out:
            print("GITHUB_OUTPUT not set", file=sys.stderr)
            return 2
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"should_run={'true' if should_run else 'false'}\n")
            fh.write(f"reason={reason}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
