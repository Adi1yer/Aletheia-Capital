"""Beat SPY run profile defaults (~$10k paper)."""

from __future__ import annotations

from typing import Any, Dict


def apply_beat_spy_defaults(run_config: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(run_config)
    if not out.get("beat_spy_mode"):
        return out

    out["phase13_enabled"] = True
    out["phase13_hard_risk_off"] = False
    out["cash_buffer_pct"] = min(float(out.get("cash_buffer_pct", 0.12)), 0.05)
    out["cash_floor_pct"] = 0.03
    out["max_buy_tickers"] = min(int(out.get("max_buy_tickers", 12)), 12)
    out["max_position_pct"] = min(float(out.get("max_position_pct", 0.10)), 0.10)
    out["max_sector_pct"] = min(float(out.get("max_sector_pct", 0.30)), 0.30)
    out["max_stocks"] = min(int(out.get("max_stocks", 400)), 400)
    out["beat_spy_agent_triage"] = True
    out["beat_spy_factor_top_n"] = int(out.get("beat_spy_factor_top_n", 100))
    out["rebalance_interval_weeks"] = int(out.get("rebalance_interval_weeks", 2))
    out.setdefault("min_buy_confidence", 62)
    out.setdefault("min_sell_confidence", 55)
    return out
