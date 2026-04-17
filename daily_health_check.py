#!/usr/bin/env python3
"""Daily position health check: sync Alpaca, summarize P&L vs cost basis, log concentration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.broker.alpaca import AlpacaBroker
from src.config.settings import settings

logger = structlog.get_logger()


def main() -> int:
    p = argparse.ArgumentParser(description="Daily Alpaca position health check")
    p.add_argument(
        "--max-position-pct",
        type=float,
        default=25.0,
        help="Warn if a single long position exceeds this %% of equity (default 25)",
    )
    args = p.parse_args()

    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        logger.error("Alpaca keys not configured")
        return 1

    broker = AlpacaBroker()
    acct = broker.get_account()
    positions = broker.get_positions()
    equity = float(acct.get("equity") or acct.get("portfolio_value") or 0)

    logger.info(
        "Daily health snapshot",
        cash=round(acct.get("cash", 0), 2),
        equity=round(equity, 2),
        position_count=len(positions),
    )

    alerts = []

    for sym, pos in sorted(positions.items(), key=lambda x: -abs(x[1].get("market_value", 0))):
        mv = float(pos.get("market_value", 0))
        qty = int(pos.get("qty", 0))
        avg = float(pos.get("avg_entry_price", 0))
        side = pos.get("side", "long")
        if equity > 0 and side == "long" and mv > 0:
            pct = 100.0 * mv / equity
            if pct > args.max_position_pct:
                alerts.append(f"{sym}: {pct:.1f}% of equity (>{args.max_position_pct}%)")
        if qty and avg:
            last = mv / qty if qty else 0
            pnl_pct = ((last - avg) / avg * 100) if avg > 0 else 0
            logger.info(
                "Position",
                symbol=sym,
                side=side,
                qty=qty,
                avg_entry=round(avg, 4),
                market_value=round(mv, 2),
                pnl_pct=round(pnl_pct, 2),
            )

    if alerts:
        logger.warning("Concentration alerts", alerts=alerts)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
