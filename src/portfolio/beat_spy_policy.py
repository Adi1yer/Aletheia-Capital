"""Beat SPY run profile defaults (~$10k paper).

These knobs *overwrite* Phase 13 / regime / learned-policy clamps.
`min()` against the incoming config cannot restore 12 names / 10% size / 4% cash.
"""

from __future__ import annotations

from typing import Any, Dict

# Mandate: concentrated 10–12 liquid names, fully invested, agents veto-only.
CASH_BUFFER_PCT = 0.04
CASH_FLOOR_PCT = 0.03
MAX_BUY_TICKERS = 12
MAX_POSITION_PCT = 0.10
MAX_SECTOR_PCT = 0.30
MAX_STOCKS = 500
UNIVERSE_SOURCE = "sp500"
FACTOR_TOP_N = 40
MAX_ROTATION_SELLS = 20
MIN_BUY_NOTIONAL_USD = 250.0
CASH_ROTATION_MIN_EDGE = 12
MIN_BUY_CONFIDENCE = 62  # unused for entry; kept for dead-money / diagnostics
MIN_SELL_CONFIDENCE = 55
MIN_MCAP_USD = 10_000_000_000.0
MIN_ADV_USD = 20_000_000.0
MIN_PRICE_USD = 10.0


def apply_beat_spy_defaults(run_config: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(run_config)
    if not out.get("beat_spy_mode"):
        return out

    out["phase13_enabled"] = True
    out["phase13_hard_risk_off"] = False
    out["cash_buffer_pct"] = CASH_BUFFER_PCT
    out["cash_floor_pct"] = CASH_FLOOR_PCT
    out["max_buy_tickers"] = MAX_BUY_TICKERS
    out["max_position_pct"] = MAX_POSITION_PCT
    out["max_sector_pct"] = MAX_SECTOR_PCT
    out["max_stocks"] = min(int(out.get("max_stocks", MAX_STOCKS)), MAX_STOCKS)
    out["universe_source"] = UNIVERSE_SOURCE
    out["beat_spy_agent_triage"] = True
    out["beat_spy_factor_top_n"] = int(out.get("beat_spy_factor_top_n", FACTOR_TOP_N) or FACTOR_TOP_N)
    out["beat_spy_concentrated"] = True
    out.setdefault("max_llm_calls", 3200)
    out["rebalance_interval_weeks"] = int(out.get("rebalance_interval_weeks", 2) or 2)
    out["min_buy_confidence"] = MIN_BUY_CONFIDENCE
    out["min_sell_confidence"] = MIN_SELL_CONFIDENCE
    out["prefer_market_orders"] = True
    out["phase13_cancel_stale_orders"] = True
    out["stale_order_max_age_hours"] = 0
    out["enable_covered_calls"] = False
    out["enable_cash_secured_puts"] = False
    out["phase13_force_cc_lots"] = False
    out["max_cash_rotation_sells"] = MAX_ROTATION_SELLS
    out["cash_rotation_min_edge"] = CASH_ROTATION_MIN_EDGE
    out["cash_rotation_min_buy_notional_usd"] = MIN_BUY_NOTIONAL_USD
    out["enable_cash_rotation"] = True
    out["enable_conviction_rebalance"] = False
    out["phase13_book_stops"] = True
    out["phase13_threshold_rebalance"] = False
    out["beat_spy_min_mcap_usd"] = float(out.get("beat_spy_min_mcap_usd") or MIN_MCAP_USD)
    out["beat_spy_min_adv_usd"] = float(out.get("beat_spy_min_adv_usd") or MIN_ADV_USD)
    out["beat_spy_min_price_usd"] = float(out.get("beat_spy_min_price_usd") or MIN_PRICE_USD)
    return out
