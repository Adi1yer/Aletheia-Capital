"""Month-3 / Month-6 Beat SPY capital-path gates."""

from __future__ import annotations

from typing import Any, Dict, Optional

MONTH3_WEEKS = 12
MONTH6_WEEKS = 26


def evaluate_beat_spy_gates(scorecard: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Pass/fail from rolling IR scorecard. Month 3 is IR>=0; month 6 uses full gates."""
    scorecard = scorecard or {}
    weeks = int(scorecard.get("weeks_recorded") or 0)
    ir = scorecard.get("information_ratio")
    gates = scorecard.get("gates") or {}
    month3_due = weeks >= MONTH3_WEEKS
    month6_due = weeks >= MONTH6_WEEKS
    ir_val = float(ir) if ir is not None else None
    month3_pass = bool(month3_due and ir_val is not None and ir_val >= 0.0)
    month6_pass = bool(month6_due and gates.get("all_ok"))
    return {
        "weeks_recorded": weeks,
        "information_ratio": ir_val,
        "month3": {
            "due": month3_due,
            "weeks_needed": MONTH3_WEEKS,
            "rule": "IR of active vs SPY >= 0",
            "pass": month3_pass,
            "action": (
                "continue"
                if not month3_due
                else ("continue" if month3_pass else "redesign_factors_or_universe")
            ),
        },
        "month6": {
            "due": month6_due,
            "weeks_needed": MONTH6_WEEKS,
            "rule": "IR/Sharpe/return/DD gates all_ok",
            "pass": month6_pass,
            "action": (
                "continue"
                if not month6_due
                else ("owner_1k_live_plus_paper_twin" if month6_pass else "redesign_sprint")
            ),
        },
    }
