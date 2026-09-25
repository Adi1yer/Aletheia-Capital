#!/usr/bin/env python3
"""
Bake-off: Compare wheel strategy with edge-gating vs legacy always-on.

Runs backtest twice on same window/universe:
1. Legacy (--edge-mode off): Always write CC/CSP, no IV gating
2. Gated (--edge-mode file): Write only when VRP > threshold

Outputs side-by-side comparison table + JSON results.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.wheel_hybrid.engine import WheelHybridBacktest
from src.backtesting.wheel_hybrid.universe import get_wheel_universe
from src.backtesting.wheel_hybrid.iv_provider import CsvIVProvider, NullIVProvider
from src.backtesting.wheel_hybrid.vix_iv_provider import VixIVProvider
from src.backtesting.wheel_hybrid.edge_gate import EdgeGate, EdgeGateConfig
from src.backtesting.wheel_hybrid.regime import RegimeDetector, RegimeConfig
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


def run_backtest(
    start_date: str,
    end_date: str,
    nav: float,
    universe: list,
    iv_provider,
    edge_gate,
    regime_detector,
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
        iv_provider=iv_provider,
        edge_gate=edge_gate,
        regime_detector=regime_detector,
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
        description="Bake-off: Compare edge-gated vs always-on wheel strategy"
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
        "--iv-csv",
        type=str,
        help="Path to IV CSV for gated run (if not provided, uses synthetic IV labeled RESEARCH-ONLY)",
    )
    parser.add_argument(
        "--iv-source",
        type=str,
        choices=["synthetic", "csv", "vix"],
        default="synthetic",
        help="IV source: synthetic (research-only), csv (from file), vix (free CBOE regime signal)",
    )
    parser.add_argument(
        "--min-vrp",
        type=float,
        default=0.10,
        help="Minimum VRP threshold for gated run (default: 0.10 = 10%%)",
    )
    parser.add_argument(
        "--min-iv-rank",
        type=float,
        help="Minimum IV rank for gated run (optional)",
    )
    parser.add_argument(
        "--enable-regime",
        action="store_true",
        help="Enable regime detection in gated run",
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
        help="Benchmark ticker (default: ^SPXTR = SPY total return, fallback to SPY if unavailable)",
    )
    
    args = parser.parse_args()
    
    # Get universe
    if args.custom_tickers:
        universe = args.custom_tickers
    else:
        universe = get_wheel_universe(args.start, universe_type=args.universe)
    
    logger.info(
        "Starting VRP bake-off",
        start=args.start,
        end=args.end,
        universe=universe,
        iv_csv=args.iv_csv,
    )
    
    # === Run 1: Legacy (always-on) ===
    logger.info("=" * 60)
    logger.info("RUN 1: Legacy (always-on, no edge gating)")
    logger.info("=" * 60)
    
    legacy_results = run_backtest(
        start_date=args.start,
        end_date=args.end,
        nav=args.nav,
        universe=universe,
        iv_provider=None,
        edge_gate=None,
        regime_detector=None,
        benchmark_ticker=args.benchmark,
        label="legacy_always_on",
    )
    
    if not legacy_results:
        logger.error("Legacy run failed")
        return 1
    
    # === Run 2: Gated (with IV) ===
    logger.info("=" * 60)
    logger.info("RUN 2: Gated (IV edge filter)")
    logger.info("=" * 60)
    
    # Select IV provider based on source
    if args.iv_source == "vix":
        logger.info("Using FREE VIX-based IV provider (REGIME SIGNAL)")
        iv_provider = VixIVProvider()
        is_synthetic = False
        edge_label = "VIX-gated (FREE regime signal)"
    elif args.iv_csv or args.iv_source == "csv":
        if not args.iv_csv:
            logger.error("--iv-source csv requires --iv-csv path")
            return 1
        logger.info("Using market IV from CSV", path=args.iv_csv)
        iv_provider = CsvIVProvider(args.iv_csv)
        is_synthetic = False
        edge_label = "CSV-gated (market IV)"
    else:  # synthetic
        logger.warning("Using synthetic IV (RESEARCH-ONLY)")
        logger.error(
            "Bake-off with --iv-source synthetic requires real implementation. "
            "Use --iv-source vix (free) or --iv-csv (market data)"
        )
        return 1
    
    gate_config = EdgeGateConfig(
        enabled=True,
        min_vrp=args.min_vrp,
        min_iv_rank=args.min_iv_rank,
        fail_closed_when_no_iv=True,
    )
    edge_gate = EdgeGate(gate_config, iv_provider)
    
    regime_detector = None
    if args.enable_regime:
        regime_config = RegimeConfig(enabled=True)
        regime_detector = RegimeDetector(regime_config, iv_provider)
    
    gated_results = run_backtest(
        start_date=args.start,
        end_date=args.end,
        nav=args.nav,
        universe=universe,
        iv_provider=iv_provider,
        edge_gate=edge_gate,
        regime_detector=regime_detector,
        benchmark_ticker=args.benchmark,
        label=edge_label,
    )
    
    if not gated_results:
        logger.error("Gated run failed")
        return 1
    
    # === Compare Results ===
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine label based on IV source
    if args.iv_source == "vix":
        iv_source_label = "vix_free_regime"
    elif args.iv_source == "csv":
        iv_source_label = "market_iv_csv"
    else:
        iv_source_label = "synthetic_iv_research_only"
        is_synthetic = True
    
    comparison = {
        "metadata": {
            "start_date": args.start,
            "end_date": args.end,
            "initial_nav": args.nav,
            "universe_type": args.universe,
            "universe_tickers": universe,
            "iv_source": iv_source_label,
            "min_vrp": args.min_vrp,
            "min_iv_rank": args.min_iv_rank,
            "regime_enabled": args.enable_regime,
            "label": "research_only_synthetic_iv" if is_synthetic else "market_iv_validation",
        },
        "legacy_always_on": legacy_results,
        "gated_edge_on": gated_results,
        "comparison": {
            "abs_return_delta_pct": gated_results["abs_return_pct"] - legacy_results["abs_return_pct"],
            "excess_vs_spy_delta_pct": gated_results["excess_return_pct"] - legacy_results["excess_return_pct"],
            "sharpe_delta": gated_results["sharpe"] - legacy_results["sharpe"],
            "max_dd_delta_pct": gated_results["max_drawdown_pct"] - legacy_results["max_drawdown_pct"],
        },
    }
    
    # Save JSON
    json_path = output_dir / f"bakeoff_{args.start}_{args.end}.json"
    with open(json_path, "w") as f:
        json.dump(comparison, f, indent=2)
    
    # Print comparison table
    print("\n" + "=" * 80)
    print(f"VRP BAKE-OFF RESULTS ({args.start} to {args.end})")
    print("=" * 80)
    print(f"Universe: {args.universe} ({len(universe)} tickers)")
    print(f"IV Source: {iv_source_label}")
    if args.iv_source == "vix":
        print("ℹ️  Using FREE VIX (REGIME SIGNAL, index-level vol)")
    if is_synthetic:
        print("⚠️  WARNING: Using SYNTHETIC IV (RESEARCH-ONLY)")
    print("=" * 80)
    print()
    
    print(f"{'Metric':<30} {'Legacy (Off)':<20} {'Gated (On)':<20} {'Delta':<15}")
    print("-" * 85)
    
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
        legacy_val = legacy_results.get(key, 0)
        gated_val = gated_results.get(key, 0)
        delta = gated_val - legacy_val
        
        if unit == "$":
            legacy_str = f"${legacy_val:,.2f}"
            gated_str = f"${gated_val:,.2f}"
            delta_str = f"${delta:+,.2f}" if show_delta else ""
        elif unit == "%":
            legacy_str = f"{legacy_val:+.2f}%"
            gated_str = f"{gated_val:+.2f}%"
            delta_str = f"{delta:+.2f}%" if show_delta else ""
        else:
            legacy_str = f"{legacy_val:.2f}"
            gated_str = f"{gated_val:.2f}"
            delta_str = f"{delta:+.2f}" if show_delta else ""
        
        print(f"{label:<30} {legacy_str:<20} {gated_str:<20} {delta_str:<15}")
    
    print()
    print("-" * 85)
    
    # Gate statistics
    if hasattr(edge_gate, "writes_allowed"):
        total_gate_checks = (
            edge_gate.writes_allowed +
            edge_gate.writes_blocked_vrp +
            edge_gate.writes_blocked_iv_rank +
            edge_gate.writes_blocked_no_iv
        )
        if total_gate_checks > 0:
            block_rate = (
                (edge_gate.writes_blocked_vrp + edge_gate.writes_blocked_iv_rank + edge_gate.writes_blocked_no_iv)
                / total_gate_checks * 100
            )
            print(f"\nGate Statistics:")
            print(f"  Writes allowed:      {edge_gate.writes_allowed}")
            print(f"  Blocked (low VRP):   {edge_gate.writes_blocked_vrp}")
            print(f"  Blocked (low IV rank): {edge_gate.writes_blocked_iv_rank}")
            print(f"  Blocked (no IV):     {edge_gate.writes_blocked_no_iv}")
            print(f"  Block rate:          {block_rate:.1f}%")
    
    # Regime statistics (if enabled)
    if regime_detector and hasattr(regime_detector, "regime_day_counts"):
        print(f"\nRegime Day Counts:")
        for regime, days in regime_detector.regime_day_counts.items():
            print(f"  {regime}: {days} days")
    
    print()
    print("=" * 80)
    print(f"Results saved: {output_dir}/")
    print(f"  - {json_path.name}")
    print("=" * 80)
    
    # Verdict
    print()
    if comparison["comparison"]["excess_vs_spy_delta_pct"] > 2.0:
        print("✅ Gated strategy outperforms legacy by >2% excess (edge detected)")
    elif comparison["comparison"]["excess_vs_spy_delta_pct"] > 0:
        print("⚠️  Gated strategy outperforms legacy, but margin <2% (weak edge)")
    else:
        print("❌ Gated strategy underperforms legacy (no edge detected)")
    
    if is_synthetic:
        print()
        print("⚠️  WARNING: Results based on SYNTHETIC IV (RESEARCH-ONLY)")
        print("   Do NOT use for production validation or beat-SPY claims")
    
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
