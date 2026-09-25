#!/usr/bin/env python3
"""Watchdog: send MISSED RUN email if the morning wheel job did not succeed today."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.performance.official_track import (  # noqa: E402
    missed_run_due,
    read_last_successful_run,
)
from src.utils.wheel_email import build_missed_run_email  # noqa: E402

ET = ZoneInfo("America/New_York")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-missed", action="store_true")
    parser.add_argument("--date", help="Override ET day YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.date:
        now = datetime.strptime(args.date, "%Y-%m-%d").replace(
            hour=18, minute=0, tzinfo=ET
        )
    else:
        now = datetime.now(tz=ET)

    last = read_last_successful_run()
    due, reason = missed_run_due(now=now, last_success=last, force=args.force_missed)
    print(f"missed={due} reason={reason} last={last}")
    if not due:
        return 0

    subject, text, html = build_missed_run_email(
        day_label=now.date().isoformat(),
        reason=reason,
        last_success=last.isoformat() if last else None,
    )
    if args.dry_run:
        print(subject)
        print(text)
        return 0

    recipient = (os.environ.get("RECIPIENT_EMAIL") or "").strip()
    if not recipient:
        print("RECIPIENT_EMAIL unset — not sending", file=sys.stderr)
        return 2
    from src.utils.email import get_email_notifier

    ok = get_email_notifier().send_email(recipient, subject, text, html)
    print(f"sent={ok}")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
