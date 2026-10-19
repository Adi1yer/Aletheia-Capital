#!/usr/bin/env python3
"""Read-only Alpaca paper fills and positions report.

CRITICAL: This script is READ-ONLY. It makes ZERO order/cancel/replace calls.
Used by finance to confirm paper trades and split cash moves between order legs.

Usage:
    python scripts/read_only_fills_report.py --date 2026-10-14
    python scripts/read_only_fills_report.py  # defaults to today
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def format_currency(value: float) -> str:
    """Format as USD with sign."""
    return f"${value:,.2f}" if value >= 0 else f"-${abs(value):,.2f}"


def get_account_info(broker) -> Dict[str, Any]:
    """Get account cash and equity (read-only).
    
    Raises:
        Exception: If account fetch fails.
    """
    account = broker.get_account()
    return {
        "cash": float(account.get("cash") or 0.0),
        "equity": float(account.get("equity") or 0.0),
        "buying_power": float(account.get("buying_power") or 0.0),
    }


def get_positions(broker) -> List[Dict[str, Any]]:
    """Get current positions (read-only).
    
    Raises:
        Exception: If positions fetch fails.
    """
    positions = []
    warnings = []
    
    equity_positions = broker.get_positions() or {}
    for ticker, pos_dict in equity_positions.items():
        qty = float(pos_dict.get("qty") or 0)
        if qty != 0:
            # Extract current price, keep None if missing
            current_price_raw = pos_dict.get("current_price") or pos_dict.get("mark_price")
            try:
                current_price = float(current_price_raw) if current_price_raw is not None else None
                if current_price is not None and current_price <= 0:
                    current_price = None
            except (TypeError, ValueError):
                current_price = None
            
            if current_price is None:
                warnings.append(f"Equity {ticker}: missing or invalid current_price/mark_price")
            
            positions.append({
                "type": "equity",
                "symbol": ticker,
                "qty": qty,
                "market_value": float(pos_dict.get("market_value") or 0.0),
                "avg_entry_price": float(pos_dict.get("avg_entry_price") or 0.0),
                "current_price": current_price,
            })

    option_positions = broker.get_option_positions() or []
    for opt in option_positions:
        qty = float(opt.get("qty") or 0)
        if qty != 0:
            # Extract current price, keep None if missing
            current_price_raw = opt.get("current_price") or opt.get("mark_price")
            try:
                current_price = float(current_price_raw) if current_price_raw is not None else None
                if current_price is not None and current_price <= 0:
                    current_price = None
            except (TypeError, ValueError):
                current_price = None
            
            if current_price is None:
                warnings.append(f"Option {opt.get('symbol')}: missing or invalid current_price/mark_price (excluded from NAV)")
            
            positions.append({
                "type": "option",
                "symbol": opt.get("symbol"),
                "side": opt.get("side"),
                "qty": qty,
                "market_value": float(opt.get("market_value") or 0.0),
                "avg_entry_price": float(
                    opt.get("avg_entry_price") or opt.get("avg_entry") or 0.0
                ),
                "current_price": current_price,
            })

    return positions, warnings


def get_fills_for_date(broker, target_date: date) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Get fills for a specific date (read-only).
    
    Returns fills with: symbol, side, qty, filled_avg_price, filled_at, order_id
    Also includes warnings list for orders with parsing issues.
    
    Raises:
        Exception: If orders fetch fails.
    """
    fills = []
    warnings = []
    
    # Fetch orders for the target date with strict=True so failures raise
    # Use after/until to filter by date at the API level
    recent_orders = broker.get_recent_orders(
        limit=500, strict=True, after=target_date, until=target_date
    ) or []
    
    # Warn if results may be truncated
    if len(recent_orders) >= 500:
        warnings.append({
            "symbol": None,
            "side": None,
            "order_id": None,
            "filled_at": None,
            "reason": f"Fetched 500+ orders for {target_date}; results may be truncated. Consider pagination if fills are missing.",
        })
    
    for order in recent_orders:
        # Check if order was filled
        status = order.get("status", "").lower()
        if status not in ("filled", "partially_filled"):
            continue
        
        # Parse filled_at timestamp
        filled_at_str = order.get("filled_at")
        if not filled_at_str:
            continue
        
        try:
            filled_dt = datetime.fromisoformat(
                filled_at_str.replace("Z", "+00:00")
            )
            filled_date = filled_dt.astimezone(ZoneInfo("America/New_York")).date()
        except (ValueError, AttributeError) as e:
            # Unable to parse filled_at - collect as WARNING
            warnings.append({
                "symbol": order.get("symbol"),
                "side": order.get("side"),
                "order_id": order.get("id"),
                "filled_at": filled_at_str,
                "reason": f"Cannot parse filled_at: {e}",
            })
            continue
        
        # Filter by target date
        if filled_date != target_date:
            continue
        
        filled_qty = float(order.get("filled_qty") or 0)
        if filled_qty <= 0:
            continue
        
        fills.append({
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "qty": filled_qty,
            "filled_avg_price": order.get("filled_avg_price"),  # Keep None if missing
            "filled_at": filled_at_str,
            "order_id": order.get("id"),
            "order_type": order.get("type"),
        })
    
    return fills, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Alpaca paper fills and positions report"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date for fills report (YYYY-MM-DD), defaults to today ET",
    )
    args = parser.parse_args()

    # Parse target date
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"ERROR: Invalid date format: {args.date}", file=sys.stderr)
            return 1
    else:
        target_date = datetime.now(ZoneInfo("America/New_York")).date()

    # Initialize broker (read-only operations only)
    from src.broker.alpaca import AlpacaBroker
    
    broker = AlpacaBroker()

    print("=" * 80)
    print("ALPACA PAPER FILLS & POSITIONS REPORT")
    print("=" * 80)
    print(f"Report Date: {target_date.isoformat()}")
    print(f"Generated: {datetime.now(ZoneInfo('America/New_York')).isoformat()}")
    print()

    # Account info
    try:
        account = get_account_info(broker)
    except Exception as e:
        print(f"ERROR: Failed to fetch account info: {e}", file=sys.stderr)
        return 1
    
    print("ACCOUNT INFO")
    print("-" * 80)
    print(f"  Cash:          {format_currency(account['cash'])}")
    print(f"  Equity:        {format_currency(account['equity'])}")
    print(f"  Buying Power:  {format_currency(account['buying_power'])}")
    print()

    # Current positions
    try:
        positions, pos_warnings = get_positions(broker)
    except Exception as e:
        print(f"ERROR: Failed to fetch positions: {e}", file=sys.stderr)
        return 1
    
    print("CURRENT POSITIONS")
    print("-" * 80)
    
    if pos_warnings:
        print("  WARNINGS:")
        for warn in pos_warnings:
            print(f"    {warn}")
        print()
    
    if not positions:
        print("  (No open positions)")
    else:
        for pos in sorted(positions, key=lambda p: (p["type"], p["symbol"])):
            side = f" ({pos['side']})" if pos.get("side") else ""
            current_price = pos.get("current_price")
            mark_str = "n/a" if current_price is None else format_currency(current_price)
            print(
                f"  {pos['type'].upper():8s} {pos['symbol']:25s}{side:10s} "
                f"qty={pos['qty']:8.2f}  mv={format_currency(pos['market_value']):>12s}  "
                f"entry={format_currency(pos['avg_entry_price']):>10s}  "
                f"mark={mark_str:>10s}"
            )
        
        # Add explicit position status lines for specific tickers requested in #46
        import re
        nu_equity = next((p for p in positions if p.get("symbol") == "NU" and p.get("type") == "equity"), None)
        # Match any NU option: OCC format NU + 6 digits + C/P + 8 digits
        nu_option = next((p for p in positions if p.get("type") == "option" and re.match(r'^NU\d{6}[CP]', p.get("symbol", ""))), None)
        cpng_equity = next((p for p in positions if p.get("symbol") == "CPNG" and p.get("type") == "equity"), None)
        
        print()
        if nu_equity and nu_option:
            print(f"  NU: OPEN (equity qty={nu_equity['qty']:.0f}, short put qty={nu_option['qty']:.0f})")
        elif nu_equity:
            print(f"  NU: OPEN (equity qty={nu_equity['qty']:.0f}, no short put)")
        elif nu_option:
            print(f"  NU: OPEN (no equity, short put qty={nu_option['qty']:.0f})")
        else:
            print("  NU: FLAT")
        
        if cpng_equity:
            print(f"  CPNG cost basis: {format_currency(cpng_equity['avg_entry_price'])} (qty={cpng_equity['qty']:.0f})")
        else:
            print("  CPNG cost basis: (No position)")
    print()

    # Fills for date
    try:
        fills, warnings = get_fills_for_date(broker, target_date)
    except Exception as e:
        print(f"ERROR: Failed to fetch fills: {e}", file=sys.stderr)
        return 1
    
    print(f"FILLS ON {target_date.isoformat()}")
    print("-" * 80)
    
    # Show warnings first if any
    if warnings:
        print("  WARNINGS:")
        for warn in warnings:
            order_id = warn.get('order_id') or 'unknown'
            order_id_display = order_id[:8] if order_id != 'unknown' else order_id
            symbol = warn.get('symbol') or ''
            side = warn.get('side', '').upper() if warn.get('side') else ''
            
            # Format based on whether this is an order-specific or general warning
            if symbol and side:
                print(f"    Order {order_id_display} ({symbol}) {side}: {warn.get('reason')}")
            else:
                print(f"    {warn.get('reason')}")
        print()
    
    if not fills:
        print("  (No fills on this date)")
    else:
        # Validate all fills have filled_avg_price
        missing_price_fills = [f for f in fills if f.get("filled_avg_price") is None]
        if missing_price_fills:
            print("ERROR: The following fills are missing filled_avg_price:", file=sys.stderr)
            for f in missing_price_fills:
                print(
                    f"  Order {f.get('order_id', 'unknown')[:8]}: {f.get('symbol')} "
                    f"{f.get('side', '').upper()} qty={f.get('qty', 0)}",
                    file=sys.stderr
                )
            print("ERROR: Cannot compute cash impact without fill prices.", file=sys.stderr)
            return 1
        
        total_cash_impact = 0.0
        for fill in sorted(fills, key=lambda f: f.get("filled_at") or ""):
            symbol = fill["symbol"]
            side = fill["side"]
            qty = fill["qty"]
            price = fill["filled_avg_price"]
            filled_at = fill.get("filled_at") or "unknown"
            order_id = fill.get("order_id") or "unknown"
            
            # Calculate cash impact (buy = negative, sell = positive)
            # For options: price is per-share, multiply by 100 * qty
            if "symbol" in fill and len(symbol or "") > 10:  # Heuristic for option symbol
                cash_impact = price * 100.0 * qty * (1 if side == "sell" else -1)
            else:
                cash_impact = price * qty * (1 if side == "sell" else -1)
            
            total_cash_impact += cash_impact
            
            print(
                f"  {filled_at[:19]:19s}  {side.upper():4s}  {symbol:25s}  "
                f"qty={qty:8.2f}  price={format_currency(price):>10s}  "
                f"cash_impact={format_currency(cash_impact):>12s}  "
                f"order_id={order_id[:8]}"
            )
        
        print()
        print(f"Total cash impact for {target_date}: {format_currency(total_cash_impact)}")
        print()
        print("NOTE: Fees are not included in cash impact calculations, so total may")
        print("      not reconcile exactly to account cash changes.")
    
    print()
    print("=" * 80)
    print("END OF REPORT (read-only, zero orders placed)")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: Report failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        raise
