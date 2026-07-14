"""Phase 13 capital, risk-off, and special-opportunity policy helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Operating defaults (hedge-fund style liquidity)
CASH_BUFFER_BASE = 0.12
CASH_BUFFER_RISK_OFF = 0.20
CASH_FLOOR_ABSOLUTE = 0.05
SPECIAL_OPP_MAX_PCT_EQUITY = 0.05
SPECIAL_OPP_MAX_PCT_EQUITY_RISK_OFF = 0.03
SPECIAL_OPP_MIN_CONFIDENCE = 85
SPECIAL_OPP_MAX_NAMES = 2
MAX_BUY_TICKERS_DEFAULT = 8
MIN_BUY_CONFIDENCE = 65
MIN_SELL_CONFIDENCE = 55
MAX_POSITION_PCT = 0.07
MAX_SECTOR_PCT = 0.25
CONVICTION_GAP = 15
MIN_HOLD_FOR_ROTATION = 55
STOP_LOSS_BOOK_PCT = 0.08
DEAD_MONEY_WEEKS = 4
THRESHOLD_WEIGHT_DRIFT = 0.04
THRESHOLD_CONF_JUMP = 15
AUTO_THROTTLE_WEEKS = 8


def resolve_cash_buffer_pct(
    *,
    regime_mode: str = "neutral",
    base_buffer: Optional[float] = None,
    risk_off_buffer: Optional[float] = None,
) -> float:
    base = float(base_buffer if base_buffer is not None else CASH_BUFFER_BASE)
    risk = float(risk_off_buffer if risk_off_buffer is not None else CASH_BUFFER_RISK_OFF)
    if str(regime_mode).lower() == "harvest":
        return max(base, risk)
    return max(float(base), float(CASH_BUFFER_BASE))


def hard_risk_off_active(regime: Optional[Dict[str, Any]], run_config: Optional[Dict[str, Any]] = None) -> bool:
    run_config = run_config or {}
    if not bool(run_config.get("phase13_hard_risk_off", True)):
        return False
    mode = str((regime or {}).get("mode") or run_config.get("regime", {}).get("mode") or "").lower()
    return mode == "harvest"


def is_special_opportunity(
    conf: int,
    *,
    net_edge: float,
    top_edge: float,
    min_conf: int = SPECIAL_OPP_MIN_CONFIDENCE,
) -> bool:
    if int(conf) < int(min_conf):
        return False
    if top_edge <= 0:
        return int(conf) >= int(min_conf)
    # Must be in the top tier of this run's net-edge distribution
    return float(net_edge) >= float(top_edge) * 0.95 and int(conf) >= int(min_conf)


def special_opp_budget_pct(risk_off: bool) -> float:
    return SPECIAL_OPP_MAX_PCT_EQUITY_RISK_OFF if risk_off else SPECIAL_OPP_MAX_PCT_EQUITY


def filter_buys_for_risk_off(
    buy_candidates: List[Tuple[str, int]],
    *,
    net_edges: Dict[str, float],
    risk_off: bool,
    allow_special: bool = True,
) -> Tuple[List[Tuple[str, int]], List[str]]:
    """
    In hard risk-off, drop ordinary buys; keep only special opportunities.
    Returns (filtered_candidates, special_tickers).
    """
    if not risk_off or not allow_special:
        if risk_off and not allow_special:
            return [], []
        return list(buy_candidates), []

    if not buy_candidates:
        return [], []
    edges = [float(net_edges.get(t, 0.0)) for t, _ in buy_candidates]
    top_edge = max(edges) if edges else 0.0
    specials: List[Tuple[str, int]] = []
    tags: List[str] = []
    for t, conf in buy_candidates:
        if is_special_opportunity(conf, net_edge=float(net_edges.get(t, 0.0)), top_edge=top_edge):
            specials.append((t, conf))
            tags.append(t)
        if len(specials) >= SPECIAL_OPP_MAX_NAMES:
            break
    return specials, tags


def position_stop_triggered(
    *,
    qty: int,
    price: float,
    cost_basis: float,
    stop_pct: float = STOP_LOSS_BOOK_PCT,
) -> bool:
    if qty <= 0 or price <= 0 or cost_basis <= 0:
        return False
    pnl_pct = (price - cost_basis) / cost_basis
    return pnl_pct <= -abs(float(stop_pct))


def apply_phase13_defaults(run_config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply Phase 13 profitability knobs (setdefault + enforce floors where noted)."""
    out = dict(run_config)
    out.setdefault("phase13_enabled", True)
    if not out.get("phase13_enabled", True):
        return out

    out["min_buy_confidence"] = max(int(out.get("min_buy_confidence", MIN_BUY_CONFIDENCE)), MIN_BUY_CONFIDENCE)
    # Sell bar should not sit above buy bar
    out["min_sell_confidence"] = min(int(out.get("min_sell_confidence", MIN_SELL_CONFIDENCE)), MIN_SELL_CONFIDENCE)
    out["min_sell_confidence"] = max(40, int(out["min_sell_confidence"]))

    out["cash_buffer_pct"] = max(float(out.get("cash_buffer_pct", CASH_BUFFER_BASE)), CASH_BUFFER_BASE)
    out["cash_floor_pct"] = float(out.get("cash_floor_pct", CASH_FLOOR_ABSOLUTE))
    out["max_buy_tickers"] = min(int(out.get("max_buy_tickers", MAX_BUY_TICKERS_DEFAULT)), MAX_BUY_TICKERS_DEFAULT)
    out["max_position_pct"] = min(float(out.get("max_position_pct", MAX_POSITION_PCT)), MAX_POSITION_PCT)
    out["max_sector_pct"] = min(float(out.get("max_sector_pct", MAX_SECTOR_PCT)), MAX_SECTOR_PCT)

    out.setdefault("enable_conviction_rebalance", True)
    out["conviction_score_gap"] = min(int(out.get("conviction_score_gap", CONVICTION_GAP)), CONVICTION_GAP)
    out["min_hold_confidence_for_rotation"] = max(
        int(out.get("min_hold_confidence_for_rotation", MIN_HOLD_FOR_ROTATION)),
        MIN_HOLD_FOR_ROTATION,
    )
    out.setdefault("max_cash_rotation_sells", 1)
    out["max_cash_rotation_sells"] = min(int(out["max_cash_rotation_sells"]), 1)
    out.setdefault("cash_rotation_min_edge", 15)
    out["cash_rotation_min_edge"] = max(int(out["cash_rotation_min_edge"]), 15)

    out.setdefault("phase13_hard_risk_off", True)
    out.setdefault("phase13_special_opportunity", True)
    out.setdefault("phase13_book_stops", True)
    out.setdefault("phase13_threshold_rebalance", True)
    out.setdefault("phase13_force_cc_lots", True)
    out.setdefault("phase13_net_edge", True)
    out.setdefault("phase13_cancel_stale_orders", True)
    out.setdefault("stale_order_max_age_hours", 48)
    out.setdefault("book_stop_loss_pct", STOP_LOSS_BOOK_PCT)
    out.setdefault("dead_money_weeks", DEAD_MONEY_WEEKS)
    out.setdefault("rebalance_weight_drift", THRESHOLD_WEIGHT_DRIFT)
    out.setdefault("rebalance_conf_jump", THRESHOLD_CONF_JUMP)
    out.setdefault("auto_throttle_weeks", AUTO_THROTTLE_WEEKS)
    out.setdefault("slo_cash_conc_hard_after_weeks", 2)
    return out
