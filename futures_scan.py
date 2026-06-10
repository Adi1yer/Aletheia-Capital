#!/usr/bin/env python3
"""Futures trend CTA-lite sleeve (IBKR paper account)."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.fund.orchestrator import run_orchestrator
from src.sleeves.common import append_ledger, init_workflow_broker
from src.sleeves.ibkr_signals import rank_by_momentum

logger = structlog.get_logger()

WORKFLOW_ID = "futures-trend"
CONTRACTS = [("MES", "ES=F"), ("MNQ", "NQ=F"), ("ZN", "ZN=F")]


def main() -> int:
    p = argparse.ArgumentParser(description="Futures trend sleeve")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    run_orchestrator()
    ranked = rank_by_momentum(CONTRACTS, months=12)
    picks = [r for r in ranked if abs(r["mom_pct"]) > 2.0][:2]
    row = {"run_date": date.today().isoformat(), "ranked": ranked, "picks": picks, "executed": False}

    broker = init_workflow_broker(WORKFLOW_ID)
    if broker:
        broker.connect()
    if args.execute and broker and picks:
        for p in picks:
            side = "buy" if p["mom_pct"] > 0 else "sell"
            if not getattr(broker, "dry_run", True):
                broker.place_market_order(p["symbol"], 1, side, sec_type="FUT")
        row["executed"] = True

    append_ledger(WORKFLOW_ID, row)
    if broker and hasattr(broker, "disconnect"):
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
