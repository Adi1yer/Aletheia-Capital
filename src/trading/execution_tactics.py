"""Adaptive execution tactic selection by liquidity/spread regime."""

from __future__ import annotations

from typing import Any, Dict, Optional


def select_execution_tactic(
    *,
    ticker: str,
    action: str,
    current_price: Optional[float],
    avg_daily_volume: Optional[float] = None,
    spread_bps: Optional[float] = None,
    run_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Choose deterministic order tactic from market-state inputs."""
    cfg = run_config or {}
    px = float(current_price or 0.0)
    adv = float(avg_daily_volume or 0.0)
    spread = float(spread_bps if spread_bps is not None else 8.0)

    if px <= 0:
        return {"tactic": "skip", "use_limit_order": False, "limit_slippage_pct": 0.002, "reason": "missing_price"}

    liquidity_bucket = "high" if adv >= 2_000_000 else ("mid" if adv >= 250_000 else "low")
    wide_spread = spread >= 15.0

    if action in ("sell", "short") and liquidity_bucket == "low":
        tactic = "market_aggressive"
        use_limit = False
        slip = 0.0
        reason = "sell_first_low_liquidity"
    elif wide_spread or liquidity_bucket == "low":
        tactic = "limit_passive"
        use_limit = True
        slip = min(0.01, max(0.001, spread / 10000.0))
        reason = "wide_spread_or_low_liquidity"
    elif liquidity_bucket == "high" and action in ("buy", "cover"):
        tactic = "limit_improve"
        use_limit = bool(cfg.get("use_limit_orders", False)) or True
        slip = float(cfg.get("limit_slippage_pct", 0.0015))
        reason = "high_liquidity_buy"
    else:
        tactic = "market_standard"
        use_limit = bool(cfg.get("use_limit_orders", False))
        slip = float(cfg.get("limit_slippage_pct", 0.002))
        reason = "default"

    return {
        "tactic": tactic,
        "use_limit_order": use_limit,
        "limit_slippage_pct": slip,
        "liquidity_bucket": liquidity_bucket,
        "spread_bps": round(spread, 2),
        "reason": reason,
        "ticker": ticker,
    }
