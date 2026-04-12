"""Simple health check for the weekly trading pipeline.

Runs a tiny dry-run over a couple of tickers and asserts:
- All agent signals use canonical signals: bullish/bearish/neutral
- No agent reasoning contains failure markers (\"Analysis failed\", \"Agent error\")
- No portfolio decision reasoning contains \"Decision error\"

Exit code 0 means healthy, non-zero means something regressed.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence
import sys

import structlog

from src.trading.pipeline import TradingPipeline


logger = structlog.get_logger()


def run_health_check(tickers: Sequence[str] | None = None) -> None:
    if not tickers:
        tickers = ["MSFT", "AAPL"]

    end = date.today()
    start = end - timedelta(days=90)

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

    # 1) Validate agent signals
    agent_signals = results.get("agent_signals") or {}
    allowed_signals = {"bullish", "bearish,neutral".split(",")[0], "neutral"}  # keep explicit set
    allowed_signals = {"bullish", "bearish", "neutral"}

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

    # 2) Validate portfolio decisions
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


if __name__ == "__main__":
    run_health_check()

