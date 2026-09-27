#!/usr/bin/env python3
"""
Sleeve Weight Grid: Test different growth/ballast splits for income drip strategy.

Goal 2: Test 90/10, 80/20, 70/30 sleeve weights on fixed Arm 2 delta-rebal mechanics.
KEEP bar: Sharpe improves on BOTH 2020-24 and 2010-24 vs 80/20 baseline.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.income_drip.engine import IncomeDripBacktest
from src.backtesting.income_drip.data_cache import DataCache
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()

# Test windows
WINDOWS = {
    "2020_2024": ("2020-01-01", "2024-12-31"),
    "2010_2024": ("2010-01-01", "2024-12-31"),
    "2022_stress": ("2022-01-01", "2022-12-31"),
    "2000_2002_stress": ("2000-01-01", "2002-12-31"),
}

# Sleeve weight configurations
SLEEVE_WEIGHTS = [
    (0.90, 0.10, "90_10"),
    (0.80, 0.20, "80_20"),  # Baseline
    (0.70, 0.30, "70_30"),
]


def run_sleeve_weight_test(
    growth_weight: float,
    ballast_weight: float,
    label: str,
    window_name: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
    initial_nav: float = 10_000.0,
    cache = None,
) -> Dict:
    """Run income drip backtest with specified sleeve weights."""
    logger.info(
        f"Running sleeve weight test",
        label=label,
        window=window_name,
        growth_pct=f"{growth_weight*100:.0f}%",
        ballast_pct=f"{ballast_weight*100:.0f}%",
    )
    
    backtest = IncomeDripBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=initial_nav,
        growth_weight=growth_weight,
        ballast_weight=ballast_weight,
        rebalance_frequency="quarterly",
        trading_cost_pct=0.0007,  # 7 bps
        benchmark_ticker="SPY",  # Use SPY (^SPXTR often has data issues)
        cc_enabled=False,  # No CCs for sleeve weight grid
    )
    
    data_provider = YahooFinanceProvider()
    
    try:
        results = backtest.run(
            data_provider,
            arm_name=f"sleeve_{label}_{window_name}",
            cache=cache,
        )
        
        if not results:
            logger.error("Backtest failed", label=label, window=window_name)
            return {}
        
        # Save results
        window_output_dir = output_dir / window_name
        backtest.save_results(window_output_dir, arm_name=f"sleeve_{label}")
        
        return results.get("summary", {})
        
    except Exception as e:
        logger.error("Backtest failed with exception", label=label, window=window_name, error=str(e))
        import traceback
        traceback.print_exc()
        return {}


def generate_sleeve_weight_report(results: Dict, output_dir: Path):
    """Generate sleeve weight grid comparison report."""
    
    report = []
    report.append("# Sleeve Weight Grid Results")
    report.append("")
    report.append("**Goal:** Find optimal growth/ballast split using fixed delta-rebalancing mechanics.")
    report.append("")
    report.append("**Baseline:** 80/20 (80% momentum growth / 20% dividend ballast)")
    report.append("")
    report.append("**KEEP Bar:** Sharpe improves on BOTH primary windows (2020-24 and 2010-24) vs 80/20 baseline,")
    report.append("without disastrous DD blow-up (max DD worse by >10pp with only tiny Sharpe gain).")
    report.append("")
    report.append("---")
    report.append("")
    
    # Get baseline (80/20) results for comparison
    baseline_2020 = results.get("80_20", {}).get("2020_2024", {})
    baseline_2010 = results.get("80_20", {}).get("2010_2024", {})
    
    baseline_sharpe_2020 = baseline_2020.get("sharpe", 0)
    baseline_sharpe_2010 = baseline_2010.get("sharpe", 0)
    baseline_dd_2020 = baseline_2020.get("max_drawdown_pct", 0)
    baseline_dd_2010 = baseline_2010.get("max_drawdown_pct", 0)
    
    report.append("## Baseline (80/20)")
    report.append("")
    report.append(f"- **2020-2024:** Sharpe {baseline_sharpe_2020:.3f}, Max DD {baseline_dd_2020:.2f}%")
    report.append(f"- **2010-2024:** Sharpe {baseline_sharpe_2010:.3f}, Max DD {baseline_dd_2010:.2f}%")
    report.append("")
    report.append("---")
    report.append("")
    
    # Summary table
    report.append("## Comparison Table")
    report.append("")
    report.append("| Split | Window | Sharpe | Ann Ret | Max DD | vs 80/20 Sharpe | vs 80/20 DD | Verdict |")
    report.append("|-------|--------|--------|---------|--------|-----------------|-------------|---------|")
    
    for growth, ballast, label in SLEEVE_WEIGHTS:
        label_results = results.get(label, {})
        
        for window_name, _ in WINDOWS.items():
            metrics = label_results.get(window_name, {})
            
            if not metrics:
                report.append(f"| {label} | {window_name} | N/A | N/A | N/A | N/A | N/A | NO DATA |")
                continue
            
            sharpe = metrics.get("sharpe", 0)
            ann_ret = metrics.get("ann_return_pct", 0)
            max_dd = metrics.get("max_drawdown_pct", 0)
            
            # Compare to baseline
            if window_name == "2020_2024":
                sharpe_delta = sharpe - baseline_sharpe_2020
                dd_delta = max_dd - baseline_dd_2020
            elif window_name == "2010_2024":
                sharpe_delta = sharpe - baseline_sharpe_2010
                dd_delta = max_dd - baseline_dd_2010
            else:
                sharpe_delta = 0
                dd_delta = 0
            
            is_primary = window_name in ["2020_2024", "2010_2024"]
            
            # Determine verdict for primary windows
            if is_primary:
                sharpe_str = f"{sharpe_delta:+.3f}"
                dd_str = f"{dd_delta:+.2f}pp"
                
                if label == "80_20":
                    verdict = "BASELINE"
                else:
                    verdict = "✓" if sharpe_delta >= 0 else "✗"
            else:
                sharpe_str = f"{sharpe_delta:+.3f}" if sharpe_delta != 0 else "-"
                dd_str = f"{dd_delta:+.2f}pp" if dd_delta != 0 else "-"
                verdict = "INFO"
            
            report.append(
                f"| {int(growth*100)}/{int(ballast*100)} | {window_name} | "
                f"{sharpe:.3f} | {ann_ret:.2f}% | {max_dd:.2f}% | "
                f"{sharpe_str} | {dd_str} | {verdict} |"
            )
    
    report.append("")
    report.append("---")
    report.append("")
    
    # KEEP/ABANDON per sleeve weight
    report.append("## KEEP / ABANDON Verdict")
    report.append("")
    
    for growth, ballast, label in SLEEVE_WEIGHTS:
        if label == "80_20":
            continue  # Skip baseline
        
        label_results = results.get(label, {})
        metrics_2020 = label_results.get("2020_2024", {})
        metrics_2010 = label_results.get("2010_2024", {})
        
        if not metrics_2020 or not metrics_2010:
            report.append(f"### {int(growth*100)}/{int(ballast*100)}: INSUFFICIENT DATA")
            report.append("")
            continue
        
        sharpe_2020 = metrics_2020.get("sharpe", 0)
        sharpe_2010 = metrics_2010.get("sharpe", 0)
        dd_2020 = metrics_2010.get("max_drawdown_pct", 0)
        dd_2010 = metrics_2010.get("max_drawdown_pct", 0)
        
        sharpe_improves_both = (sharpe_2020 >= baseline_sharpe_2020 and sharpe_2010 >= baseline_sharpe_2010)
        
        dd_delta_2020 = dd_2020 - baseline_dd_2020
        dd_delta_2010 = dd_2010 - baseline_dd_2010
        dd_blowup = (dd_delta_2020 < -10.0 or dd_delta_2010 < -10.0)  # Worse by >10pp
        
        sharpe_delta_2020 = sharpe_2020 - baseline_sharpe_2020
        sharpe_delta_2010 = sharpe_2010 - baseline_sharpe_2010
        tiny_sharpe_gain = (sharpe_delta_2020 < 0.05 and sharpe_delta_2010 < 0.05)
        
        if sharpe_improves_both and not (dd_blowup and tiny_sharpe_gain):
            verdict = f"✓ KEEP - Sharpe improves on both primary windows ({sharpe_delta_2020:+.3f} / {sharpe_delta_2010:+.3f})"
        else:
            if not sharpe_improves_both:
                reason = "Sharpe does not improve on both primary windows"
            else:
                reason = "DD blowup (>10pp worse) with only tiny Sharpe gain"
            verdict = f"✗ ABANDON - {reason}"
        
        report.append(f"### {int(growth*100)}/{int(ballast*100)} (Growth/Ballast)")
        report.append("")
        report.append(f"**2020-2024:** Sharpe {sharpe_2020:.3f} ({sharpe_delta_2020:+.3f} vs 80/20), DD {dd_2020:.2f}% ({dd_delta_2020:+.2f}pp)")
        report.append(f"**2010-2024:** Sharpe {sharpe_2010:.3f} ({sharpe_delta_2010:+.3f} vs 80/20), DD {dd_2010:.2f}% ({dd_delta_2010:+.2f}pp)")
        report.append("")
        report.append(f"**Verdict:** {verdict}")
        report.append("")
    
    report.append("---")
    report.append("")
    
    # Final recommendation
    report.append("## Final Recommendation")
    report.append("")
    
    keepers = []
    for growth, ballast, label in SLEEVE_WEIGHTS:
        if label == "80_20":
            continue
        
        label_results = results.get(label, {})
        metrics_2020 = label_results.get("2020_2024", {})
        metrics_2010 = label_results.get("2010_2024", {})
        
        if not metrics_2020 or not metrics_2010:
            continue
        
        sharpe_2020 = metrics_2020.get("sharpe", 0)
        sharpe_2010 = metrics_2010.get("sharpe", 0)
        
        sharpe_improves_both = (sharpe_2020 >= baseline_sharpe_2020 and sharpe_2010 >= baseline_sharpe_2010)
        
        if sharpe_improves_both:
            keepers.append((label, sharpe_2020 + sharpe_2010))
    
    if keepers:
        # Sort by total Sharpe
        keepers.sort(key=lambda x: x[1], reverse=True)
        winner_label, _ = keepers[0]
        
        growth, ballast, _ = [(g, b, l) for g, b, l in SLEEVE_WEIGHTS if l == winner_label][0]
        
        report.append(f"**Winner:** {int(growth*100)}/{int(ballast*100)} split (Sharpe improves on both primary windows)")
        report.append("")
        report.append(f"Proceed to Goal 3 (vol-target overlay) using {int(growth*100)}/{int(ballast*100)} sleeve weights.")
    else:
        report.append("**Winner:** 80/20 (baseline) - no alternative improves Sharpe on both primary windows")
        report.append("")
        report.append("Proceed to Goal 3 (vol-target overlay) using 80/20 sleeve weights.")
    
    report.append("")
    
    # Write report
    report_path = output_dir / "SLEEVE_WEIGHT_GRID.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report))
    
    logger.info("Sleeve weight grid report generated", path=str(report_path))


def main():
    parser = argparse.ArgumentParser(
        description="Test sleeve weight grid for income drip strategy"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="results/income_drip_sharpe_v1/sleeve_grid",
        help="Output directory (default: results/income_drip_sharpe_v1/sleeve_grid)",
    )
    parser.add_argument(
        "--window",
        type=str,
        choices=list(WINDOWS.keys()) + ["all"],
        default="all",
        help="Run specific window or all (default: all)",
    )
    
    args = parser.parse_args()
    
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    windows_to_run = list(WINDOWS.keys()) if args.window == "all" else [args.window]
    
    logger.info(
        "Starting sleeve weight grid tests",
        weights=[(f"{int(g*100)}/{int(b*100)}", l) for g, b, l in SLEEVE_WEIGHTS],
        windows=windows_to_run,
        output_dir=str(output_dir),
    )
    
    # Initialize data cache (reuse audit cache if it exists)
    cache_dir = Path("results/income_drip_sharpe_v1/audit_before_after/.data_cache")
    if not cache_dir.exists():
        cache_dir = output_dir / ".data_cache"
    
    cache = DataCache(cache_dir=str(cache_dir))
    logger.info("Initialized data cache", cache_dir=str(cache_dir))
    
    # Run all sleeve weight tests
    all_results = {}
    
    for growth, ballast, label in SLEEVE_WEIGHTS:
        label_results = {}
        
        for window_name in windows_to_run:
            start_date, end_date = WINDOWS[window_name]
            
            metrics = run_sleeve_weight_test(
                growth_weight=growth,
                ballast_weight=ballast,
                label=label,
                window_name=window_name,
                start_date=start_date,
                end_date=end_date,
                output_dir=output_dir,
                initial_nav=10_000.0,
                cache=cache,
            )
            
            label_results[window_name] = metrics
        
        all_results[label] = label_results
    
    # Save consolidated results
    consolidated_path = output_dir / "consolidated_sleeve_grid.json"
    with open(consolidated_path, "w") as f:
        json.dump(all_results, f, indent=2)
    
    logger.info("Consolidated results saved", path=str(consolidated_path))
    
    # Generate report
    generate_sleeve_weight_report(all_results, output_dir)
    
    print("\n" + "=" * 80)
    print("Sleeve Weight Grid Complete")
    print("=" * 80)
    print(f"Results: {output_dir}/")
    print(f"Report: {output_dir}/SLEEVE_WEIGHT_GRID.md")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
