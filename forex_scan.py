#!/usr/bin/env python3
"""Forex G10 momentum sleeve (IBKR paper account)."""

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
from src.sleeves.ibkr_signals import rank_by_momentum

logger = structlog.get_logger()

WORKFLOW_ID = "forex-weekly"
PAIRS = [
    ("EURUSD", "EURUSD=X"),
    ("GBPUSD", "GBPUSD=X"),
    ("USDJPY", "JPY=X"),
    ("AUDUSD", "AUDUSD=X"),
]


def main() -> int:
    p = argparse.ArgumentParser(description="Forex weekly sleeve")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    run_orchestrator()
    ranked = rank_by_momentum(PAIRS, months=1)
    if spy_regime_harvest():
        ranked = ranked[:1]
    top = ranked[0] if ranked else None
    row = {"run_date": date.today().isoformat(), "ranked": ranked, "top": top, "executed": False}

    broker = init_workflow_broker(WORKFLOW_ID)
    if broker:
        broker.connect()
    if args.execute and broker and top:
        side = "buy" if top["mom_pct"] >= 0 else "sell"
        qty = 10000
        if not getattr(broker, "dry_run", True):
            broker.place_market_order(top["symbol"], qty, side, sec_type="CASH")
        row["executed"] = True
        row["order"] = {"symbol": top["symbol"], "side": side, "qty": qty}

    append_ledger(WORKFLOW_ID, row)
    if broker and hasattr(broker, "disconnect"):
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
