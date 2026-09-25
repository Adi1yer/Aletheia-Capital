#!/usr/bin/env python3
"""
VRP bake-off: Compare always-on wheel-hybrid vs VIX-gated regime control.

Usage:
    poetry run python scripts/run_vrp_bakeoff.py --start-date 2020-01-01 --end-date 2024-12-31
    poetry run python scripts/run_vrp_bakeoff.py --preset bluechip-2020-2024
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd
import structlog

from src.backtesting.wheel_hybrid.edge_gate import EdgeGate, EdgeMode
from src.backtesting.wheel_hybrid.simulator import WheelHybridSimulator
from src.backtesting.wheel_hybrid.vix_provider import VixDataProvider

logger = structlog.get_logger()

# Predefined test universes
UNIVERSES = {
    "bluechip": ["AAPL", "MSFT", "JPM", "JNJ", "PG", "KO", "DIS", "BA", "CAT", "MMM"],
    "wheel_classic": ["F", "SOFI", "NOK", "ITUB", "ABEV", "GOLD", "NIO", "PLUG", "LCID", "RIVN"],
}

# Predefined test windows
WINDOWS = {
    "covid-recovery": (date(2020, 4, 1), date(2021, 12, 31)),
    "full-2020s": (date(2020, 1, 1), date(2024, 12, 31)),
    "bluechip-2020-2024": (date(2020, 1, 1), date(2024, 12, 31)),
}


def run_bakeoff(
    universe: list[str],
    start_date: date,
    end_date: date,
    initial_capital: float = 10000.0,
    output_dir: str = "docs/backtest_results/vix_gated",
) -> dict:
    """
    Run bake-off: always-on vs VIX-gated wheel-hybrid.

    Args:
        universe: List of ticker symbols
        start_date: Backtest start date
        end_date: Backtest end date
        initial_capital: Starting capital
        output_dir: Directory to save results

    Returns:
        Dict with summary results
    """
    logger.info(
        "Starting VRP bake-off",
        universe_size=len(universe),
        start=str(start_date),
        end=str(end_date),
    )

    # Initialize VIX provider
    vix_provider = VixDataProvider()

    # Get SPY benchmark data
    import yfinance as yf

    spy = yf.Ticker("SPY")
    spy_data = spy.history(start=start_date, end=end_date)
    spy_start = spy_data.iloc[0]["Close"] if not spy_data.empty else 100.0
    spy_end = spy_data.iloc[-1]["Close"] if not spy_data.empty else 100.0
    spy_return = (spy_end / spy_start - 1.0) * 100.0

    logger.info("SPY benchmark", return_pct=round(spy_return, 2))

    # Run always-on backtest
    logger.info("Running always-on backtest...")
    always_on_gate = EdgeGate(mode=EdgeMode.ALWAYS_ON)
    always_on_sim = WheelHybridSimulator(
        universe=universe,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        edge_gate=always_on_gate,
    )
    always_on_result = always_on_sim.run()

    # Run VIX-gated backtest
    logger.info("Running VIX-gated backtest...")
    vix_gate = EdgeGate(
        mode=EdgeMode.VIX_GATED,
        vix_provider=vix_provider,
        vix_percentile_threshold_low=30.0,
        vix_percentile_threshold_high=70.0,
    )
    vix_gated_sim = WheelHybridSimulator(
        universe=universe,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        edge_gate=vix_gate,
    )
    vix_gated_result = vix_gated_sim.run()

    # Calculate metrics
    alpha_vs_always_on = vix_gated_result.total_return - always_on_result.total_return
    alpha_vs_spy = vix_gated_result.total_return - spy_return

    # Calculate Sharpe ratios (annualized)
    def calculate_sharpe(daily_equity: pd.Series) -> float:
        returns = daily_equity.pct_change().dropna()
        if len(returns) == 0:
            return 0.0
        return (returns.mean() * 252) / (returns.std() * (252**0.5)) if returns.std() > 0 else 0.0

    always_on_sharpe = calculate_sharpe(always_on_result.daily_equity)
    vix_gated_sharpe = calculate_sharpe(vix_gated_result.daily_equity)

    # Compile summary
    summary = {
        "backtest_window": {
            "start_date": str(start_date),
            "end_date": str(end_date),
            "initial_capital": initial_capital,
        },
        "universe": {
            "tickers": universe,
            "size": len(universe),
        },
        "spy_benchmark": {
            "total_return_pct": round(spy_return, 2),
            "start_price": round(spy_start, 2),
            "end_price": round(spy_end, 2),
        },
        "always_on": {
            "final_equity": round(always_on_result.final_equity, 2),
            "total_return_pct": round(always_on_result.total_return, 2),
            "premium_collected": round(always_on_result.premium_collected, 2),
            "sharpe_ratio": round(always_on_sharpe, 3),
            "num_cc_writes": always_on_result.num_cc_writes,
        },
        "vix_gated": {
            "final_equity": round(vix_gated_result.final_equity, 2),
            "total_return_pct": round(vix_gated_result.total_return, 2),
            "premium_collected": round(vix_gated_result.premium_collected, 2),
            "sharpe_ratio": round(vix_gated_sharpe, 3),
            "num_cc_writes": vix_gated_result.num_cc_writes,
        },
        "alpha": {
            "vix_gated_vs_always_on_pct": round(alpha_vs_always_on, 2),
            "vix_gated_vs_spy_pct": round(alpha_vs_spy, 2),
            "meets_2pct_hurdle": alpha_vs_always_on >= 2.0,
        },
        "metadata": {
            "wheel_pct": vix_gated_result.metadata.get("wheel_pct", 0.7),
            "max_wheel_names": vix_gated_result.metadata.get("max_wheel_names", 4),
        },
    }

    # Save results
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    summary_file = output_path / f"summary_{start_date}_{end_date}.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info("Saved summary", path=str(summary_file))

    # Save equity curves
    equity_df = pd.DataFrame(
        {
            "date": always_on_result.daily_equity.index,
            "always_on_equity": always_on_result.daily_equity.values,
            "vix_gated_equity": vix_gated_result.daily_equity.values,
        }
    )
    equity_file = output_path / f"equity_curves_{start_date}_{end_date}.csv"
    equity_df.to_csv(equity_file, index=False)

    logger.info("Saved equity curves", path=str(equity_file))

    # Print summary
    print("\n" + "=" * 80)
    print("VRP BAKE-OFF RESULTS")
    print("=" * 80)
    print(f"\nWindow: {start_date} to {end_date}")
    print(f"Universe: {len(universe)} tickers")
    print(f"\nSPY Benchmark:     {spy_return:+.2f}%")
    print(f"\nAlways-On:         {always_on_result.total_return:+.2f}%  (Sharpe: {always_on_sharpe:.3f})")
    print(f"VIX-Gated:         {vix_gated_result.total_return:+.2f}%  (Sharpe: {vix_gated_sharpe:.3f})")
    print(f"\nAlpha vs Always-On: {alpha_vs_always_on:+.2f}%")
    print(f"Alpha vs SPY:       {alpha_vs_spy:+.2f}%")
    print(f"\n≥2% hurdle vs always-on: {'✓ PASS' if summary['alpha']['meets_2pct_hurdle'] else '✗ FAIL'}")
    print("=" * 80)
    print(f"\nResults saved to {output_dir}/")
    print("=" * 80 + "\n")

    return summary


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run VRP wheel-hybrid bake-off")
    parser.add_argument(
        "--preset",
        choices=list(WINDOWS.keys()),
        help="Use predefined test window",
    )
    parser.add_argument(
        "--start-date",
        type=lambda s: date.fromisoformat(s),
        help="Backtest start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=lambda s: date.fromisoformat(s),
        help="Backtest end date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--universe",
        choices=list(UNIVERSES.keys()),
        default="bluechip",
        help="Universe selection",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Initial capital",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/backtest_results/vix_gated",
        help="Output directory for results",
    )

    args = parser.parse_args()

    # Determine date range
    if args.preset:
        start_date, end_date = WINDOWS[args.preset]
    elif args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        parser.error("Must provide either --preset or both --start-date and --end-date")

    universe = UNIVERSES[args.universe]

    run_bakeoff(
        universe=universe,
        start_date=start_date,
        end_date=end_date,
        initial_capital=args.capital,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )
    main()
