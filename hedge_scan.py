#!/usr/bin/env python3
"""Beta hedge sleeve: inverse ETF / defensive when SPY regime is harvest."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.data.macro_signals import spy_regime_harvest
from src.fund.orchestrator import run_orchestrator
from src.sleeves.common import append_ledger, init_workflow_broker

logger = structlog.get_logger()

WORKFLOW_ID = "hedge-weekly"
HEDGE_SYMBOL = "SH"  # inverse SPY ETF on Alpaca


def main() -> int:
    p = argparse.ArgumentParser(description="Beta hedge weekly sleeve")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--target-pct", type=float, default=0.15, help="Target % of equity in hedge")
    args = p.parse_args()

    run_orchestrator()
    if not spy_regime_harvest():
        logger.info("Regime not harvest — no hedge action")
        append_ledger(WORKFLOW_ID, {"action": "skip", "reason": "regime_not_harvest", "run_date": date.today().isoformat()})
        return 0

    try:
        broker = init_workflow_broker(WORKFLOW_ID, require_broker=args.execute)
    except RuntimeError as e:
        logger.error(str(e))
        return 1
    if broker is None:
        return 0

    acct = broker.get_account()
    equity = float(acct.get("equity") or 0)
    target_usd = equity * args.target_pct
    positions = broker.get_positions()
    cur_mv = float((positions.get(HEDGE_SYMBOL) or {}).get("market_value", 0))
    delta_usd = target_usd - cur_mv

    row = {
        "run_date": date.today().isoformat(),
        "symbol": HEDGE_SYMBOL,
        "target_pct": args.target_pct,
        "target_usd": round(target_usd, 2),
        "current_mv": round(cur_mv, 2),
        "delta_usd": round(delta_usd, 2),
        "executed": False,
    }

    if args.execute and delta_usd > 500:
        from src.portfolio.manager import PortfolioDecision

        import yfinance as yf

        px = float(yf.Ticker(HEDGE_SYMBOL).history(period="5d")["Close"].iloc[-1])
        qty = max(1, int(delta_usd // px))
        results = broker.execute_decisions({HEDGE_SYMBOL: PortfolioDecision(action="buy", quantity=qty, confidence=80, reasoning="Harvest hedge")})
        row["executed"] = True
        row["qty"] = qty
        row["results"] = str(results)

    append_ledger(WORKFLOW_ID, row)
    logger.info("Hedge scan complete", **{k: row[k] for k in row if k != "results"})
    if hasattr(broker, "disconnect"):
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
