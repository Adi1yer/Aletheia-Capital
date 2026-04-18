#!/usr/bin/env python3
"""
Lightweight smoke test for the stock trading pipeline (dry run, no orders).

Moved from src/health/check.py. Validates agent signals and portfolio decisions
for a couple of tickers. Exit 0 = healthy.

Usage:
  poetry run python scripts/pipeline_smoke_check.py
  poetry run python scripts/pipeline_smoke_check.py --tickers MSFT,AAPL
"""

from __future__ import annotations

import argparse
from typing import Sequence
import sys

import structlog

from src.trading.pipeline import TradingPipeline

logger = structlog.get_logger()


def run_health_check(tickers: Sequence[str] | None = None) -> None:
    if not tickers:
        tickers = ["MSFT", "AAPL"]

    pipeline = TradingPipeline(parallel_agents=True)

    results = pipeline.run_weekly_trading(
        tickers=list(tickers),
        execute=False,
        scan_cache=None,
        run_config={
            "execute": False,
            "universe": False,
            "max_stocks": len(tickers),
            "ticker_source": "health_check",
        },
    )

    problems: list[str] = []

    allowed_signals = {"bullish", "bearish", "neutral"}

    agent_signals = results.get("agent_signals") or {}
    for agent_key, per_ticker in agent_signals.items():
        for ticker, sig in per_ticker.items():
            signal = sig.get("signal")
            reasoning = sig.get("reasoning", "") or ""
            if signal not in allowed_signals:
                problems.append(
                    f"Invalid signal '{signal}' from agent '{agent_key}' for ticker '{ticker}'"
                )
            if "Analysis failed" in reasoning or "Agent error" in reasoning:
                problems.append(
                    f"Failure-like reasoning from agent '{agent_key}' for '{ticker}': {reasoning}"
                )

    decisions = results.get("decisions") or {}
    for ticker, dec in decisions.items():
        reasoning = dec.get("reasoning", "") or ""
        if "Decision error" in reasoning:
            problems.append(f"Decision error for '{ticker}': {reasoning}")

    if problems:
        logger.error("Health check failed", problem_count=len(problems))
        for p in problems:
            print(f"- {p}", file=sys.stderr)
        raise SystemExit(1)

    logger.info("Health check passed", ticker_count=len(tickers))
    print(f"Health check passed; tickers={list(tickers)}")


def main() -> None:
    p = argparse.ArgumentParser(description="Pipeline smoke check (dry run)")
    p.add_argument("--tickers", type=str, default="", help="Comma-separated tickers (default MSFT,AAPL)")
    args = p.parse_args()
    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers.strip()
        else None
    )
    run_health_check(tickers)


if __name__ == "__main__":
    main()
