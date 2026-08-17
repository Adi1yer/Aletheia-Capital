"""Biweekly full-rebalance cadence for Beat SPY (weekly runs still do stops)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Tuple

STATE_PATH = Path("data/performance/beat_spy_rebalance.json")


def _load(path: Path = STATE_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(payload: Dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def should_skip_new_buys(
    *,
    interval_weeks: int = 2,
    now: datetime | None = None,
    path: Path = STATE_PATH,
) -> Tuple[bool, Dict[str, Any]]:
    """True → risk-only week (stops, no rebuild/adds). First run is always full."""
    now = now or datetime.utcnow()
    interval_weeks = max(1, int(interval_weeks or 1))
    state = _load(path)
    last_raw = state.get("last_full_rebalance_at")
    if not last_raw:
        return False, {"reason": "no_prior_full_rebalance", "last_full_rebalance_at": None}
    try:
        last = datetime.fromisoformat(str(last_raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return False, {"reason": "bad_timestamp", "last_full_rebalance_at": last_raw}
    elapsed_days = (now - last).days
    skip = elapsed_days < int(interval_weeks) * 7
    return skip, {
        "reason": "inside_interval" if skip else "interval_elapsed",
        "last_full_rebalance_at": last_raw,
        "elapsed_days": elapsed_days,
        "interval_weeks": interval_weeks,
    }


def mark_full_rebalance(path: Path = STATE_PATH) -> None:
    _save({"last_full_rebalance_at": datetime.utcnow().isoformat() + "Z"})
