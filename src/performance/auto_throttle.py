"""Auto-throttle after sustained negative active return vs SPY."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from src.portfolio.phase13_policy import AUTO_THROTTLE_WEEKS

STATE_PATH = Path("data/performance/auto_throttle_state.json")


def _load() -> Dict[str, Any]:
    if not STATE_PATH.is_file():
        return {"negative_weeks": 0, "history": [], "throttled": False}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"negative_weeks": 0, "history": [], "throttled": False}


def _save(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def record_active_return(active_return_pct: float, *, weeks: int = AUTO_THROTTLE_WEEKS) -> Dict[str, Any]:
    state = _load()
    hist: List[Dict[str, Any]] = list(state.get("history") or [])
    hist.append(
        {
            "at": datetime.utcnow().isoformat() + "Z",
            "active_return_pct": float(active_return_pct),
        }
    )
    hist = hist[-52:]
    # consecutive trailing negatives
    neg = 0
    for row in reversed(hist):
        if float(row.get("active_return_pct") or 0.0) < 0:
            neg += 1
        else:
            break
    throttled = neg >= int(weeks)
    state = {
        "negative_weeks": neg,
        "history": hist,
        "throttled": throttled,
        "threshold_weeks": int(weeks),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    _save(state)
    return state


def apply_throttle_to_run_config(run_config: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(run_config)
    state = _load()
    out["auto_throttle"] = {
        "throttled": bool(state.get("throttled")),
        "negative_weeks": int(state.get("negative_weeks") or 0),
        "threshold_weeks": int(state.get("threshold_weeks") or AUTO_THROTTLE_WEEKS),
    }
    if not state.get("throttled"):
        return out
    out["max_buy_tickers"] = min(int(out.get("max_buy_tickers", 8)), 3)
    out["cash_buffer_pct"] = max(float(out.get("cash_buffer_pct", 0.12)), 0.20)
    out["phase13_special_opportunity"] = False  # defensive: no stretching cash
    out["biotech_mechanical_force_off"] = True
    return out
