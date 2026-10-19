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
from typing import Any, Dict, List
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
    
    equity_positions = broker.get_positions() or {}
    for ticker, pos_dict in equity_positions.items():
        qty = float(pos_dict.get("qty") or 0)
        if qty != 0:
            positions.append({
                "type": "equity",
                "symbol": ticker,
                "qty": qty,
                "market_value": float(pos_dict.get("market_value") or 0.0),
                "avg_entry_price": float(pos_dict.get("avg_entry_price") or 0.0),
                "current_price": float(
                    pos_dict.get("current_price") or pos_dict.get("mark_price") or 0.0
                ),
            })

    option_positions = broker.get_option_positions() or []
    for opt in option_positions:
        qty = float(opt.get("qty") or 0)
        if qty != 0:
            positions.append({
                "type": "option",
                "symbol": opt.get("symbol"),
                "side": opt.get("side"),
                "qty": qty,
                "market_value": float(opt.get("market_value") or 0.0),
                "avg_entry_price": float(
                    opt.get("avg_entry_price") or opt.get("avg_entry") or 0.0
                ),
                "current_price": float(
                    opt.get("current_price") or opt.get("mark_price") or 0.0
                ),
            })

    return positions


def get_fills_for_date(broker, target_date: date) -> List[Dict[str, Any]]:
    """Get fills for a specific date (read-only).
    
    Returns fills with: symbol, side, qty, filled_avg_price, filled_at, order_id
    
    Raises:
        Exception: If orders fetch fails.
    """
    fills = []
    
    # Fetch recent orders (extends back ~60 days typically)
    # Filter for filled orders on the target date
    recent_orders = broker.get_recent_orders(limit=500) or []
    
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
        except (ValueError, AttributeError):
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
            "filled_avg_price": float(order.get("filled_avg_price") or 0.0),
            "filled_at": filled_at_str,
            "order_id": order.get("id"),
            "order_type": order.get("type"),
        })
    
    return fills


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
        positions = get_positions(broker)
    except Exception as e:
        print(f"ERROR: Failed to fetch positions: {e}", file=sys.stderr)
        return 1
    
    print("CURRENT POSITIONS")
    print("-" * 80)
    if not positions:
        print("  (No open positions)")
    else:
        for pos in sorted(positions, key=lambda p: (p["type"], p["symbol"])):
            side = f" ({pos['side']})" if pos.get("side") else ""
            print(
                f"  {pos['type'].upper():8s} {pos['symbol']:25s}{side:10s} "
                f"qty={pos['qty']:8.2f}  mv={format_currency(pos['market_value']):>12s}  "
                f"entry={format_currency(pos['avg_entry_price']):>10s}  "
                f"mark={format_currency(pos['current_price']):>10s}"
            )
    print()

    # Fills for date
    try:
        fills = get_fills_for_date(broker, target_date)
    except Exception as e:
        print(f"ERROR: Failed to fetch fills: {e}", file=sys.stderr)
        return 1
    
    print(f"FILLS ON {target_date.isoformat()}")
    print("-" * 80)
    if not fills:
        print("  (No fills on this date)")
    else:
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
