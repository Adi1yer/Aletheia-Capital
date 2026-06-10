#!/usr/bin/env python3
"""Commodities momentum sleeve (IBKR paper account)."""

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
from src.sleeves.ibkr_signals import momentum_pct, rank_by_momentum

logger = structlog.get_logger()

WORKFLOW_ID = "commodities"
CONTRACTS = [("CL", "CL=F"), ("GC", "GC=F"), ("HG", "HG=F")]


def main() -> int:
    p = argparse.ArgumentParser(description="Commodities sleeve")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    run_orchestrator()
    ranked = rank_by_momentum(CONTRACTS, months=3)
    long_m = rank_by_momentum(CONTRACTS, months=12)
    picks = []
    for r in ranked:
        lm = next((x for x in long_m if x["symbol"] == r["symbol"]), r)
        if r["mom_pct"] > 0 and lm["mom_pct"] > 0:
            picks.append(r)
    picks = picks[:2]
    row = {"run_date": date.today().isoformat(), "ranked": ranked, "picks": picks, "executed": False}

    broker = init_workflow_broker(WORKFLOW_ID)
    if broker:
        broker.connect()
    if args.execute and broker and picks:
        for p in picks:
            if not getattr(broker, "dry_run", True):
                broker.place_market_order(p["symbol"], 1, "buy", sec_type="FUT")
        row["executed"] = True

    append_ledger(WORKFLOW_ID, row)
    if broker and hasattr(broker, "disconnect"):
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
