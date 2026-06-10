#!/usr/bin/env python3
"""Congressional tradable sleeve: follow disclosed politician stock trades."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.data.providers.aggregator import get_data_provider
from src.fund.orchestrator import run_orchestrator
from src.sleeves.common import append_ledger, init_workflow_broker

logger = structlog.get_logger()

WORKFLOW_ID = "congressional"


WATCHLIST = ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "JPM"]


def _recent_buys(limit: int = 5) -> List[Dict[str, Any]]:
    provider = get_data_provider()
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=60)).isoformat()
    buys: List[Dict[str, Any]] = []
    for ticker in WATCHLIST:
        try:
            trades = provider.get_congressional_trades(ticker, end, start, limit=20)
        except Exception:
            trades = []
        for t in trades or []:
            tx = str(t.get("transaction_type") or t.get("type") or "").lower()
            if "buy" in tx or "purchase" in tx:
                buys.append({"ticker": ticker, "side": tx, "name": t.get("name")})
    seen = set()
    out = []
    for b in buys:
        if b["ticker"] in seen:
            continue
        seen.add(b["ticker"])
        out.append(b)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Congressional trades sleeve")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--notional-per-name", type=float, default=500.0)
    args = p.parse_args()

    run_orchestrator()
    picks = _recent_buys()
    row = {"run_date": date.today().isoformat(), "picks": picks, "executed": False}

    broker = init_workflow_broker(WORKFLOW_ID)
    if args.execute and broker and picks:
        from src.portfolio.manager import PortfolioDecision

        import yfinance as yf

        for pick in picks[:3]:
            t = pick["ticker"]
            try:
                px = float(yf.Ticker(t).history(period="5d")["Close"].iloc[-1])
                qty = max(1, int(args.notional_per_name // px))
                broker.execute_decisions(
                    {t: PortfolioDecision(action="buy", quantity=qty, confidence=55, reasoning="Congressional buy signal")}
                )
                pick["qty"] = qty
            except Exception as e:
                pick["error"] = str(e)
        row["executed"] = True

    append_ledger(WORKFLOW_ID, row)
    logger.info("Congressional scan", picks=len(picks))
    if broker and hasattr(broker, "disconnect"):
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
