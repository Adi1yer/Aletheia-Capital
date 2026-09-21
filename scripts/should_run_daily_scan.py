#!/usr/bin/env python3
"""GitHub Actions gate: run daily wheel jobs on every NYSE open weekday.

Also supports same-ET-day skip/mark so a late ``schedule`` cron does not
full-rebalance twice after an earlier successful morning run.
"""

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
from src.trading.wheel_daily_once import (  # noqa: E402
    check_already_ran,
    mark_ran_et_day,
)

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
        help="Write outputs to $GITHUB_OUTPUT",
    )
    parser.add_argument(
        "--check-already-ran",
        action="store_true",
        help="Check data/performance marker; set already_ran=true|false",
    )
    parser.add_argument(
        "--mark-ran-today",
        action="store_true",
        help="Write today's ET date to the same-day completion marker",
    )
    args = parser.parse_args()

    if args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        day = datetime.now(tz=ET).date()

    if args.mark_ran_today:
        path = mark_ran_et_day(day)
        print(f"marked_ran={day.isoformat()} path={path}")
        if args.github_output:
            out = os.environ.get("GITHUB_OUTPUT")
            if out:
                with open(out, "a", encoding="utf-8") as fh:
                    fh.write(f"marked_ran={day.isoformat()}\n")
        return 0

    if args.check_already_ran:
        already, reason = check_already_ran(day)
        print(f"already_ran={str(already).lower()} reason={reason}")
        if args.github_output:
            out = os.environ.get("GITHUB_OUTPUT")
            if not out:
                print("GITHUB_OUTPUT not set", file=sys.stderr)
                return 2
            with open(out, "a", encoding="utf-8") as fh:
                fh.write(f"already_ran={'true' if already else 'false'}\n")
                fh.write(f"reason={reason}\n")
        return 0

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
