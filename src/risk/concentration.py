"""Single-name concentration controls: gates, auto-trim, and health check integration."""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker
    from src.portfolio.manager import PortfolioDecision

logger = structlog.get_logger()


def is_regular_market_hours() -> bool:
    """Check if current time is within regular US market hours (09:30-16:00 ET, Mon-Fri)."""
    try:
        from src.trading.us_equity_calendar import is_market_open
        return is_market_open()
    except Exception as e:
        logger.warning("Market hours check failed", error=str(e))
        return False


def is_scheduled_run() -> bool:
    """Check if running in a scheduled workflow (not manual workflow_dispatch)."""
    # GitHub Actions sets GITHUB_EVENT_NAME
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    return event in ("schedule", "repository_dispatch")


def calculate_position_concentration(
    positions: Dict[str, Dict[str, Any]],
    current_prices: Dict[str, float],
    equity: float,
) -> Dict[str, float]:
    """
    Calculate percentage of equity for each position.
    
    Returns dict mapping ticker -> percentage (0-100).
    """
    if equity <= 0:
        return {}
    
    concentrations: Dict[str, float] = {}
    for ticker, pos in positions.items():
        qty = int(pos.get("qty", 0) or 0)
        if qty <= 0:
            continue
        side = str(pos.get("side", "long") or "long").lower()
        if side != "long":
            continue
        
        price = current_prices.get(ticker)
        if price is None or not (0 < price < float("inf")):
            # Fallback to cost basis if no market price
            price = float(pos.get("avg_entry_price", 0) or 0)
        if not (0 < price < float("inf")):
            continue
        
        market_value = float(qty) * float(price)
        pct = 100.0 * market_value / equity
        concentrations[ticker] = pct
    
    return concentrations


def get_breaching_names(
    concentrations: Dict[str, float],
    threshold_pct: float = 25.0,
) -> List[Tuple[str, float]]:
    """Return list of (ticker, pct) for names over threshold, sorted by pct descending."""
    breaches = [(t, p) for t, p in concentrations.items() if p > threshold_pct]
    return sorted(breaches, key=lambda x: -x[1])


def check_new_buy_gate(
    ticker: str,
    buy_qty: int,
    current_price: float,
    positions: Dict[str, Dict[str, Any]],
    current_prices: Dict[str, float],
    equity: float,
    *,
    threshold_pct: float = 25.0,
) -> Tuple[bool, Optional[str]]:
    """
    Gate new buys at 25%: block any buy that would take a name over threshold.
    
    Returns (allowed, reason).
    """
    if equity <= 0:
        return False, "equity_unavailable"
    
    if buy_qty <= 0 or not (0 < current_price < float("inf")):
        return True, None
    
    # Current position
    pos = positions.get(ticker, {})
    current_qty = int(pos.get("qty", 0) or 0) if pos.get("side", "long") == "long" else 0
    current_mv = current_qty * current_prices.get(ticker, current_price)
    
    # After buy
    after_qty = current_qty + buy_qty
    after_mv = after_qty * current_price
    after_pct = 100.0 * after_mv / equity
    
    if after_pct > threshold_pct:
        return False, f"would_breach_{threshold_pct:.0f}%_concentration"
    
    return True, None


def check_put_assignment_gate(
    ticker: str,
    strike: float,
    put_qty: int,
    current_price: float,
    positions: Dict[str, Dict[str, Any]],
    current_prices: Dict[str, float],
    equity: float,
    *,
    threshold_pct: float = 25.0,
) -> Tuple[bool, Optional[str]]:
    """
    Gate put selection: reject puts whose assignment would breach concentration.
    
    Assignment value: current_market_value + (100 * strike * put_qty).
    
    Returns (allowed, reason).
    """
    if equity <= 0:
        return False, "equity_unavailable"
    
    if put_qty <= 0 or strike <= 0:
        return True, None
    
    # Current position
    pos = positions.get(ticker, {})
    current_qty = int(pos.get("qty", 0) or 0) if pos.get("side", "long") == "long" else 0
    current_mv = current_qty * current_prices.get(ticker, current_price)
    
    # After assignment
    assignment_shares = 100 * put_qty
    assignment_value = assignment_shares * strike
    after_mv = current_mv + assignment_value
    after_pct = 100.0 * after_mv / equity
    
    if after_pct > threshold_pct:
        return False, f"assignment_would_breach_{threshold_pct:.0f}%_concentration"
    
    return True, None


def calculate_unencumbered_shares(
    ticker: str,
    long_shares: int,
    open_orders: List[Dict[str, Any]],
    option_positions: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Unencumbered shares = long - (100*short_calls) - (shares_in_working_sell_orders).
    
    Returns max shares available for trim sale.
    """
    if long_shares <= 0:
        return 0
    
    # Short calls (covered)
    short_calls = 0
    if option_positions:
        from src.options.wheel_lifecycle import parse_occ_symbol
        for pos in option_positions:
            if str(pos.get("side") or "").lower() != "short":
                continue
            parsed = parse_occ_symbol(str(pos.get("symbol") or ""))
            if not parsed or parsed.get("option_type") != "call":
                continue
            if str(parsed.get("underlying") or "").upper() == str(ticker).upper():
                short_calls += int(pos.get("qty", 0) or 0)
    
    covered = min(long_shares, short_calls * 100)
    
    # Working sell orders
    working_sell = 0
    for o in open_orders:
        if str(o.get("symbol") or "").upper() != str(ticker).upper():
            continue
        if str(o.get("side") or "").lower() != "sell":
            continue
        status = str(o.get("status") or "").lower()
        if status not in ("new", "pending_new", "accepted", "partially_filled"):
            continue
        working_sell += int(o.get("qty", 0) or 0) - int(o.get("filled_qty", 0) or 0)
    
    return max(0, long_shares - covered - working_sell)


def calculate_trim_size(
    ticker: str,
    current_pct: float,
    bid_price: float,
    equity: float,
    market_value: float,
    unencumbered_shares: int,
    *,
    target_pct: float = 22.0,
) -> Tuple[int, Optional[str]]:
    """
    Calculate shares to sell to trim position from current_pct down to target_pct.
    
    Formula: floor((market_value - 0.22*equity) / bid_price).
    
    Returns (shares_to_sell, skip_reason).
    """
    if equity <= 0:
        return 0, "equity_unavailable"
    
    if not (0 < bid_price < float("inf")):
        return 0, "bid_price_unavailable"
    
    if unencumbered_shares <= 0:
        return 0, "no_unencumbered_shares"
    
    target_mv = equity * (target_pct / 100.0)
    excess_mv = market_value - target_mv
    
    if excess_mv <= 0:
        return 0, "already_below_target"
    
    # Sell floor to avoid fractional shares
    shares = int(math.floor(excess_mv / bid_price))
    
    if shares < 1:
        return 0, "under_1_share"
    
    # Cap at unencumbered
    shares = min(shares, unencumbered_shares)
    
    return shares, None


def get_trim_order_id_for_ticker(
    ticker: str,
    open_orders: List[Dict[str, Any]],
) -> Optional[str]:
    """Find existing trim order for ticker (by reasoning marker)."""
    for o in open_orders:
        if str(o.get("symbol") or "").upper() != str(ticker).upper():
            continue
        if str(o.get("side") or "").lower() != "sell":
            continue
        # Orders don't carry reasoning; we rely on client_order_id or must track separately.
        # For now, we'll cancel all open sell orders before placing new trim.
        status = str(o.get("status") or "").lower()
        if status in ("new", "pending_new", "accepted", "partially_filled"):
            return str(o.get("id") or "")
    return None


def generate_trim_orders(
    broker: "AlpacaBroker",
    positions: Dict[str, Dict[str, Any]],
    current_prices: Dict[str, float],
    equity: float,
    open_orders: List[Dict[str, Any]],
    option_positions: Optional[List[Dict[str, Any]]] = None,
    *,
    breach_threshold_pct: float = 25.0,
    target_pct: float = 22.0,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """
    Generate concentration trim orders for breaching names.
    
    Returns list of order result dicts with keys: ticker, action, reason, order_id (if submitted).
    """
    concentrations = calculate_position_concentration(positions, current_prices, equity)
    breaches = get_breaching_names(concentrations, breach_threshold_pct)
    
    if not breaches:
        logger.info("No concentration breaches to trim")
        return []
    
    results: List[Dict[str, Any]] = []
    
    for ticker, pct in breaches:
        pos = positions.get(ticker, {})
        qty = int(pos.get("qty", 0) or 0)
        if qty <= 0:
            continue
        
        # Get bid price for limit order
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockLatestQuoteRequest
            
            key = broker._api_key
            sec = broker._secret_key
            if not key or not sec:
                results.append({
                    "ticker": ticker,
                    "action": "skip",
                    "reason": "broker_credentials_unavailable",
                })
                continue
            
            client = StockHistoricalDataClient(key, sec)
            from src.broker.alpaca import alpaca_call_with_retry
            quotes = alpaca_call_with_retry(
                lambda: client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=[ticker])),
                op="get_stock_latest_quote_for_trim",
                attempts=2,
                base_delay_sec=1.0,
            )
            qmap = quotes if isinstance(quotes, dict) else getattr(quotes, "data", None) or {}
            q = qmap.get(ticker)
            bid_price = None
            if q:
                try:
                    bid_price = float(getattr(q, "bid_price", None) or 0)
                except (TypeError, ValueError):
                    pass
            
            if not bid_price or not (0 < bid_price < float("inf")):
                results.append({
                    "ticker": ticker,
                    "action": "skip",
                    "reason": "bid_price_unavailable",
                    "current_pct": round(pct, 2),
                })
                continue
        except Exception as e:
            logger.error("Failed to fetch bid for trim", ticker=ticker, error=str(e))
            results.append({
                "ticker": ticker,
                "action": "skip",
                "reason": f"quote_error: {str(e)[:100]}",
                "current_pct": round(pct, 2),
            })
            continue
        
        market_value = qty * current_prices.get(ticker, 0)
        unencumbered = calculate_unencumbered_shares(ticker, qty, open_orders, option_positions)
        
        shares, skip_reason = calculate_trim_size(
            ticker, pct, bid_price, equity, market_value, unencumbered,
            target_pct=target_pct,
        )
        
        if skip_reason:
            results.append({
                "ticker": ticker,
                "action": "skip",
                "reason": skip_reason,
                "current_pct": round(pct, 2),
                "unencumbered_shares": unencumbered,
            })
            continue
        
        # Cancel any existing sell orders for this ticker
        for o in open_orders:
            if str(o.get("symbol") or "").upper() != str(ticker).upper():
                continue
            if str(o.get("side") or "").lower() != "sell":
                continue
            status = str(o.get("status") or "").lower()
            if status in ("new", "pending_new", "accepted", "partially_filled"):
                oid = str(o.get("id") or "")
                if oid:
                    logger.info("Cancelling stale sell order before trim", ticker=ticker, order_id=oid)
                    if not dry_run:
                        broker.cancel_order(oid)
        
        if dry_run:
            results.append({
                "ticker": ticker,
                "action": "dry_run",
                "shares": shares,
                "limit_price": round(bid_price, 2),
                "current_pct": round(pct, 2),
                "target_pct": target_pct,
            })
            continue
        
        # Submit DAY limit sell at bid
        from alpaca.trading.requests import LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
        
        try:
            order_data = LimitOrderRequest(
                symbol=ticker,
                qty=shares,
                side=OrderSide.SELL,
                type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                limit_price=round(bid_price, 2),
            )
            order = broker.client.submit_order(order_data=order_data)
            logger.info(
                "Concentration trim order submitted",
                ticker=ticker,
                shares=shares,
                limit_price=round(bid_price, 2),
                current_pct=round(pct, 2),
                target_pct=target_pct,
                order_id=str(order.id),
            )
            results.append({
                "ticker": ticker,
                "action": "trim_submitted",
                "shares": shares,
                "limit_price": round(bid_price, 2),
                "current_pct": round(pct, 2),
                "target_pct": target_pct,
                "order_id": str(order.id),
            })
        except Exception as e:
            logger.error("Trim order submit failed", ticker=ticker, error=str(e))
            results.append({
                "ticker": ticker,
                "action": "submit_failed",
                "error": str(e)[:200],
                "current_pct": round(pct, 2),
            })
    
    return results


def run_concentration_trim_workflow(
    broker: "AlpacaBroker",
    *,
    breach_threshold_pct: float = 25.0,
    target_pct: float = 22.0,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Main entry point for concentration trim workflow.
    
    Guards:
    - Regular market hours only
    - Scheduled runs only (not manual)
    - ENABLE_CONCENTRATION_TRIM=1
    
    Returns summary dict with trim results.
    """
    # Guard: ENABLE_CONCENTRATION_TRIM must be "1"
    enable_trim = os.environ.get("ENABLE_CONCENTRATION_TRIM", "0").strip()
    if enable_trim != "1":
        return {
            "trimmed": False,
            "reason": "ENABLE_CONCENTRATION_TRIM_not_enabled",
            "enable_trim": enable_trim,
        }
    
    # Guard: scheduled runs only
    if not is_scheduled_run():
        return {
            "trimmed": False,
            "reason": "not_scheduled_run",
        }
    
    # Guard: regular market hours only
    if not is_regular_market_hours():
        return {
            "trimmed": False,
            "reason": "not_regular_market_hours",
        }
    
    # Fetch account state
    try:
        account = broker.get_account()
        equity = float(account.get("equity") or account.get("portfolio_value") or 0)
    except Exception as e:
        logger.error("Failed to fetch account for concentration trim", error=str(e))
        # Fail closed: no trim if account unavailable
        return {
            "trimmed": False,
            "reason": "account_unavailable",
            "error": str(e)[:200],
        }
    
    if equity <= 0:
        return {
            "trimmed": False,
            "reason": "equity_zero_or_negative",
            "equity": equity,
        }
    
    try:
        positions = broker.get_positions()
    except Exception as e:
        logger.error("Failed to fetch positions for concentration trim", error=str(e))
        return {
            "trimmed": False,
            "reason": "positions_unavailable",
            "error": str(e)[:200],
        }
    
    try:
        open_orders = broker.get_open_orders(limit=500)
    except Exception as e:
        logger.error("Failed to fetch open orders for concentration trim", error=str(e))
        return {
            "trimmed": False,
            "reason": "open_orders_unavailable",
            "error": str(e)[:200],
        }
    
    # Current prices
    current_prices = {}
    for ticker, pos in positions.items():
        mv = float(pos.get("market_value", 0) or 0)
        qty = int(pos.get("qty", 0) or 0)
        if qty > 0:
            current_prices[ticker] = mv / qty
    
    # Option positions (for covered-call encumbrance)
    option_positions = None
    try:
        option_positions = broker.get_option_positions()
    except Exception:
        pass
    
    trim_results = generate_trim_orders(
        broker,
        positions,
        current_prices,
        equity,
        open_orders,
        option_positions,
        breach_threshold_pct=breach_threshold_pct,
        target_pct=target_pct,
        dry_run=dry_run,
    )
    
    submitted = [r for r in trim_results if r.get("action") == "trim_submitted"]
    
    return {
        "trimmed": len(submitted) > 0,
        "equity": round(equity, 2),
        "breach_threshold_pct": breach_threshold_pct,
        "target_pct": target_pct,
        "trim_orders_submitted": len(submitted),
        "trim_results": trim_results,
    }
