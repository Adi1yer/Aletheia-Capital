"""Pre-trade portfolio simulation gate."""

from __future__ import annotations

from typing import Any, Dict


def simulate_pretrade(decisions: Dict[str, Any], risk_analysis: Dict[str, Any], *, max_sector_pct: float = 0.35) -> Dict[str, Any]:
    notional = 0.0
    actionable = 0
    for t, d in (decisions or {}).items():
        if hasattr(d, "model_dump"):
            d = d.model_dump()
        if not isinstance(d, dict):
            continue
        if d.get("action") not in ("buy", "sell", "short", "cover"):
            continue
        actionable += 1
        px = float((risk_analysis.get(t) or {}).get("current_price") or 0.0)
        qty = int(d.get("quantity") or 0)
        notional += abs(px * qty)
    hard_block = actionable > 0 and notional <= 0
    return {
        "actionable_decisions": actionable,
        "projected_notional": round(notional, 2),
        "max_sector_pct": max_sector_pct,
        "hard_block": hard_block,
        "block_reason": "no_notional_with_actionable_decisions" if hard_block else "",
    }

