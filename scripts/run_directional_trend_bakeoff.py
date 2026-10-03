#!/usr/bin/env python3
"""
Directional Sleeve Trend Bake-off
==================================

Compare three strategies on same universe and time window:
1. Baseline Hybrid (wheel always-on + passive directional)
2. Trend Hybrid (wheel always-on + trend-filtered directional)
3. SPY Buy-and-Hold

Outputs side-by-side comparison + JSON results.
"""

import argparse
import json
import sys
from pathlib import Path
import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.wheel_hybrid.engine import WheelHybridBacktest
from src.backtesting.wheel_hybrid.universe import get_wheel_universe
from src.backtesting.wheel_hybrid.directional_trend import DirectionalTrendOverlay, TrendConfig
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


def run_backtest(
    start_date: str,
    end_date: str,
    nav: float,
    universe: list,
    directional_trend,
    benchmark_ticker: str,
    label: str,
):
    """Run single backtest configuration."""
    logger.info("Running backtest", label=label)
    
    backtest = WheelHybridBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=nav,
        wheel_pct=0.70,
        directional_pct=0.30,
        directional_trend=directional_trend,
        benchmark_ticker=benchmark_ticker,
    )
    
    data_provider = YahooFinanceProvider()
    results = backtest.run(universe, data_provider)
    
    if not results:
        logger.error("Backtest failed", label=label)
        return None
    
    return results.get("summary", {})


def main():
    parser = argparse.ArgumentParser(
        description="Bake-off: Compare baseline hybrid vs trend-sleeve hybrid vs SPY"
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
        "--universe",
        type=str,
        default="bluechip",
        choices=["bluechip", "expanded", "auto"],
        help="Universe selection (default: bluechip)",
    )
    parser.add_argument(
        "--custom-tickers",
        type=str,
        nargs="+",
        help="Custom universe (overrides --universe)",
    )
    parser.add_argument(
        "--sma-window",
        type=int,
        default=200,
        help="SMA window for trend filter (default: 200)",
    )
    parser.add_argument(
        "--momentum-lookback",
        type=int,
        default=126,
        help="Momentum lookback in days (default: 126 = ~6 months)",
    )
    parser.add_argument(
        "--no-dual-momentum",
        action="store_true",
        help="Disable dual momentum (use only SMA200 trend)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output directory for bake-off results",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default="^SPXTR",
        help="Benchmark ticker (default: ^SPXTR = SPY total return)",
    )
    
    args = parser.parse_args()
    
    # Get universe
    if args.custom_tickers:
        universe = args.custom_tickers
    else:
        universe = get_wheel_universe(args.start, universe_type=args.universe)
    
    logger.info(
        "Starting directional trend bake-off",
        start=args.start,
        end=args.end,
        universe=universe[:5],  # Log first 5
        universe_size=len(universe),
    )
    
    # === Run 1: Baseline Hybrid (no trend overlay) ===
    logger.info("=" * 60)
    logger.info("RUN 1: Baseline Hybrid (no trend overlay)")
    logger.info("=" * 60)
    
    baseline_results = run_backtest(
        start_date=args.start,
        end_date=args.end,
        nav=args.nav,
        universe=universe,
        directional_trend=None,  # No overlay
        benchmark_ticker=args.benchmark,
        label="baseline_hybrid",
    )
    
    if not baseline_results:
        logger.error("Baseline run failed")
        return 1
    
    # === Run 2: Trend Hybrid (with trend overlay) ===
    logger.info("=" * 60)
    logger.info("RUN 2: Trend Hybrid (with directional trend overlay)")
    logger.info("=" * 60)
    
    trend_config = TrendConfig(
        enabled=True,
        sma_window=args.sma_window,
        use_dual_momentum=not args.no_dual_momentum,
        momentum_lookback=args.momentum_lookback,
        cash_when_bearish=True,
    )
    trend_overlay = DirectionalTrendOverlay(trend_config)
    
    trend_results = run_backtest(
        start_date=args.start,
        end_date=args.end,
        nav=args.nav,
        universe=universe,
        directional_trend=trend_overlay,
        benchmark_ticker=args.benchmark,
        label="trend_hybrid",
    )
    
    if not trend_results:
        logger.error("Trend run failed")
        return 1
    
    # === Compare Results ===
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    comparison = {
        "metadata": {
            "start_date": args.start,
            "end_date": args.end,
            "initial_nav": args.nav,
            "universe_type": args.universe,
            "universe_tickers": universe,
            "sma_window": args.sma_window,
            "momentum_lookback": args.momentum_lookback,
            "dual_momentum": not args.no_dual_momentum,
            "strategy": "directional_trend_overlay",
        },
        "baseline_hybrid": baseline_results,
        "trend_hybrid": trend_results,
        "comparison": {
            "abs_return_delta_pct": trend_results["abs_return_pct"] - baseline_results["abs_return_pct"],
            "excess_vs_spy_delta_pct": trend_results["excess_return_pct"] - baseline_results["excess_return_pct"],
            "sharpe_delta": trend_results["sharpe"] - baseline_results["sharpe"],
            "sortino_delta": trend_results["sortino"] - baseline_results["sortino"],
            "max_dd_delta_pct": trend_results["max_drawdown_pct"] - baseline_results["max_drawdown_pct"],
        },
    }
    
    # Save JSON
    json_path = output_dir / "summary.json"
    with open(json_path, "w") as f:
        json.dump(comparison, f, indent=2)
    
    # Print comparison table
    print("\n" + "=" * 90)
    print(f"DIRECTIONAL TREND BAKE-OFF ({args.start} to {args.end})")
    print("=" * 90)
    print(f"Universe: {args.universe} ({len(universe)} tickers)")
    print(f"Trend Filter: SMA{args.sma_window}, Momentum {args.momentum_lookback}d")
    print("=" * 90)
    print()
    
    print(f"{'Metric':<30} {'Baseline':<20} {'Trend Overlay':<20} {'Delta':<15}")
    print("-" * 90)
    
    metrics = [
        ("Absolute Return", "abs_return_pct", "%", True),
        ("SPY Return", "spy_return_pct", "%", False),
        ("Excess vs SPY", "excess_return_pct", "%", True),
        ("Max Drawdown", "max_drawdown_pct", "%", False),
        ("Sharpe Ratio", "sharpe", "", True),
        ("Sortino Ratio", "sortino", "", True),
        ("Alpha (annual)", "alpha_annual_pct", "%", True),
        ("Beta", "beta", "", False),
        ("Hit Rate", "hit_rate_pct", "%", True),
        ("Premium Collected", "premium_collected", "$", True),
    ]
    
    for label, key, unit, show_delta in metrics:
        baseline_val = baseline_results.get(key, 0)
        trend_val = trend_results.get(key, 0)
        delta = trend_val - baseline_val
        
        if unit == "$":
            baseline_str = f"${baseline_val:,.2f}"
            trend_str = f"${trend_val:,.2f}"
            delta_str = f"${delta:+,.2f}" if show_delta else ""
        elif unit == "%":
            baseline_str = f"{baseline_val:+.2f}%"
            trend_str = f"{trend_val:+.2f}%"
            delta_str = f"{delta:+.2f}pp" if show_delta else ""
        else:
            baseline_str = f"{baseline_val:.2f}"
            trend_str = f"{trend_val:.2f}"
            delta_str = f"{delta:+.2f}" if show_delta else ""
        
        print(f"{label:<30} {baseline_str:<20} {trend_str:<20} {delta_str:<15}")
    
    print()
    print("-" * 90)
    
    # Trend statistics
    if "directional_trend" in trend_results:
        trend_stats = trend_results["directional_trend"]
        print(f"\nTrend Overlay Statistics:")
        print(f"  Days risk-on:       {trend_stats['days_risk_on']} ({trend_stats['risk_on_pct']:.1f}%)")
        print(f"  Days risk-off:      {trend_stats['days_risk_off']} ({100 - trend_stats['risk_on_pct']:.1f}%)")
        print(f"  Total signals:      {trend_stats['signal_count']}")
    
    print()
    print("=" * 90)
    print(f"Results saved: {output_dir}/")
    print(f"  - {json_path.name}")
    print("=" * 90)
    
    # Verdict
    print()
    excess_delta = comparison["comparison"]["excess_vs_spy_delta_pct"]
    baseline_excess = baseline_results["excess_return_pct"]
    trend_excess = trend_results["excess_return_pct"]
    
    print(f"Baseline Hybrid: {baseline_excess:+.2f}% vs SPY")
    print(f"Trend Hybrid:    {trend_excess:+.2f}% vs SPY")
    print()
    
    if excess_delta >= 2.0:
        print("✅ Trend overlay improves excess by ≥2pp (strong improvement)")
    elif excess_delta > 0:
        print("⚠️  Trend overlay improves excess but <2pp (marginal)")
    else:
        print("❌ Trend overlay underperforms baseline (no improvement)")
    
    print()
    
    # Sharpe improvement
    sharpe_delta = comparison["comparison"]["sharpe_delta"]
    if sharpe_delta > 0.1:
        print(f"✅ Sharpe improved by {sharpe_delta:+.2f} (better risk-adjusted)")
    elif sharpe_delta > 0:
        print(f"⚠️  Sharpe improved by {sharpe_delta:+.2f} (marginal)")
    else:
        print(f"❌ Sharpe declined by {sharpe_delta:.2f} (worse risk-adjusted)")
    
    print()
    
    # Recommendation
    print("RECOMMENDATION:")
    if excess_delta >= 2.0 or (excess_delta > 0 and sharpe_delta > 0.1):
        print("✅ KEEP - Trend overlay provides material improvement")
        print("   Consider: iterate parameters (SMA window, momentum lookback)")
        print("             expand to relative strength ranking")
    elif trend_excess > baseline_excess and trend_excess > 0:
        print("⚠️  ITERATE - Trend overlay shows promise but needs tuning")
        print("   Consider: test different SMA windows (50/100/200)")
        print("             add regime detection (VIX > 20 → more defensive)")
    else:
        print("❌ ABANDON - Trend overlay does not improve beat-SPY path")
        print("   Consider: alternative approaches (sector rotation, factor tilts)")
    
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
