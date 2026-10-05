#!/usr/bin/env python3
"""Check if current time is within the usable trading window for a workflow.

Used by workflows to abort schedule events that fire too late. workflow_dispatch
always bypasses this check (manual override).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.trading.execution_status import can_submit_live_orders  # noqa: E402
from src.trading.us_equity_calendar import is_us_equity_trading_day, nyse_session_close_et  # noqa: E402

ET = ZoneInfo("America/New_York")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflow",
        choices=["wheel", "options", "drip"],
        required=True,
        help="Workflow track: wheel (morning equity), options (afternoon), or drip (daily)",
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="Write outputs to $GITHUB_OUTPUT",
    )
    args = parser.parse_args()

    now = datetime.now(tz=ET)
    day = now.date()

    # Check basic trading day first
    if not is_us_equity_trading_day(day):
        print(f"in_window=false reason=market_closed:{day.isoformat()}")
        if args.github_output:
            out = os.environ.get("GITHUB_OUTPUT")
            if out:
                with open(out, "a", encoding="utf-8") as fh:
                    fh.write("in_window=false\n")
                    fh.write(f"reason=market_closed:{day.isoformat()}\n")
        return 1

    # Workflow-specific cutoffs
    if args.workflow == "wheel":
        # Morning wheel: equity orders with DAY TIF, cutoff 15:30 ET
        ok, reason = can_submit_live_orders(now, cutoff_et="15:30")
        in_window = ok
    elif args.workflow == "options":
        # Afternoon options: options can trade until 15:55 ET
        ok, reason = can_submit_live_orders(now, cutoff_et="15:55")
        in_window = ok
    elif args.workflow == "drip":
        # Drip residual: must complete before equity close (16:00 ET, or 13:00 on early close)
        close = nyse_session_close_et(now)
        t = now.time()
        open_time = time(9, 30)
        if t < open_time:
            in_window = False
            reason = "before_open"
        elif t >= close:
            in_window = False
            reason = "after_close"
        else:
            in_window = True
            reason = "ok"
    else:
        return 2

    print(f"in_window={str(in_window).lower()} workflow={args.workflow} reason={reason}")

    if args.github_output:
        out = os.environ.get("GITHUB_OUTPUT")
        if not out:
            print("GITHUB_OUTPUT not set", file=sys.stderr)
            return 2
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"in_window={'true' if in_window else 'false'}\n")
            fh.write(f"reason={reason}\n")

    return 0 if in_window else 1


if __name__ == "__main__":
    raise SystemExit(main())
