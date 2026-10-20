"""Single-name concentration controls: alerts, gates, auto-trim."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker
    from src.portfolio.models import Portfolio

logger = structlog.get_logger()

# Default concentration threshold (25% of NAV)
DEFAULT_CONCENTRATION_THRESHOLD_PCT = 0.25


def check_single_name_concentration(
    portfolio: "Portfolio",
    current_prices: Dict[str, float],
    equity: Optional[float] = None,
    threshold_pct: float = DEFAULT_CONCENTRATION_THRESHOLD_PCT,
    *,
    fail_closed_on_missing_data: bool = True,
) -> Tuple[bool, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Check if any single name would exceed concentration threshold.
    
    Args:
        portfolio: Current portfolio state
        current_prices: Current prices by ticker
        equity: Total NAV; computed if not provided
        threshold_pct: Concentration threshold (default 0.25 = 25%)
        fail_closed_on_missing_data: If True, block when position data unavailable
    
    Returns:
        (passed, alerts, diagnostics) tuple:
        - passed: False if any name at or above threshold
        - alerts: List of concentration breach dicts
        - diagnostics: Stats about concentration check
    """
    try:
        eq = float(equity) if equity is not None else 0.0
        if not math.isfinite(eq) or eq <= 0:
            if hasattr(portfolio, "get_equity"):
                eq = float(portfolio.get_equity(current_prices) or 0.0)
            else:
                eq = float(getattr(portfolio, "cash", 0) or 0)
            
            # Add position values
            for ticker, pos in (getattr(portfolio, "positions", None) or {}).items():
                try:
                    qty = int(getattr(pos, "long", 0) or 0)
                    if qty <= 0:
                        continue
                    px = float(current_prices.get(ticker) or current_prices.get(str(ticker).upper()) or 0.0)
                    if px > 0:
                        eq += qty * px
                except Exception:
                    continue
    except Exception as e:
        logger.error("Equity computation failed in concentration check", error=str(e))
        if fail_closed_on_missing_data:
            return False, [], {"error": "equity_unavailable", "passed": False}
        return True, [], {"error": "equity_unavailable_soft_pass", "passed": True}
    
    if not math.isfinite(eq) or eq <= 0:
        if fail_closed_on_missing_data:
            return False, [], {"error": "equity_zero_or_invalid", "passed": False}
        return True, [], {"error": "equity_zero_soft_pass", "passed": True}
    
    threshold = eq * float(threshold_pct)
    alerts: List[Dict[str, Any]] = []
    positions_checked = 0
    max_concentration_pct = 0.0
    max_name = None
    
    for ticker, pos in (getattr(portfolio, "positions", None) or {}).items():
        try:
            qty = int(getattr(pos, "long", 0) or 0)
            if qty <= 0:
                continue
            
            positions_checked += 1
            px = float(current_prices.get(ticker) or current_prices.get(str(ticker).upper()) or 0.0)
            
            if px <= 0 and fail_closed_on_missing_data:
                alerts.append({
                    "ticker": str(ticker).upper(),
                    "reason": "price_unavailable_fail_closed",
                    "shares": qty,
                    "weight_pct": None,
                    "threshold_pct": round(threshold_pct * 100, 1),
                })
                continue
            
            if px <= 0:
                # Soft-pass: skip when price missing and fail-closed disabled
                continue
            
            mv = qty * px
            weight_pct = (mv / eq) * 100.0 if eq > 0 else 0.0
            
            if weight_pct > max_concentration_pct:
                max_concentration_pct = weight_pct
                max_name = str(ticker).upper()
            
            # Alert if at or above threshold
            if mv >= threshold - 1e-6:
                alerts.append({
                    "ticker": str(ticker).upper(),
                    "reason": "concentration_at_or_above_threshold",
                    "shares": qty,
                    "market_value": round(mv, 2),
                    "weight_pct": round(weight_pct, 2),
                    "threshold_pct": round(threshold_pct * 100, 1),
                    "equity": round(eq, 2),
                })
        except Exception as e:
            logger.warning("Position concentration check error", ticker=ticker, error=str(e))
            if fail_closed_on_missing_data:
                alerts.append({
                    "ticker": str(ticker).upper(),
                    "reason": f"check_error_{str(e)[:50]}",
                    "shares": qty if 'qty' in locals() else None,
                })
    
    passed = len(alerts) == 0
    diagnostics = {
        "passed": passed,
        "positions_checked": positions_checked,
        "alerts_count": len(alerts),
        "max_concentration_pct": round(max_concentration_pct, 2) if max_name else 0.0,
        "max_name": max_name,
        "threshold_pct": round(threshold_pct * 100, 1),
        "equity": round(eq, 2),
    }
    
    return passed, alerts, diagnostics


def would_new_buy_breach_concentration(
    ticker: str,
    buy_qty: int,
    price: float,
    portfolio: "Portfolio",
    current_prices: Dict[str, float],
    equity: Optional[float] = None,
    threshold_pct: float = DEFAULT_CONCENTRATION_THRESHOLD_PCT,
    *,
    fail_closed_on_missing_data: bool = True,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Check if a new buy would leave the name at or above concentration threshold.
    
    Args:
        ticker: Ticker to buy
        buy_qty: Shares to buy
        price: Current price
        portfolio: Current portfolio state
        current_prices: Current prices by ticker
        equity: Total NAV; computed if not provided
        threshold_pct: Concentration threshold (default 0.25 = 25%)
        fail_closed_on_missing_data: If True, block when data unavailable
    
    Returns:
        (would_breach, details) tuple:
        - would_breach: True if post-buy weight would be >= threshold
        - details: Dict with weight calculations
    """
    ticker_upper = str(ticker).upper()
    
    try:
        eq = float(equity) if equity is not None else 0.0
        if not math.isfinite(eq) or eq <= 0:
            if hasattr(portfolio, "get_equity"):
                eq = float(portfolio.get_equity(current_prices) or 0.0)
            else:
                eq = float(getattr(portfolio, "cash", 0) or 0)
                for t, pos in (getattr(portfolio, "positions", None) or {}).items():
                    try:
                        q = int(getattr(pos, "long", 0) or 0)
                        if q <= 0:
                            continue
                        px = float(current_prices.get(t) or current_prices.get(str(t).upper()) or 0.0)
                        if px > 0:
                            eq += q * px
                    except Exception:
                        continue
    except Exception as e:
        logger.error("Equity computation failed in buy concentration check", ticker=ticker, error=str(e))
        if fail_closed_on_missing_data:
            return True, {"error": "equity_unavailable_fail_closed", "would_breach": True}
        return False, {"error": "equity_unavailable_soft_pass", "would_breach": False}
    
    if not math.isfinite(eq) or eq <= 0:
        if fail_closed_on_missing_data:
            return True, {"error": "equity_zero_fail_closed", "would_breach": True}
        return False, {"error": "equity_zero_soft_pass", "would_breach": False}
    
    px = float(price)
    if not math.isfinite(px) or px <= 0:
        if fail_closed_on_missing_data:
            return True, {"error": "price_unavailable_fail_closed", "ticker": ticker_upper, "would_breach": True}
        return False, {"error": "price_unavailable_soft_pass", "ticker": ticker_upper, "would_breach": False}
    
    # Current holding
    held_qty = 0
    try:
        if hasattr(portfolio, "long_qty"):
            held_qty = int(portfolio.long_qty(ticker_upper) or 0)
        else:
            pos = (getattr(portfolio, "positions", None) or {}).get(ticker) or \
                  (getattr(portfolio, "positions", None) or {}).get(ticker_upper)
            if pos:
                held_qty = int(getattr(pos, "long", 0) or 0)
    except Exception:
        held_qty = 0
    
    post_buy_qty = held_qty + int(buy_qty)
    post_buy_mv = post_buy_qty * px
    post_buy_weight_pct = (post_buy_mv / eq) * 100.0 if eq > 0 else 0.0
    threshold = eq * float(threshold_pct)
    
    would_breach = post_buy_mv >= threshold - 1e-6
    
    return would_breach, {
        "ticker": ticker_upper,
        "held_qty": held_qty,
        "buy_qty": int(buy_qty),
        "post_buy_qty": post_buy_qty,
        "price": round(px, 2),
        "post_buy_mv": round(post_buy_mv, 2),
        "post_buy_weight_pct": round(post_buy_weight_pct, 2),
        "threshold_pct": round(threshold_pct * 100, 1),
        "threshold_usd": round(threshold, 2),
        "equity": round(eq, 2),
        "would_breach": would_breach,
    }


def compute_concentration_trim(
    ticker: str,
    portfolio: "Portfolio",
    current_prices: Dict[str, float],
    equity: Optional[float] = None,
    threshold_pct: float = DEFAULT_CONCENTRATION_THRESHOLD_PCT,
    target_pct: float = 0.20,
    min_trim_shares: int = 10,
    *,
    fail_closed_on_missing_data: bool = True,
    short_calls_by_underlying: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Compute trim quantity for a name above concentration threshold.
    
    Args:
        ticker: Ticker to trim
        portfolio: Current portfolio state
        current_prices: Current prices by ticker
        equity: Total NAV; computed if not provided
        threshold_pct: Concentration threshold triggering trim
        target_pct: Target weight after trim (default 0.20 = 20%)
        min_trim_shares: Minimum shares to trim (skip if trim < min)
        fail_closed_on_missing_data: If True, return None when data unavailable
        short_calls_by_underlying: Dict of short call contracts by ticker (do not sell collateral)
    
    Returns:
        Trim details dict if trim needed, None if not needed or data unavailable
    """
    ticker_upper = str(ticker).upper()
    short_calls_by_underlying = short_calls_by_underlying or {}
    
    try:
        eq = float(equity) if equity is not None else 0.0
        if not math.isfinite(eq) or eq <= 0:
            if hasattr(portfolio, "get_equity"):
                eq = float(portfolio.get_equity(current_prices) or 0.0)
            else:
                eq = float(getattr(portfolio, "cash", 0) or 0)
                for t, pos in (getattr(portfolio, "positions", None) or {}).items():
                    try:
                        q = int(getattr(pos, "long", 0) or 0)
                        if q <= 0:
                            continue
                        px = float(current_prices.get(t) or current_prices.get(str(t).upper()) or 0.0)
                        if px > 0:
                            eq += q * px
                    except Exception:
                        continue
    except Exception as e:
        logger.error("Equity computation failed in trim check", ticker=ticker, error=str(e))
        if fail_closed_on_missing_data:
            return None
        return None
    
    if not math.isfinite(eq) or eq <= 0:
        if fail_closed_on_missing_data:
            return None
        return None
    
    # Current holding
    held_qty = 0
    try:
        if hasattr(portfolio, "long_qty"):
            held_qty = int(portfolio.long_qty(ticker_upper) or 0)
        else:
            pos = (getattr(portfolio, "positions", None) or {}).get(ticker) or \
                  (getattr(portfolio, "positions", None) or {}).get(ticker_upper)
            if pos:
                held_qty = int(getattr(pos, "long", 0) or 0)
    except Exception:
        held_qty = 0
    
    if held_qty <= 0:
        return None
    
    px = float(current_prices.get(ticker) or current_prices.get(ticker_upper) or 0.0)
    if not math.isfinite(px) or px <= 0:
        if fail_closed_on_missing_data:
            return None
        return None
    
    current_mv = held_qty * px
    current_weight_pct = (current_mv / eq) * 100.0 if eq > 0 else 0.0
    threshold = eq * float(threshold_pct)
    
    # Not above threshold
    if current_mv < threshold - 1e-6:
        return None
    
    # Compute trim to target
    target_mv = eq * float(target_pct)
    excess_usd = max(0.0, current_mv - target_mv)
    trim_qty_raw = int(excess_usd // px) if px > 0 else 0
    
    # Do not sell shares covering short calls
    short_call_qty = short_calls_by_underlying.get(ticker, 0) or short_calls_by_underlying.get(ticker_upper, 0) or 0
    covered_shares = int(short_call_qty) * 100
    available_to_sell = max(0, held_qty - covered_shares)
    
    trim_qty = min(trim_qty_raw, available_to_sell)
    
    if trim_qty < int(min_trim_shares):
        return {
            "ticker": ticker_upper,
            "status": "trim_below_min",
            "held_qty": held_qty,
            "trim_qty": 0,
            "trim_qty_before_min": trim_qty,
            "min_trim_shares": int(min_trim_shares),
            "current_weight_pct": round(current_weight_pct, 2),
            "threshold_pct": round(threshold_pct * 100, 1),
            "target_pct": round(target_pct * 100, 1),
            "short_call_contracts": int(short_call_qty),
            "covered_shares": covered_shares,
        }
    
    post_trim_qty = held_qty - trim_qty
    post_trim_mv = post_trim_qty * px
    post_trim_weight_pct = (post_trim_mv / eq) * 100.0 if eq > 0 else 0.0
    
    return {
        "ticker": ticker_upper,
        "status": "trim_needed",
        "held_qty": held_qty,
        "trim_qty": trim_qty,
        "post_trim_qty": post_trim_qty,
        "price": round(px, 2),
        "current_mv": round(current_mv, 2),
        "post_trim_mv": round(post_trim_mv, 2),
        "current_weight_pct": round(current_weight_pct, 2),
        "post_trim_weight_pct": round(post_trim_weight_pct, 2),
        "threshold_pct": round(threshold_pct * 100, 1),
        "target_pct": round(target_pct * 100, 1),
        "equity": round(eq, 2),
        "short_call_contracts": int(short_call_qty),
        "covered_shares": covered_shares,
        "available_to_sell": available_to_sell,
    }
