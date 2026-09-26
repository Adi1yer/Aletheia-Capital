#!/usr/bin/env python3
"""CLI to run directional sleeve mode bake-off: bluechip_ew vs spy_buyhold."""

import argparse
import json
import sys
from pathlib import Path

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.wheel_hybrid.engine import WheelHybridBacktest
from src.backtesting.wheel_hybrid.universe import get_wheel_universe
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


def run_arm(
    arm_name: str,
    universe: list,
    start_date: str,
    end_date: str,
    initial_nav: float,
    directional_sleeve_mode: str,
    benchmark: str,
    data_provider,
) -> dict:
    """Run one arm of the bake-off."""
    
    logger.info(
        "Running arm",
        arm=arm_name,
        mode=directional_sleeve_mode,
        start=start_date,
        end=end_date,
    )
    
    backtest = WheelHybridBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=initial_nav,
        benchmark_ticker=benchmark,
        directional_sleeve_mode=directional_sleeve_mode,
    )
    
    results = backtest.run(universe, data_provider)
    
    if not results:
        logger.error("Arm failed", arm=arm_name)
        return {}
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Run directional sleeve mode bake-off"
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2020-01-01",
        help="Start date (YYYY-MM-DD). Default: 2020-01-01.",
    )
    parser.add_argument(
        "--end",
        type=str,
        default="2024-12-31",
        help="End date (YYYY-MM-DD). Default: 2024-12-31.",
    )
    parser.add_argument(
        "--nav",
        type=float,
        default=10000.0,
        help="Initial NAV (default: 10000)",
    )
    parser.add_argument(
        "--universe",
        type=str,
        default="bluechip",
        choices=["bluechip", "expanded", "auto"],
        help="Universe selection: bluechip (6 names), expanded (~45 names), auto (date-based). Default: bluechip.",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default="^SPXTR",
        help="Benchmark ticker (default: ^SPXTR = SPY total return)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="docs/backtest_results/directional_spy_buyhold/2020_2024_bluechip",
        help="Output directory for results",
    )
    
    args = parser.parse_args()
    
    # Get universe
    universe = get_wheel_universe(args.start, universe_type=args.universe)
    
    logger.info(
        "Starting directional sleeve bake-off",
        start=args.start,
        end=args.end,
        nav=args.nav,
        universe_type=args.universe,
        universe_count=len(universe),
    )
    
    # Initialize data provider
    data_provider = YahooFinanceProvider()
    
    # Run Arm A: bluechip_ew (baseline)
    results_a = run_arm(
        arm_name="Arm A (bluechip_ew baseline)",
        universe=universe,
        start_date=args.start,
        end_date=args.end,
        initial_nav=args.nav,
        directional_sleeve_mode="bluechip_ew",
        benchmark=args.benchmark,
        data_provider=data_provider,
    )
    
    if not results_a:
        logger.error("Arm A failed, aborting bake-off")
        return 1
    
    # Run Arm B: spy_buyhold
    results_b = run_arm(
        arm_name="Arm B (spy_buyhold)",
        universe=universe,
        start_date=args.start,
        end_date=args.end,
        initial_nav=args.nav,
        directional_sleeve_mode="spy_buyhold",
        benchmark=args.benchmark,
        data_provider=data_provider,
    )
    
    if not results_b:
        logger.error("Arm B failed, aborting bake-off")
        return 1
    
    # Prepare summary comparison
    summary_a = results_a.get("summary", {})
    summary_b = results_b.get("summary", {})
    
    # Calculate deltas
    delta_abs_return = summary_b.get("abs_return_pct", 0) - summary_a.get("abs_return_pct", 0)
    delta_excess_spy = summary_b.get("excess_return_pct", 0) - summary_a.get("excess_return_pct", 0)
    delta_sharpe = summary_b.get("sharpe", 0) - summary_a.get("sharpe", 0)
    delta_turnover = summary_b.get("turnover", 0) - summary_a.get("turnover", 0)
    
    # Recommendation logic
    KEEP_THRESHOLD = 2.0  # pp improvement vs baseline
    recommendation = "KEEP" if delta_abs_return >= KEEP_THRESHOLD else "ABANDON"
    
    comparison = {
        "bakeoff_metadata": {
            "start_date": args.start,
            "end_date": args.end,
            "initial_nav": args.nav,
            "universe_type": args.universe,
            "universe_tickers": universe,
            "benchmark": args.benchmark,
        },
        "arm_a_bluechip_ew_baseline": summary_a,
        "arm_b_spy_buyhold": summary_b,
        "deltas": {
            "abs_return_pct": delta_abs_return,
            "excess_vs_spy_pct": delta_excess_spy,
            "sharpe": delta_sharpe,
            "turnover": delta_turnover,
        },
        "recommendation": recommendation,
        "keep_threshold_pp": KEEP_THRESHOLD,
    }
    
    # Save results
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_dir / "summary.json", "w") as f:
        json.dump(comparison, f, indent=2)
    
    with open(output_dir / "arm_a_equity_curve.csv", "w") as f:
        f.write("date,nav,spy\n")
        for (date_str, nav), (_, spy_level) in zip(
            results_a["equity_curve"], results_a["spy_curve"]
        ):
            f.write(f"{date_str},{nav},{spy_level}\n")
    
    with open(output_dir / "arm_b_equity_curve.csv", "w") as f:
        f.write("date,nav,spy\n")
        for (date_str, nav), (_, spy_level) in zip(
            results_b["equity_curve"], results_b["spy_curve"]
        ):
            f.write(f"{date_str},{nav},{spy_level}\n")
    
    # Print summary
    print("\n" + "=" * 80)
    print(f"DIRECTIONAL SLEEVE BAKE-OFF RESULTS ({args.start} to {args.end})")
    print("=" * 80)
    print()
    print("ARM A: bluechip_ew (baseline)")
    print(f"  Absolute Return:  {summary_a.get('abs_return_pct', 0):+.2f}%")
    print(f"  Excess vs SPY:    {summary_a.get('excess_return_pct', 0):+.2f}%")
    print(f"  Sharpe:           {summary_a.get('sharpe', 0):.2f}")
    print(f"  Max DD:           {summary_a.get('max_drawdown_pct', 0):.2f}%")
    print(f"  Turnover:         {summary_a.get('turnover', 0):.2f}x")
    print(f"  Premium:          ${summary_a.get('premium_collected', 0):,.2f}")
    print(f"  CC Writes:        {summary_a.get('trade_counts', {}).get('cc_writes', 0)}")
    print()
    print("ARM B: spy_buyhold")
    print(f"  Absolute Return:  {summary_b.get('abs_return_pct', 0):+.2f}%")
    print(f"  Excess vs SPY:    {summary_b.get('excess_return_pct', 0):+.2f}%")
    print(f"  Sharpe:           {summary_b.get('sharpe', 0):.2f}")
    print(f"  Max DD:           {summary_b.get('max_drawdown_pct', 0):.2f}%")
    print(f"  Turnover:         {summary_b.get('turnover', 0):.2f}x")
    print(f"  Premium:          ${summary_b.get('premium_collected', 0):,.2f}")
    print(f"  CC Writes:        {summary_b.get('trade_counts', {}).get('cc_writes', 0)}")
    print()
    print("DELTAS (B - A)")
    print(f"  Absolute Return:  {delta_abs_return:+.2f}pp")
    print(f"  Excess vs SPY:    {delta_excess_spy:+.2f}pp")
    print(f"  Sharpe:           {delta_sharpe:+.3f}")
    print(f"  Turnover:         {delta_turnover:+.2f}x")
    print()
    print(f"RECOMMENDATION: {recommendation}")
    if recommendation == "KEEP":
        print(f"  ✓ Arm B beats Arm A by ≥{KEEP_THRESHOLD}pp")
    else:
        print(f"  ✗ Arm B improvement < {KEEP_THRESHOLD}pp threshold")
    print()
    print(f"Results saved: {output_dir}/")
    print("  - summary.json")
    print("  - arm_a_equity_curve.csv")
    print("  - arm_b_equity_curve.csv")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
