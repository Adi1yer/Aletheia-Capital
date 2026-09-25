#!/usr/bin/env python3
"""CLI to run wheel hybrid backtest."""

import argparse
import sys
from pathlib import Path

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.wheel_hybrid.engine import WheelHybridBacktest
from src.backtesting.wheel_hybrid.universe import get_wheel_universe
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


def main():
    parser = argparse.ArgumentParser(
        description="Run wheel hybrid backtest with synthetic option pricing"
    )
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--nav",
        type=float,
        default=10000.0,
        help="Initial NAV (default: 10000)",
    )
    parser.add_argument(
        "--wheel-pct",
        type=float,
        default=0.70,
        help="Wheel sleeve target percentage (default: 0.70)",
    )
    parser.add_argument(
        "--directional-pct",
        type=float,
        default=0.30,
        help="Directional sleeve target percentage (default: 0.30)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output directory for results",
    )
    parser.add_argument(
        "--universe",
        type=str,
        nargs="+",
        help="Custom universe (space-separated tickers). Default: fixed research universe.",
    )
    parser.add_argument(
        "--use-fallback",
        action="store_true",
        help="Use fallback universe if primary has data issues",
    )
    
    args = parser.parse_args()
    
    # Get universe
    if args.universe:
        universe = args.universe
    else:
        universe = get_wheel_universe(args.start, use_fallback=args.use_fallback)
    
    logger.info(
        "Starting backtest",
        start=args.start,
        end=args.end,
        nav=args.nav,
        universe=universe,
    )
    
    # Initialize backtest
    backtest = WheelHybridBacktest(
        start_date=args.start,
        end_date=args.end,
        initial_nav=args.nav,
        wheel_pct=args.wheel_pct,
        directional_pct=args.directional_pct,
    )
    
    # Run with Yahoo Finance provider
    data_provider = YahooFinanceProvider()
    
    results = backtest.run(universe, data_provider)
    
    if not results:
        logger.error("Backtest failed")
        return 1
    
    # Save results
    output_dir = Path(args.out)
    backtest.save_results(output_dir)
    
    # Print summary
    summary = results.get("summary", {})
    
    print("\n" + "=" * 60)
    print(f"Wheel Hybrid Backtest ({args.start} to {args.end})")
    print("=" * 60)
    print(f"Start NAV:        ${summary.get('start_nav', 0):,.2f}")
    print(f"End NAV:          ${summary.get('end_nav', 0):,.2f}")
    print(f"Absolute Return:  {summary.get('abs_return_pct', 0):+.2f}%")
    print(f"SPY Return:       {summary.get('spy_return_pct', 0):+.2f}%")
    print(f"Excess Return:    {summary.get('excess_return_pct', 0):+.2f}% / ${summary.get('excess_return_usd', 0):+,.2f}")
    print()
    print(f"Max Drawdown:     {summary.get('max_drawdown_pct', 0):.2f}%")
    print(f"Sharpe (rf=0%):   {summary.get('sharpe', 0):.2f}")
    print(f"Sortino (rf=0%):  {summary.get('sortino', 0):.2f}")
    print(f"Beta:             {summary.get('beta', 0):.2f}")
    print(f"Correlation:      {summary.get('correlation', 0):.2f}")
    print(f"Alpha (annual):   {summary.get('alpha_annual_pct', 0):+.2f}%")
    print()
    print(f"Hit Rate:         {summary.get('hit_rate_pct', 0):.1f}% ({summary.get('hit_sessions', 0)}/{summary.get('total_sessions', 0)} sessions)")
    print(f"Turnover:         {summary.get('turnover', 0):.2f}x")
    print(f"Premium Collected: ${summary.get('premium_collected', 0):,.2f}")
    print()
    
    trade_counts = summary.get("trade_counts", {})
    print("Trade Counts:")
    print(f"  CC Writes:      {trade_counts.get('cc_writes', 0)}")
    print(f"  CSP Writes:     {trade_counts.get('csp_writes', 0)}")
    print(f"  BTC Calls:      {trade_counts.get('btc_calls', 0)}")
    print(f"  BTC Puts:       {trade_counts.get('btc_puts', 0)}")
    print(f"  Call Assigns:   {trade_counts.get('assignments_call', 0)}")
    print(f"  Put Assigns:    {trade_counts.get('assignments_put', 0)}")
    print()
    print(f"Results saved: {output_dir}/")
    print("  - equity_curve.csv")
    print("  - trades.csv")
    print("  - summary.json")
    print("  - assumptions.json")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
