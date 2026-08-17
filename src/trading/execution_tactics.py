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
    """Choose deterministic order tactic from market-state inputs.

    Missing ADV used to classify every name as 'low' liquidity and send
    passive limits that never fill. Unknown volume now defaults to a
    marketable (or market) order so weekly paper trades complete in RTH.
    """
    cfg = run_config or {}
    px = float(current_price or 0.0)
    adv_raw = avg_daily_volume
    adv = float(adv_raw) if adv_raw is not None else None
    spread = float(spread_bps) if spread_bps is not None else None

    if px <= 0:
        return {
            "tactic": "skip",
            "use_limit_order": False,
            "limit_slippage_pct": 0.002,
            "reason": "missing_price",
        }

    prefer_market = bool(cfg.get("prefer_market_orders", False))
    marketable_slip = float(cfg.get("marketable_slippage_pct", 0.005))

    if adv is None:
        liquidity_bucket = "unknown"
    elif adv >= 2_000_000:
        liquidity_bucket = "high"
    elif adv >= 250_000:
        liquidity_bucket = "mid"
    else:
        liquidity_bucket = "low"

    wide_spread = spread is not None and spread >= 15.0

    # Paper Beat SPY: fill in RTH. Market unless explicitly forcing limits.
    if prefer_market or liquidity_bucket in ("unknown", "low"):
        tactic = "market_fill"
        use_limit = False
        slip = 0.0
        reason = "market_fill_unknown_or_low_adv" if not prefer_market else "prefer_market_orders"
    elif action in ("sell", "short") and liquidity_bucket == "low":
        tactic = "market_aggressive"
        use_limit = False
        slip = 0.0
        reason = "sell_first_low_liquidity"
    elif wide_spread:
        tactic = "limit_marketable"
        use_limit = True
        slip = marketable_slip
        reason = "wide_spread_marketable"
    elif liquidity_bucket == "high" and action in ("buy", "cover"):
        tactic = "limit_marketable"
        use_limit = True
        slip = max(float(cfg.get("limit_slippage_pct", 0.003)), 0.003)
        reason = "high_liquidity_marketable_buy"
    else:
        tactic = "market_standard"
        use_limit = False
        slip = float(cfg.get("limit_slippage_pct", 0.002))
        reason = "default_market"

    return {
        "tactic": tactic,
        "use_limit_order": use_limit,
        "limit_slippage_pct": slip,
        "liquidity_bucket": liquidity_bucket,
        "spread_bps": round(spread, 2) if spread is not None else None,
        "reason": reason,
        "ticker": ticker,
    }
