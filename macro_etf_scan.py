#!/usr/bin/env python3
"""Macro ETF rotation sleeve on dedicated Alpaca paper account."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog
import yfinance as yf

from src.data.macro_signals import spy_regime_harvest
from src.fund.orchestrator import run_orchestrator
from src.sleeves.common import append_ledger, init_workflow_broker

logger = structlog.get_logger()

WORKFLOW_ID = "macro-etf"
ETF_MAP = {"accumulate": ["SPY", "QQQ"], "harvest": ["TLT", "GLD"], "neutral": ["SHY", "UUP"]}


def _momentum(sym: str, months: int = 3) -> float:
    hist = yf.Ticker(sym).history(period=f"{months}mo")
    if hist is None or len(hist) < 5:
        return 0.0
    return float((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100)


def main() -> int:
    p = argparse.ArgumentParser(description="Macro ETF sleeve")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    run_orchestrator()
    regime = "harvest" if spy_regime_harvest() else "accumulate"
    universe = ETF_MAP.get(regime, ETF_MAP["neutral"])
    ranked = sorted(universe, key=_momentum, reverse=True)
    pick = ranked[0] if ranked else "SHY"

    row = {"run_date": date.today().isoformat(), "regime": regime, "pick": pick, "executed": False}
    try:
        broker = init_workflow_broker(WORKFLOW_ID, require_broker=args.execute)
    except RuntimeError as e:
        logger.error(str(e))
        return 1

    if args.execute and broker:
        from src.portfolio.manager import PortfolioDecision

        acct = broker.get_account()
        equity = float(acct.get("equity") or 0)
        px = float(yf.Ticker(pick).history(period="5d")["Close"].iloc[-1])
        qty = max(1, int((equity * 0.2) // px))
        broker.execute_decisions(
            {pick: PortfolioDecision(action="buy", quantity=qty, confidence=70, reasoning=f"Macro ETF {regime}")}
        )
        row.update({"executed": True, "qty": qty})

    append_ledger(WORKFLOW_ID, row)
    logger.info("Macro ETF scan", pick=pick, regime=regime)
    if broker and hasattr(broker, "disconnect"):
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
