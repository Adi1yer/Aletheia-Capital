#!/usr/bin/env python3
"""Crypto weekly sleeve on isolated Alpaca crypto paper account."""

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
from src.trading.crypto_pipeline import CryptoTradingPipeline, DEFAULT_CRYPTO_TICKERS

logger = structlog.get_logger()

WORKFLOW_ID = "crypto-weekly"


def main() -> int:
    p = argparse.ArgumentParser(description="Crypto weekly sleeve")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    run_orchestrator()
    pipeline = CryptoTradingPipeline()
    results = pipeline.run(tickers=DEFAULT_CRYPTO_TICKERS, execute=args.execute)

    broker = init_workflow_broker(WORKFLOW_ID)
    row = {
        "run_date": date.today().isoformat(),
        "tickers": DEFAULT_CRYPTO_TICKERS,
        "pipeline_summary": str(results)[:500],
        "executed": args.execute,
    }
    append_ledger(WORKFLOW_ID, row)
    logger.info("Crypto weekly scan complete")
    if broker and hasattr(broker, "disconnect"):
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
