"""Holdout promotion gates for biotech policy updates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.biotech.thesis_ledger import recent_entries

logger = structlog.get_logger()

HOLD_PATH = Path("data/biotech/calibration_hold.json")


def calibration_hold_active(path: Optional[Path] = None) -> bool:
    path = path or HOLD_PATH
    if not path.is_file():
        return False
    try:
        with open(path, encoding="utf-8") as f:
            return bool(json.load(f).get("active"))
    except Exception:
        return False


def set_calibration_hold(active: bool, reason: str = "", path: Path = HOLD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"active": active, "reason": reason}, f, indent=2)


def _closed_by_run_date(weeks: int = 24) -> Dict[str, List[Dict[str, Any]]]:
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for r in recent_entries(weeks=weeks):
        if str(r.get("status") or "") not in ("closed", "expired"):
            continue
        if r.get("pnl_pct_of_premium") is None:
            continue
        d = str(r.get("run_date") or "")[:10]
        if d:
            by_date.setdefault(d, []).append(r)
    return by_date


def _avg_pnl(rows: List[Dict[str, Any]], arm: Optional[str] = None) -> float:
    pnls = []
    for r in rows:
        if arm and str(r.get("arm")) != arm:
            continue
        pnls.append(float(r.get("pnl_pct_of_premium") or 0))
    return sum(pnls) / len(pnls) if pnls else 0.0


def evaluate_biotech_proposal(
    proposed_policy: Dict[str, Any],
    *,
    weeks: int = 24,
    holdout_run_dates: int = 2,
    tolerance: float = 2.0,
) -> Dict[str, Any]:
    """
    Compare holdout run dates (most recent N) avg PnL vs train window.
    Promote if holdout llm_gated avg is not worse than train by more than tolerance.
    """
    if calibration_hold_active():
        return {
            "promote": False,
            "reason": "calibration_hold_active",
            "holdout": {},
            "train": {},
        }

    by_date = _closed_by_run_date(weeks=weeks)
    dates = sorted(by_date.keys())
    if len(dates) < holdout_run_dates + 2:
        return {
            "promote": True,
            "reason": "insufficient_run_dates_for_holdout",
            "holdout": {},
            "train": {},
        }

    holdout_dates = set(dates[-holdout_run_dates:])
    train_rows: List[Dict[str, Any]] = []
    holdout_rows: List[Dict[str, Any]] = []
    for d, rows in by_date.items():
        if d in holdout_dates:
            holdout_rows.extend(rows)
        else:
            train_rows.extend(rows)

    train_llm = _avg_pnl(train_rows, "llm_gated")
    holdout_llm = _avg_pnl(holdout_rows, "llm_gated")
    train_mech = _avg_pnl(train_rows, "mechanical")
    holdout_mech = _avg_pnl(holdout_rows, "mechanical")

    promote = True
    reason = "holdout_ok"
    if len(holdout_rows) >= 2 and holdout_llm < train_llm - tolerance:
        promote = False
        reason = f"holdout llm_gated avg {holdout_llm:.1f}% vs train {train_llm:.1f}%"

    return {
        "promote": promote,
        "reason": reason,
        "holdout": {
            "dates": sorted(holdout_dates),
            "count": len(holdout_rows),
            "llm_gated_avg_pnl_pct": round(holdout_llm, 2),
            "mechanical_avg_pnl_pct": round(holdout_mech, 2),
        },
        "train": {
            "count": len(train_rows),
            "llm_gated_avg_pnl_pct": round(train_llm, 2),
            "mechanical_avg_pnl_pct": round(train_mech, 2),
        },
        "proposed_policy_keys": list(proposed_policy.keys()),
    }
