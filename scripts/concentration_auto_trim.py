#!/usr/bin/env python3
"""Auto-trim positions exceeding single-name concentration threshold.

Default OFF. Enable via ENABLE_CONCENTRATION_TRIM=1.

CRO-owned parameters (all have conservative placeholder defaults):
- CONCENTRATION_TRIM_THRESHOLD_PCT: Threshold triggering trim (default 0.25 = 25%)
- CONCENTRATION_TRIM_TARGET_PCT: Target weight after trim (default 0.20 = 20%)
- CONCENTRATION_TRIM_MIN_SHARES: Minimum shares to trim (default 10)
- CONCENTRATION_TRIM_ORDER_TYPE: Order type (default 'market')
- CONCENTRATION_TRIM_MAX_PER_DAY: Max number of trims per day (default 2)
- CONCENTRATION_TRIM_CADENCE_HOURS: Minimum hours between trims of same name (default 24)

Never sells shares covering short calls.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import structlog

from src.broker.alpaca import get_alpaca_broker
from src.risk.concentration import (
    check_single_name_concentration,
    compute_concentration_trim,
)
from src.options.wheel_lifecycle import parse_occ_symbol

logger = structlog.get_logger()

TRIM_STATE_PATH = Path("data/performance/concentration_trim_state.json")


def load_trim_state() -> Dict[str, Any]:
    """Load trim state (last trim timestamps per ticker)."""
    if not TRIM_STATE_PATH.is_file():
        return {"last_trims": {}, "updated_at": None}
    try:
        return json.loads(TRIM_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"last_trims": {}, "updated_at": None}


def save_trim_state(state: Dict[str, Any]) -> None:
    """Save trim state."""
    TRIM_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    TRIM_STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def is_trim_allowed_for_ticker(
    ticker: str,
    last_trims: Dict[str, str],
    cadence_hours: float,
) -> bool:
    """Check if enough time has passed since last trim of this ticker."""
    last_trim = last_trims.get(str(ticker).upper())
    if not last_trim:
        return True
    try:
        last_dt = datetime.fromisoformat(last_trim.replace("Z", "+00:00"))
        elapsed = datetime.utcnow() - last_dt.replace(tzinfo=None)
        return elapsed.total_seconds() >= cadence_hours * 3600
    except Exception:
        return True


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Auto-trim positions exceeding concentration threshold")
    p.add_argument("--execute", action="store_true", help="Execute trim orders (default dry-run)")
    p.add_argument("--enable", action="store_true", help="Force enable (override ENABLE_CONCENTRATION_TRIM env)")
    args = p.parse_args(argv)

    # Gate: ENABLE_CONCENTRATION_TRIM must be "1", "true", or "yes"
    enable_env = os.environ.get("ENABLE_CONCENTRATION_TRIM", "").strip().lower()
    enabled = args.enable or enable_env in ("1", "true", "yes")
    
    if not enabled:
        logger.info(
            "Concentration auto-trim DISABLED (ENABLE_CONCENTRATION_TRIM=0 or unset)",
            enable_env=enable_env or "(unset)",
        )
        print("Concentration auto-trim: DISABLED (ENABLE_CONCENTRATION_TRIM=0)")
        return 0
    
    # Load CRO-owned parameters (all have conservative defaults)
    try:
        threshold_pct = float(os.environ.get("CONCENTRATION_TRIM_THRESHOLD_PCT", "0.25"))
        target_pct = float(os.environ.get("CONCENTRATION_TRIM_TARGET_PCT", "0.20"))
        min_trim_shares = int(os.environ.get("CONCENTRATION_TRIM_MIN_SHARES", "10"))
        order_type = os.environ.get("CONCENTRATION_TRIM_ORDER_TYPE", "market").strip().lower()
        max_per_day = int(os.environ.get("CONCENTRATION_TRIM_MAX_PER_DAY", "2"))
        cadence_hours = float(os.environ.get("CONCENTRATION_TRIM_CADENCE_HOURS", "24"))
    except (ValueError, TypeError) as e:
        logger.error("Invalid concentration trim parameter", error=str(e))
        print(f"ERROR: Invalid trim parameter: {e}", file=sys.stderr)
        return 1
    
    if not (0.0 < threshold_pct <= 1.0):
        logger.error("Invalid threshold_pct", value=threshold_pct)
        print(f"ERROR: CONCENTRATION_TRIM_THRESHOLD_PCT must be in (0, 1], got {threshold_pct}", file=sys.stderr)
        return 1
    
    if not (0.0 < target_pct < threshold_pct):
        logger.error("Invalid target_pct", value=target_pct, threshold=threshold_pct)
        print(
            f"ERROR: CONCENTRATION_TRIM_TARGET_PCT must be in (0, threshold), got {target_pct} vs {threshold_pct}",
            file=sys.stderr,
        )
        return 1
    
    if order_type not in ("market", "limit"):
        logger.error("Invalid order_type", value=order_type)
        print(f"ERROR: CONCENTRATION_TRIM_ORDER_TYPE must be 'market' or 'limit', got {order_type}", file=sys.stderr)
        return 1
    
    logger.info(
        "Concentration auto-trim ENABLED",
        threshold_pct=round(threshold_pct * 100, 1),
        target_pct=round(target_pct * 100, 1),
        min_trim_shares=min_trim_shares,
        order_type=order_type,
        max_per_day=max_per_day,
        cadence_hours=cadence_hours,
        execute=args.execute,
    )
    
    # Connect to broker
    try:
        broker = get_alpaca_broker(workflow_id="wheel-10k")
    except Exception as e:
        logger.error("Broker connection failed", error=str(e))
        print(f"ERROR: Broker connection failed: {e}", file=sys.stderr)
        return 1
    
    # Fetch current state
    try:
        portfolio = broker.sync_portfolio()
        account = broker.get_account()
        equity = float(account.get("equity") or account.get("portfolio_value") or 0.0)
        
        positions = broker.get_positions()
        current_prices = {
            str(p.get("symbol") or "").upper(): float(p.get("current_price") or 0.0)
            for p in positions
            if p.get("symbol") and float(p.get("current_price") or 0.0) > 0
        }
        
        option_positions = broker.get_option_positions()
    except Exception as e:
        logger.error("Failed to fetch portfolio state", error=str(e))
        print(f"ERROR: Failed to fetch portfolio state: {e}", file=sys.stderr)
        return 1
    
    # Build short call map (do not sell shares covering short calls)
    short_calls_by_underlying: Dict[str, int] = {}
    for pos in option_positions or []:
        if str(pos.get("side") or "").lower() != "short":
            continue
        parsed = parse_occ_symbol(str(pos.get("symbol") or ""))
        if not parsed or parsed.get("option_type") != "call":
            continue
        und = str(parsed.get("underlying") or "").upper()
        if not und:
            continue
        try:
            qty = int(pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            short_calls_by_underlying[und] = short_calls_by_underlying.get(und, 0) + qty
    
    # Check concentration
    passed, alerts, diagnostics = check_single_name_concentration(
        portfolio=portfolio,
        current_prices=current_prices,
        equity=equity,
        threshold_pct=threshold_pct,
        fail_closed_on_missing_data=True,
    )
    
    if passed:
        logger.info("No concentration breaches detected", **diagnostics)
        print(f"Concentration check: PASSED (max {diagnostics.get('max_concentration_pct', 0):.1f}% / {threshold_pct * 100:.0f}%)")
        return 0
    
    logger.warning("Concentration breaches detected", alerts=len(alerts), **diagnostics)
    print(f"Concentration check: BREACH ({len(alerts)} names >= {threshold_pct * 100:.0f}%)")
    
    # Load trim state
    state = load_trim_state()
    last_trims = state.get("last_trims") or {}
    trims_today = [
        ts for ts in last_trims.values()
        if ts and (datetime.utcnow() - datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)).days == 0
    ]
    
    if len(trims_today) >= max_per_day:
        logger.info(
            "Max trims per day reached",
            trims_today=len(trims_today),
            max_per_day=max_per_day,
        )
        print(f"Max trims per day reached ({len(trims_today)}/{max_per_day})")
        return 0
    
    # Compute trims
    trim_candidates: List[Dict[str, Any]] = []
    for alert in alerts:
        ticker = str(alert.get("ticker") or "").upper()
        if not ticker:
            continue
        
        if not is_trim_allowed_for_ticker(ticker, last_trims, cadence_hours):
            logger.info("Trim blocked by cadence gate", ticker=ticker, cadence_hours=cadence_hours)
            continue
        
        trim_details = compute_concentration_trim(
            ticker=ticker,
            portfolio=portfolio,
            current_prices=current_prices,
            equity=equity,
            threshold_pct=threshold_pct,
            target_pct=target_pct,
            min_trim_shares=min_trim_shares,
            fail_closed_on_missing_data=True,
            short_calls_by_underlying=short_calls_by_underlying,
        )
        
        if trim_details is None:
            continue
        
        if trim_details.get("status") == "trim_below_min":
            logger.info("Trim below minimum", ticker=ticker, **trim_details)
            continue
        
        if trim_details.get("status") == "trim_needed":
            trim_candidates.append(trim_details)
    
    if not trim_candidates:
        logger.info("No actionable trims after filtering")
        print("No actionable trims (all below min or blocked by gates)")
        return 0
    
    # Execute trims (respecting max_per_day)
    executed_count = 0
    for trim in trim_candidates[: max_per_day - len(trims_today)]:
        ticker = trim["ticker"]
        qty = trim["trim_qty"]
        
        logger.info(
            "Concentration trim",
            ticker=ticker,
            qty=qty,
            current_weight_pct=trim["current_weight_pct"],
            post_trim_weight_pct=trim["post_trim_weight_pct"],
            execute=args.execute,
        )
        
        print(
            f"Trim {ticker}: {qty} shares "
            f"({trim['current_weight_pct']:.1f}% → {trim['post_trim_weight_pct']:.1f}%)"
        )
        
        if args.execute:
            try:
                order = broker.submit_equity_order(
                    symbol=ticker,
                    qty=qty,
                    side="sell",
                    order_type=order_type,
                    time_in_force="day",
                )
                
                order_id = str(order.get("id") or order.get("order_id") or "")
                filled_ok = order.get("status") in ("filled", "partially_filled") if order else False
                
                logger.info(
                    "Trim order submitted",
                    ticker=ticker,
                    qty=qty,
                    order_id=order_id,
                    filled_ok=filled_ok,
                )
                
                print(f"  → Order {order_id}: {'FILLED' if filled_ok else 'SUBMITTED'}")
                
                # Record trim
                last_trims[ticker] = datetime.utcnow().isoformat() + "Z"
                executed_count += 1
                
            except Exception as e:
                logger.error("Trim order failed", ticker=ticker, error=str(e))
                print(f"  → ERROR: {e}", file=sys.stderr)
        else:
            print("  → DRY-RUN (pass --execute to submit orders)")
    
    # Save updated state
    if args.execute and executed_count > 0:
        state["last_trims"] = last_trims
        save_trim_state(state)
        logger.info("Trim state saved", executed=executed_count)
    
    print(
        f"\nConcentration auto-trim: "
        f"{'executed' if args.execute else 'dry-run'} "
        f"{executed_count}/{len(trim_candidates)} trims"
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
