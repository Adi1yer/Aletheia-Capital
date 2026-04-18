#!/usr/bin/env python3
"""
Biotech catalyst scanner — standalone from weekly pipeline.

Ingests public data (ClinicalTrials.gov, EDGAR, Yahoo), runs LLM analysis,
optional paper trades on an isolated Alpaca paper account (BIOTECH_ALPACA_* env).

By default, only tickers with at least one trial whose primary/completion date falls
in the readout window (see settings / env) are analyzed — intended for near-term
trial readout catalysts.

Usage:
  poetry run python biotech_catalyst_scan.py --tickers MRNA,VRTX
  poetry run python biotech_catalyst_scan.py --from-watchlist
  poetry run python biotech_catalyst_scan.py --from-watchlist --paper-execute
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
from src.biotech.readout_window import snapshot_has_readout_catalyst
from src.biotech.risk_biotech import BiotechRiskBudget
from src.biotech.watchlist import load_biotech_tickers
from src.config.settings import settings

logger = structlog.get_logger()


def _resolve_tickers(args: argparse.Namespace) -> list[str]:
    if args.from_watchlist:
        tickers = load_biotech_tickers()
        if not tickers:
            logger.error(
                "No tickers: set BIOTECH_TICKERS or add symbols to config/biotech_watchlist.txt",
            )
            sys.exit(1)
        return tickers
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        logger.error("No tickers")
        sys.exit(1)
    return tickers


def main() -> int:
    p = argparse.ArgumentParser(description="Biotech catalyst scan (isolated from weekly pipeline)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--tickers",
        type=str,
        help="Comma-separated tickers (skips watchlist file)",
    )
    g.add_argument(
        "--from-watchlist",
        action="store_true",
        help="Use BIOTECH_TICKERS env or config/biotech_watchlist.txt",
    )
    p.add_argument(
        "--paper-execute",
        action="store_true",
        help="Submit defined-risk paper orders (straddle)",
    )
    p.add_argument(
        "--max-premium-pct-equity",
        type=float,
        default=0.02,
        help="Max premium vs equity (default 2%%)",
    )
    p.add_argument("--out-json", type=str, default="", help="Write combined results to this path")
    p.add_argument(
        "--skip-readout-filter",
        action="store_true",
        help="Analyze every ticker even if no trial is in the readout window (not recommended)",
    )
    args = p.parse_args()

    tickers = _resolve_tickers(args)

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

    fwd = int(settings.biotech_readout_forward_days)
    grace = int(settings.biotech_readout_past_grace_days)

    results = []
    for t in tickers:
        logger.info("Building snapshot", ticker=t)
        snap = build_snapshot(t)
        if not args.skip_readout_filter and not snapshot_has_readout_catalyst(
            snap,
            forward_days=fwd,
            past_grace_days=grace,
        ):
            logger.info(
                "Skipping ticker — no trial in readout window",
                ticker=t,
                forward_days=fwd,
                past_grace_days=grace,
            )
            row = {
                "ticker": t,
                "skipped": True,
                "skip_reason": "no_trial_in_readout_window",
                "gates_ok": False,
                "gate_reasons": [],
                "analysis": None,
                "execution": None,
            }
            results.append(row)
            print(json.dumps(row, indent=2, default=str))
            continue

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
                "skipped": False,
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
