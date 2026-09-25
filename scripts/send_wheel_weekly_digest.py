#!/usr/bin/env python3
"""Friday weekly wheel digest from official snapshots."""

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
    build_track_record,
    load_snapshots,
    weekly_slice,
)
from src.utils.wheel_email import build_wheel_weekly_email  # noqa: E402

ET = ZoneInfo("America/New_York")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Friday (or as-of) YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.date:
        friday = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        friday = datetime.now(tz=ET).date()

    snaps = load_snapshots()
    week = weekly_slice(snaps, friday)
    track = build_track_record(snaps, asof=friday)
    notes = []
    if not week:
        notes.append("No official snapshots this week — morning job may have missed persist.")
    subject, text, html = build_wheel_weekly_email(
        friday_label=friday.isoformat(),
        track=track,
        week_snaps=week,
        ops_notes=notes,
        fingerprint=str(track.get("config_fingerprint") or ""),
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
