#!/usr/bin/env python3
"""
Bake-off script for directional crisis overlay.

Runs side-by-side comparison:
1. Baseline: Always-on hybrid (wheel + directional)
2. Crisis Overlay (SPY/BIL): Risk-on holds SPY, risk-off holds BIL
3. Crisis Overlay (SPY/TLT): Risk-on holds SPY, risk-off holds TLT (optional)

Reports citeable bluechip results and honest KEEP/ABANDON recommendation.
"""

import argparse
import json
import sys
from pathlib import Path

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.wheel_hybrid.engine import WheelHybridBacktest
from src.backtesting.wheel_hybrid.universe import get_wheel_universe
from src.backtesting.wheel_hybrid.crisis_overlay import CrisisOverlay, CrisisOverlayConfig
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


def run_arm(
    name: str,
    start_date: str,
    end_date: str,
    initial_nav: float,
    universe: list,
    crisis_config: CrisisOverlayConfig,
    benchmark: str,
) -> dict:
    """Run one backtest arm with given crisis overlay config."""
    
    logger.info("Running arm", name=name, crisis_enabled=crisis_config.enabled)
    
    # Create crisis overlay
    crisis_overlay = CrisisOverlay(crisis_config) if crisis_config.enabled else None
    
    # Initialize backtest
    backtest = WheelHybridBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=initial_nav,
        wheel_pct=0.70,
        directional_pct=0.30,
        crisis_overlay=crisis_overlay,
        benchmark_ticker=benchmark,
    )
    
    # Run with Yahoo Finance provider
    data_provider = YahooFinanceProvider()
    
    results = backtest.run(universe, data_provider)
    
    if not results:
        logger.error("Arm failed", name=name)
        return {}
    
    return results.get("summary", {})


def print_comparison(baseline: dict, overlay_bil: dict, overlay_tlt: dict = None):
    """Print side-by-side comparison table."""
    
    print("\n" + "=" * 80)
    print("DIRECTIONAL CRISIS OVERLAY BAKE-OFF RESULTS")
    print("=" * 80)
    print()
    
    if overlay_tlt:
        print(f"{'Metric':<25} {'Baseline':<20} {'Crisis (SPY/BIL)':<20} {'Crisis (SPY/TLT)':<20}")
        print("-" * 80)
    else:
        print(f"{'Metric':<25} {'Baseline':<20} {'Crisis (SPY/BIL)':<20}")
        print("-" * 60)
    
    # Key metrics
    metrics = [
        ("Absolute Return", "abs_return_pct", "%", True),
        ("SPY Return", "spy_return_pct", "%", True),
        ("Excess vs SPY", "excess_return_pct", "pp", True),
        ("Max Drawdown", "max_drawdown_pct", "%", False),
        ("Sharpe Ratio", "sharpe", "", False),
        ("Sortino Ratio", "sortino", "", False),
        ("Beta", "beta", "", False),
        ("Alpha (annual)", "alpha_annual_pct", "%", True),
        ("Turnover", "turnover", "x", False),
        ("Premium Collected", "premium_collected", "$", False),
    ]
    
    for label, key, unit, show_sign in metrics:
        baseline_val = baseline.get(key, 0)
        overlay_bil_val = overlay_bil.get(key, 0)
        
        if unit == "%":
            baseline_str = f"{baseline_val:+.1f}%" if show_sign else f"{baseline_val:.1f}%"
            overlay_bil_str = f"{overlay_bil_val:+.1f}%" if show_sign else f"{overlay_bil_val:.1f}%"
        elif unit == "$":
            baseline_str = f"${baseline_val:,.0f}"
            overlay_bil_str = f"${overlay_bil_val:,.0f}"
        elif unit == "pp":
            baseline_str = f"{baseline_val:+.1f}pp"
            overlay_bil_str = f"{overlay_bil_val:+.1f}pp"
        else:
            baseline_str = f"{baseline_val:.2f}{unit}"
            overlay_bil_str = f"{overlay_bil_val:.2f}{unit}"
        
        if overlay_tlt:
            overlay_tlt_val = overlay_tlt.get(key, 0)
            if unit == "%":
                overlay_tlt_str = f"{overlay_tlt_val:+.1f}%" if show_sign else f"{overlay_tlt_val:.1f}%"
            elif unit == "$":
                overlay_tlt_str = f"${overlay_tlt_val:,.0f}"
            elif unit == "pp":
                overlay_tlt_str = f"{overlay_tlt_val:+.1f}pp"
            else:
                overlay_tlt_str = f"{overlay_tlt_val:.2f}{unit}"
            
            print(f"{label:<25} {baseline_str:<20} {overlay_bil_str:<20} {overlay_tlt_str:<20}")
        else:
            print(f"{label:<25} {baseline_str:<20} {overlay_bil_str:<20}")
    
    print()
    
    # Delta vs baseline
    print("DELTA VS BASELINE:")
    print("-" * 60)
    
    delta_bil = overlay_bil.get("abs_return_pct", 0) - baseline.get("abs_return_pct", 0)
    delta_bil_excess = overlay_bil.get("excess_return_pct", 0) - baseline.get("excess_return_pct", 0)
    
    print(f"Crisis (SPY/BIL) vs Baseline:")
    print(f"  Absolute Return: {delta_bil:+.1f}pp")
    print(f"  Excess vs SPY:   {delta_bil_excess:+.1f}pp")
    
    if overlay_tlt:
        delta_tlt = overlay_tlt.get("abs_return_pct", 0) - baseline.get("abs_return_pct", 0)
        delta_tlt_excess = overlay_tlt.get("excess_return_pct", 0) - baseline.get("excess_return_pct", 0)
        
        print(f"\nCrisis (SPY/TLT) vs Baseline:")
        print(f"  Absolute Return: {delta_tlt:+.1f}pp")
        print(f"  Excess vs SPY:   {delta_tlt_excess:+.1f}pp")
    
    print()
    
    # Recommendation
    print("=" * 80)
    print("RECOMMENDATION:")
    print("=" * 80)
    
    hurdle_met = delta_bil >= 2.0  # ≥2pp improvement
    
    if hurdle_met:
        print("✅ KEEP: Crisis overlay (SPY/BIL) beats baseline by ≥2pp")
        print(f"   Delta: {delta_bil:+.1f}pp absolute, {delta_bil_excess:+.1f}pp vs SPY")
    else:
        print("❌ ABANDON: Crisis overlay does NOT beat baseline by ≥2pp")
        print(f"   Delta: {delta_bil:+.1f}pp absolute, {delta_bil_excess:+.1f}pp vs SPY")
        print(f"   Required: ≥+2.0pp, achieved: {delta_bil:+.1f}pp")
    
    if overlay_tlt and delta_tlt > delta_bil:
        print(f"\n💡 NOTE: SPY/TLT variant performs better ({delta_tlt:+.1f}pp vs {delta_bil:+.1f}pp)")
    
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Run directional crisis overlay bake-off (baseline vs SPY/BIL vs SPY/TLT)"
    )
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--nav", type=float, default=10000.0, help="Initial NAV (default: 10000)")
    parser.add_argument(
        "--universe",
        type=str,
        default="bluechip",
        choices=["bluechip", "expanded"],
        help="Universe: bluechip (citeable) or expanded (non-citeable)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output directory for results (e.g., docs/backtest_results/directional_crisis_overlay/2020_2024_bluechip)",
    )
    parser.add_argument(
        "--include-tlt",
        action="store_true",
        help="Run optional SPY/TLT variant (risk-off parks in TLT instead of BIL)",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default="^SPXTR",
        help="Benchmark ticker (default: ^SPXTR = SPY total return)",
    )
    
    args = parser.parse_args()
    
    # Get universe
    universe = get_wheel_universe(args.start, universe_type=args.universe)
    
    # Add SPY, BIL, TLT to universe for crisis overlay
    extended_universe = list(set(universe + ["SPY", "BIL", "TLT"]))
    
    logger.info(
        "Starting crisis overlay bake-off",
        start=args.start,
        end=args.end,
        nav=args.nav,
        universe_type=args.universe,
        universe_size=len(universe),
    )
    
    # Run baseline (no crisis overlay)
    logger.info("=" * 60)
    logger.info("ARM 1: BASELINE (Always-on hybrid)")
    logger.info("=" * 60)
    
    baseline_config = CrisisOverlayConfig(enabled=False)
    baseline = run_arm(
        "Baseline",
        args.start,
        args.end,
        args.nav,
        extended_universe,
        baseline_config,
        args.benchmark,
    )
    
    if not baseline:
        logger.error("Baseline arm failed, cannot continue")
        return 1
    
    # Validate baseline matches expected results (citeable)
    if args.universe == "bluechip" and args.start == "2020-01-01" and args.end == "2024-12-31":
        expected_return = 55.0
        actual_return = baseline.get("abs_return_pct", 0)
        tolerance = 2.0  # Allow 2% variance
        
        if abs(actual_return - expected_return) > tolerance:
            logger.error(
                "Baseline validation FAILED",
                expected=expected_return,
                actual=actual_return,
                delta=actual_return - expected_return,
            )
            print("\n" + "=" * 80)
            print("❌ BASELINE VALIDATION FAILED")
            print("=" * 80)
            print(f"Expected: ~{expected_return:.1f}% (citeable bluechip 2020-2024)")
            print(f"Actual:   {actual_return:.1f}%")
            print(f"Delta:    {actual_return - expected_return:+.1f}pp")
            print("\nThis indicates a problem with the simulation. Fix before proceeding.")
            print("=" * 80)
            return 1
        else:
            logger.info(
                "✅ Baseline validated",
                expected=expected_return,
                actual=actual_return,
                delta=actual_return - expected_return,
            )
    
    # Run crisis overlay (SPY/BIL)
    logger.info("=" * 60)
    logger.info("ARM 2: CRISIS OVERLAY (SPY/BIL)")
    logger.info("=" * 60)
    
    crisis_bil_config = CrisisOverlayConfig(
        enabled=True,
        sma_window=200,
        rebalance_mode="monthly",
        risk_on_asset="SPY",
        risk_off_asset="BIL",
        hysteresis_pct=0.0,
    )
    
    overlay_bil = run_arm(
        "Crisis (SPY/BIL)",
        args.start,
        args.end,
        args.nav,
        extended_universe,
        crisis_bil_config,
        args.benchmark,
    )
    
    if not overlay_bil:
        logger.error("Crisis overlay (BIL) arm failed")
        return 1
    
    # Run crisis overlay (SPY/TLT) if requested
    overlay_tlt = None
    if args.include_tlt:
        logger.info("=" * 60)
        logger.info("ARM 3: CRISIS OVERLAY (SPY/TLT)")
        logger.info("=" * 60)
        
        crisis_tlt_config = CrisisOverlayConfig(
            enabled=True,
            sma_window=200,
            rebalance_mode="monthly",
            risk_on_asset="SPY",
            risk_off_asset="TLT",
            hysteresis_pct=0.0,
        )
        
        overlay_tlt = run_arm(
            "Crisis (SPY/TLT)",
            args.start,
            args.end,
            args.nav,
            extended_universe,
            crisis_tlt_config,
            args.benchmark,
        )
    
    # Print comparison
    print_comparison(baseline, overlay_bil, overlay_tlt)
    
    # Save results
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save summary JSON
    summary = {
        "start_date": args.start,
        "end_date": args.end,
        "initial_nav": args.nav,
        "universe": args.universe,
        "benchmark": args.benchmark,
        "baseline": baseline,
        "crisis_spy_bil": overlay_bil,
    }
    
    if overlay_tlt:
        summary["crisis_spy_tlt"] = overlay_tlt
    
    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    # Create README
    readme_content = f"""# Directional Crisis Overlay Bake-Off Results

**Universe**: {args.universe.upper()}  
**Period**: {args.start} to {args.end}  
**Initial NAV**: ${args.nav:,.0f}  
**Benchmark**: {args.benchmark}

## Summary

| Metric | Baseline | Crisis (SPY/BIL) | Delta |
|--------|----------|------------------|-------|
| Absolute Return | {baseline.get('abs_return_pct', 0):+.1f}% | {overlay_bil.get('abs_return_pct', 0):+.1f}% | {overlay_bil.get('abs_return_pct', 0) - baseline.get('abs_return_pct', 0):+.1f}pp |
| SPY Return | {baseline.get('spy_return_pct', 0):+.1f}% | {overlay_bil.get('spy_return_pct', 0):+.1f}% | — |
| Excess vs SPY | {baseline.get('excess_return_pct', 0):+.1f}pp | {overlay_bil.get('excess_return_pct', 0):+.1f}pp | {overlay_bil.get('excess_return_pct', 0) - baseline.get('excess_return_pct', 0):+.1f}pp |
| Max Drawdown | {baseline.get('max_drawdown_pct', 0):.1f}% | {overlay_bil.get('max_drawdown_pct', 0):.1f}% | {overlay_bil.get('max_drawdown_pct', 0) - baseline.get('max_drawdown_pct', 0):+.1f}pp |
| Sharpe | {baseline.get('sharpe', 0):.2f} | {overlay_bil.get('sharpe', 0):.2f} | {overlay_bil.get('sharpe', 0) - baseline.get('sharpe', 0):+.2f} |
| Turnover | {baseline.get('turnover', 0):.2f}x | {overlay_bil.get('turnover', 0):.2f}x | {overlay_bil.get('turnover', 0) - baseline.get('turnover', 0):+.2f}x |

## Recommendation

"""
    
    delta_bil = overlay_bil.get("abs_return_pct", 0) - baseline.get("abs_return_pct", 0)
    
    if delta_bil >= 2.0:
        readme_content += f"✅ **KEEP**: Crisis overlay beats baseline by {delta_bil:+.1f}pp (≥2pp hurdle met)\n"
    else:
        readme_content += f"❌ **ABANDON**: Crisis overlay underperforms or does not meet +2pp hurdle ({delta_bil:+.1f}pp)\n"
    
    readme_content += "\n## Reproduce\n\n```bash\n"
    readme_content += f"python3 scripts/run_directional_crisis_bakeoff.py \\\n"
    readme_content += f"  --start {args.start} \\\n"
    readme_content += f"  --end {args.end} \\\n"
    readme_content += f"  --universe {args.universe} \\\n"
    readme_content += f"  --nav {args.nav:.0f} \\\n"
    readme_content += f"  --out {args.out}"
    
    if args.include_tlt:
        readme_content += " \\\n  --include-tlt"
    
    readme_content += "\n```\n"
    
    with open(output_dir / "README.md", "w") as f:
        f.write(readme_content)
    
    logger.info("Results saved", output_dir=str(output_dir))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
