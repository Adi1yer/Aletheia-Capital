#!/usr/bin/env python3
"""
Biotech catalyst scanner — standalone from weekly pipeline.

Ingests public data (ClinicalTrials.gov, EDGAR, Yahoo), runs LLM analysis,
optional paper trades on an isolated Alpaca paper account (BIOTECH_ALPACA_* env).

Usage:
  poetry run python biotech_catalyst_scan.py --tickers MRNA,VRTX
  poetry run python biotech_catalyst_scan.py --tickers XBI --paper-execute
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.biotech.analyzer import analyze_snapshot
from src.biotech.calibration import apply_gates
from src.biotech.dataset import append_run
from src.biotech.execution import execute_straddle_paper
from src.biotech.ingest import build_snapshot
from src.biotech.models import BiotechRunRecord
from src.biotech.risk_biotech import BiotechRiskBudget
from src.config.settings import settings

logger = structlog.get_logger()


def main() -> int:
    p = argparse.ArgumentParser(description="Biotech catalyst scan (isolated from weekly pipeline)")
    p.add_argument("--tickers", type=str, required=True, help="Comma-separated tickers")
    p.add_argument("--paper-execute", action="store_true", help="Submit defined-risk paper orders (straddle)")
    p.add_argument("--max-premium-pct-equity", type=float, default=0.02, help="Max premium vs equity (default 2%%)")
    p.add_argument("--out-json", type=str, default="", help="Write combined results to this path")
    args = p.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        logger.error("No tickers")
        return 1

    biotech_key = (settings.biotech_alpaca_api_key or "").strip()
    biotech_sec = (settings.biotech_alpaca_secret_key or "").strip()
    use_isolated = bool(biotech_key and biotech_sec)

    broker = None
    if args.paper_execute:
        if not use_isolated:
            logger.error(
                "Paper execute requires BIOTECH_ALPACA_API_KEY and BIOTECH_ALPACA_SECRET_KEY "
                "in .env (isolated paper account)."
            )
            return 1
        from src.broker.alpaca import AlpacaBroker

        broker = AlpacaBroker(api_key=biotech_key, secret_key=biotech_sec)
        acct = broker.get_account()
        logger.info("Biotech paper account", equity=acct.get("equity"), cash=acct.get("cash"))

    budget = BiotechRiskBudget(max_premium_pct_equity=float(args.max_premium_pct_equity))

    results = []
    for t in tickers:
        logger.info("Building snapshot", ticker=t)
        snap = build_snapshot(t)
        logger.info("Analyzing", ticker=t)
        analysis = analyze_snapshot(snap)
        gates_ok, gate_reasons = apply_gates(snap, analysis)
        exec_result = None
        if args.paper_execute and broker and gates_ok:
            exec_result = execute_straddle_paper(broker, snap, budget)
        elif args.paper_execute and broker and not gates_ok:
            exec_result = {"status": "skipped", "reasons": gate_reasons}

        rec = BiotechRunRecord(
            snapshot=snap,
            analysis=analysis,
            gates_passed=gates_ok,
            execution=exec_result,
        )
        append_run(rec)
        results.append(
            {
                "ticker": t,
                "gates_ok": gates_ok,
                "gate_reasons": gate_reasons,
                "analysis": analysis.model_dump(),
                "execution": exec_result,
            }
        )
        print(json.dumps(results[-1], indent=2, default=str))

    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(results, indent=2, default=str))
        logger.info("Wrote results", path=args.out_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
