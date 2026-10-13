#!/usr/bin/env python3
"""Watchdog: check if daily workflows ran successfully today, auto-dispatch missed ones.

This script is the core of the self-healing watchdog system. For each workflow:
1. Checks if it already ran successfully today (via same-day marker)
2. Checks if it's still within the usable market window
3. If missed and still viable, dispatches via repository_dispatch
4. Sends email notifications for awareness

Runs after primary cron slots but before market close, providing automatic recovery
from GitHub Actions schedule delays without manual intervention.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.trading.execution_status import can_submit_live_orders
from src.trading.us_equity_calendar import is_us_equity_trading_day, nyse_session_close_et
from src.trading.wheel_daily_once import (
    DRIP_MARKER_NAME,
    MARKER_NAME,
    OPTIONS_MARKER_NAME,
    check_already_ran,
)

ET = ZoneInfo("America/New_York")

DRIP_MARKER_DIR = Path("data/performance/growth_income_drip_v1")
DEFAULT_MARKER_DIR = Path("data/performance")


class WorkflowConfig(NamedTuple):
    name: str
    track: str
    dispatch_type: str
    workflow_file: str
    cutoff_et: str
    marker_name: str
    marker_dir: Path


WORKFLOWS = [
    WorkflowConfig(
        name="Daily Wheel Scan",
        track="wheel",
        dispatch_type="trigger-daily-wheel-scan",
        workflow_file="daily-wheel-scan.yml",
        cutoff_et="15:30",
        marker_name=MARKER_NAME,
        marker_dir=DEFAULT_MARKER_DIR,
    ),
    WorkflowConfig(
        name="Wheel Options Daily Manage",
        track="options",
        dispatch_type="trigger-wheel-options-daily",
        workflow_file="wheel-options-daily.yml",
        cutoff_et="15:55",
        marker_name=OPTIONS_MARKER_NAME,
        marker_dir=DEFAULT_MARKER_DIR,
    ),
    WorkflowConfig(
        name="Growth-Income-Drip Daily Snapshot",
        track="drip",
        dispatch_type="trigger-drip-daily-snapshot",
        workflow_file="drip-daily-snapshot.yml",
        cutoff_et=None,  # Uses market close time
        marker_name=DRIP_MARKER_NAME,
        marker_dir=DRIP_MARKER_DIR,
    ),
]


def is_in_market_window(workflow: WorkflowConfig, now: datetime) -> tuple[bool, str]:
    """Check if workflow can still run successfully at the given time."""
    if not is_us_equity_trading_day(now.date()):
        return False, "market_closed"

    if workflow.cutoff_et:
        ok, reason = can_submit_live_orders(now, cutoff_et=workflow.cutoff_et)
        return ok, reason
    else:
        close_time = nyse_session_close_et(now)
        t = now.time()
        open_time = datetime.strptime("09:30", "%H:%M").time()
        if t < open_time:
            return False, "before_open"
        elif t >= close_time:
            return False, "after_close"
        else:
            return True, "ok"


def dispatch_workflow(repo: str, workflow: WorkflowConfig, dry_run: bool = False) -> bool:
    """Trigger workflow via repository_dispatch using gh CLI."""
    cmd = [
        "gh",
        "api",
        f"/repos/{repo}/dispatches",
        "-X",
        "POST",
        "-f",
        f"event_type={workflow.dispatch_type}",
    ]

    print(f"Dispatching {workflow.name} ({workflow.dispatch_type})...")
    if dry_run:
        print(f"DRY RUN: would run: {' '.join(cmd)}")
        return True

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"✓ Dispatched {workflow.name} successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to dispatch {workflow.name}: {e.stderr}", file=sys.stderr)
        return False


def send_notification(
    workflow_name: str,
    action: str,
    reason: str,
    recipient: str | None = None,
    dry_run: bool = False,
) -> bool:
    """Send email notification about watchdog action."""
    if not recipient:
        print(f"No recipient configured, skipping email notification")
        return False

    subject = f"[Watchdog] {action}: {workflow_name}"
    body = f"""
Workflow Watchdog Action
========================

Workflow: {workflow_name}
Action: {action}
Reason: {reason}
Time: {datetime.now(tz=ET).strftime('%Y-%m-%d %H:%M:%S %Z')}

This is an automated notification from the daily workflows watchdog.
"""

    if dry_run:
        print(f"DRY RUN: would send email to {recipient}")
        print(f"Subject: {subject}")
        print(body)
        return True

    try:
        from src.utils.email import get_email_notifier

        ok = get_email_notifier().send_email(recipient, subject, body, body)
        if ok:
            print(f"✓ Sent notification email to {recipient}")
        else:
            print(f"✗ Failed to send notification email", file=sys.stderr)
        return ok
    except Exception as e:
        print(f"✗ Error sending notification: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repository (owner/name)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check and report but don't dispatch or send emails",
    )
    parser.add_argument(
        "--force-wheel",
        action="store_true",
        help="Force check wheel even if marker says already ran",
    )
    parser.add_argument(
        "--force-options",
        action="store_true",
        help="Force check options even if marker says already ran",
    )
    parser.add_argument(
        "--force-drip",
        action="store_true",
        help="Force check drip even if marker says already ran",
    )
    args = parser.parse_args()

    now = datetime.now(tz=ET)
    recipient = (os.environ.get("RECIPIENT_EMAIL") or "").strip()

    if not is_us_equity_trading_day(now.date()):
        print(f"Not a trading day ({now.date().isoformat()}), nothing to check.")
        return 0

    print(f"\n{'='*60}")
    print(f"Daily Workflows Watchdog Check")
    print(f"Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"{'='*60}\n")

    force_map = {
        "wheel": args.force_wheel,
        "options": args.force_options,
        "drip": args.force_drip,
    }

    dispatched_any = False
    errors = []

    for workflow in WORKFLOWS:
        print(f"\nChecking {workflow.name} ({workflow.track})...")

        force = force_map.get(workflow.track, False)
        already_ran, ran_reason = check_already_ran(
            now, marker_dir=workflow.marker_dir, marker_name=workflow.marker_name
        )

        if already_ran and not force:
            print(f"  ✓ Already completed today ({ran_reason})")
            continue

        if force:
            print(f"  ⚠ Forced check (ignoring marker)")

        in_window, window_reason = is_in_market_window(workflow, now)

        if not in_window:
            msg = f"  ⏭ Missed but outside window ({window_reason}), cannot dispatch"
            print(msg)
            # Send notification for missed run that can't be recovered
            if recipient and not args.dry_run:
                send_notification(
                    workflow.name,
                    "Missed (cannot recover)",
                    f"Missed today and outside window: {window_reason}",
                    recipient,
                    args.dry_run,
                )
            continue

        print(f"  ⚠ MISSED and still in window ({window_reason})")
        print(f"     Attempting auto-dispatch...")

        ok = dispatch_workflow(args.repo, workflow, args.dry_run)
        if ok:
            dispatched_any = True
            if recipient:
                send_notification(
                    workflow.name,
                    "Auto-dispatched",
                    f"Workflow was overdue, dispatched automatically at {now.strftime('%H:%M %Z')}",
                    recipient,
                    args.dry_run,
                )
        else:
            errors.append(workflow.name)

    print(f"\n{'='*60}")
    if dispatched_any:
        print(f"✓ Watchdog dispatched {sum(1 for w in WORKFLOWS if force_map.get(w.track) or not check_already_ran(now, marker_dir=w.marker_dir, marker_name=w.marker_name)[0])} workflow(s)")
    else:
        print("✓ All workflows completed or outside recovery window")

    if errors:
        print(f"✗ Errors dispatching: {', '.join(errors)}")
        return 1

    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
