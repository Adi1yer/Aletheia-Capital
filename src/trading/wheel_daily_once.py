"""Same-calendar-day guard for the morning wheel full rebalance.

Prevents a late GitHub ``schedule`` cron from re-running ``wheel-10k`` after a
successful earlier run (manual dispatch or on-time cron) the same ET day.
Afternoon options manage is unaffected.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple, Union
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Persisted under data/performance so Actions cache restore sees it next run.
MARKER_NAME = "wheel_daily_completed_et.txt"
DEFAULT_MARKER_DIR = Path("data/performance")


def _as_et_date(value: Optional[Union[date, datetime]] = None) -> date:
    if value is None:
        return datetime.now(tz=ET).date()
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=ET)
        return dt.astimezone(ET).date()
    return value


def marker_path(marker_dir: Optional[Path] = None) -> Path:
    return (marker_dir or DEFAULT_MARKER_DIR) / MARKER_NAME


def read_completed_et_day(marker_dir: Optional[Path] = None) -> Optional[date]:
    path = marker_path(marker_dir)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        return date.fromisoformat(text)
    except (OSError, ValueError, IndexError):
        return None


def already_ran_et_day(
    day: Optional[Union[date, datetime]] = None,
    *,
    marker_dir: Optional[Path] = None,
) -> bool:
    completed = read_completed_et_day(marker_dir)
    if completed is None:
        return False
    return completed == _as_et_date(day)


def mark_ran_et_day(
    day: Optional[Union[date, datetime]] = None,
    *,
    marker_dir: Optional[Path] = None,
) -> Path:
    path = marker_path(marker_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    et_day = _as_et_date(day)
    path.write_text(f"{et_day.isoformat()}\n", encoding="utf-8")
    return path


def check_already_ran(
    day: Optional[Union[date, datetime]] = None,
    *,
    marker_dir: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Return (already_ran, reason)."""
    et_day = _as_et_date(day)
    completed = read_completed_et_day(marker_dir)
    if completed is None:
        return False, f"no_marker:{et_day.isoformat()}"
    if completed == et_day:
        return True, f"already_ran_et:{et_day.isoformat()}"
    return False, f"marker_stale:{completed.isoformat()}:today:{et_day.isoformat()}"
