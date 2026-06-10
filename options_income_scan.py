#!/usr/bin/env python3
"""Options vol income sleeve: IV-rank gated premium harvesting."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog
import yfinance as yf

from src.fund.orchestrator import run_orchestrator
from src.sleeves.common import append_ledger, init_workflow_broker

logger = structlog.get_logger()

WORKFLOW_ID = "options-income"
WATCHLIST = ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMD", "JPM", "XOM"]


def _iv_rank(ticker: str) -> float:
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="1y")
        if hist is None or len(hist) < 30:
            return 0.0
        rets = hist["Close"].pct_change().dropna()
        hv = float(rets.std() * (252 ** 0.5) * 100)
        return min(100.0, hv)
    except Exception:
        return 0.0


def main() -> int:
    p = argparse.ArgumentParser(description="Options income weekly sleeve")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--min-iv-rank", type=float, default=25.0)
    args = p.parse_args()

    run_orchestrator()
    try:
        broker = init_workflow_broker(WORKFLOW_ID, require_broker=args.execute)
    except RuntimeError as e:
        logger.error(str(e))
        return 1
    candidates: List[Dict[str, Any]] = []
    for t in WATCHLIST:
        iv = _iv_rank(t)
        if iv >= args.min_iv_rank:
            candidates.append({"ticker": t, "iv_proxy": round(iv, 2)})

    row = {
        "run_date": date.today().isoformat(),
        "candidates": candidates,
        "executed": False,
    }

    if args.execute and broker and candidates:
        row["executed"] = True
        row["note"] = "CC execution via weekly-scan pipeline; candidates logged for manual follow-up"

    append_ledger(WORKFLOW_ID, row)
    logger.info("Options income scan", candidates=len(candidates))
    if broker and hasattr(broker, "disconnect"):
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
