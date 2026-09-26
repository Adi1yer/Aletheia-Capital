#!/usr/bin/env python3
"""Run growth/quality v1 bake-offs vs SPY across all arms and windows."""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.growth_quality.engine import GrowthQualityBacktest
from src.backtesting.growth_quality.universe import get_universe_for_arm
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


# Test windows (as specified in research brief)
WINDOWS = {
    "2020_2024": ("2020-01-01", "2024-12-31"),      # Primary window 1
    "2010_2024": ("2010-01-01", "2024-12-31"),      # Primary window 2
    "2022_stress": ("2022-01-01", "2022-12-31"),    # Stress test (growth crash)
    "2000_2002_stress": ("2000-01-01", "2002-12-31"),  # Stress test (dot-com crash)
}


# Strategy arms
ARMS = {
    "arm_a_qqq": {
        "name": "Arm A: QQQ Buy-and-Hold",
        "description": "Nasdaq-100 ETF (QQQ) - transparent concentration baseline",
    },
    "arm_b_equal_weight": {
        "name": "Arm B: Equal-Weight Quality Mega-Caps",
        "description": "Equal-weight top 15 liquid mega/quality names",
    },
    "arm_c_quality_screen": {
        "name": "Arm C: Quality-Screened Large-Cap",
        "description": "Simple quality screen on liquid large-cap universe (top 30)",
    },
}


def run_single_backtest(
    arm: str,
    window_name: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
    initial_nav: float = 10_000.0,
) -> Dict:
    """Run a single backtest for one arm and window."""
    
    logger.info(
        "Running backtest",
        arm=arm,
        window=window_name,
        start=start_date,
        end=end_date,
    )
    
    # Get universe for arm
    universe = get_universe_for_arm(arm)
    
    # Determine rebalance frequency
    # QQQ is buy-and-hold, others rebalance quarterly
    if arm == "qqq":
        rebalance_freq = "none"
    else:
        rebalance_freq = "quarterly"
    
    # Initialize backtest
    backtest = GrowthQualityBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=initial_nav,
        rebalance_frequency=rebalance_freq,
        trading_cost_pct=0.0007,  # 7 bps round-trip (conservative for paper brokerage)
        benchmark_ticker="^SPXTR",  # SPY total return
    )
    
    # Run with Yahoo Finance provider
    data_provider = YahooFinanceProvider()
    
    try:
        results = backtest.run(
            universe,
            data_provider,
            arm_name=f"{arm}_{window_name}",
        )
        
        if not results:
            logger.error("Backtest failed", arm=arm, window=window_name)
            return {}
        
        # Save results
        window_output_dir = output_dir / window_name
        backtest.save_results(window_output_dir, arm_name=arm)
        
        return results.get("summary", {})
        
    except Exception as e:
        logger.error("Backtest failed with exception", arm=arm, window=window_name, error=str(e))
        return {}


def format_verdict(strategy_return: float, spy_return: float, is_primary: bool = False) -> str:
    """Format KEEP/FAIL verdict based on primary KEEP bar."""
    if strategy_return >= spy_return:
        verdict = "✓ KEEP" if is_primary else "✓ PASS"
        color = "green"
    else:
        verdict = "✗ FAIL" if is_primary else "✗ UNDER"
        color = "red"
    
    excess = strategy_return - spy_return
    return f"{verdict} ({excess:+.1f}pp vs SPY)"


def generate_summary_report(results: Dict[str, Dict[str, Dict]], output_dir: Path):
    """Generate markdown summary report."""
    
    report = []
    report.append("# Growth Quality v1 Bake-Off Results vs SPY")
    report.append("")
    report.append("**Strategy:** Concentrated liquid quality/growth equity (long-only, no covered calls)")
    report.append("")
    report.append("**KEEP Bar:** Strategy total return ≥ SPY total return on BOTH primary windows (2020-2024 AND 2010-2024)")
    report.append("")
    report.append("---")
    report.append("")
    
    # Summary table
    report.append("## Summary Table")
    report.append("")
    report.append("| Arm | Window | Strategy TR | SPY TR | Excess | Sharpe | Max DD | Verdict |")
    report.append("|-----|--------|-------------|--------|--------|--------|--------|---------|")
    
    for arm_id, arm_info in ARMS.items():
        arm_results = results.get(arm_id, {})
        
        for window_name, _ in WINDOWS.items():
            metrics = arm_results.get(window_name, {})
            
            if not metrics:
                report.append(f"| {arm_id} | {window_name} | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |")
                continue
            
            strategy_tr = metrics.get("abs_return_pct", 0.0)
            spy_tr = metrics.get("spy_return_pct", 0.0)
            excess = metrics.get("excess_return_pct", 0.0)
            sharpe = metrics.get("sharpe")
            max_dd = metrics.get("max_drawdown_pct", 0.0)
            
            is_primary = window_name in ["2020_2024", "2010_2024"]
            verdict = format_verdict(strategy_tr, spy_tr, is_primary)
            
            sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "N/A"
            
            report.append(
                f"| {arm_id} | {window_name} | {strategy_tr:.1f}% | {spy_tr:.1f}% | "
                f"{excess:+.1f}pp | {sharpe_str} | {max_dd:.1f}% | {verdict} |"
            )
    
    report.append("")
    report.append("---")
    report.append("")
    
    # Detailed results per arm
    for arm_id, arm_info in ARMS.items():
        report.append(f"## {arm_info['name']}")
        report.append("")
        report.append(f"**Description:** {arm_info['description']}")
        report.append("")
        
        arm_results = results.get(arm_id, {})
        
        if not arm_results:
            report.append("*No results available*")
            report.append("")
            continue
        
        # Check primary KEEP bar
        primary_2020_2024 = arm_results.get("2020_2024", {})
        primary_2010_2024 = arm_results.get("2010_2024", {})
        
        keep_2020_2024 = (
            primary_2020_2024.get("abs_return_pct", 0.0) >= primary_2020_2024.get("spy_return_pct", 0.0)
            if primary_2020_2024 else False
        )
        keep_2010_2024 = (
            primary_2010_2024.get("abs_return_pct", 0.0) >= primary_2010_2024.get("spy_return_pct", 0.0)
            if primary_2010_2024 else False
        )
        
        overall_keep = keep_2020_2024 and keep_2010_2024
        
        if overall_keep:
            report.append("### **VERDICT: ✓ KEEP**")
            report.append("")
            report.append("This arm **meets the primary KEEP bar** (≥ SPY on both 2020-2024 and 2010-2024).")
        else:
            report.append("### **VERDICT: ✗ ABANDON**")
            report.append("")
            if not keep_2020_2024 and not keep_2010_2024:
                report.append("This arm **fails BOTH primary windows**.")
            elif not keep_2020_2024:
                report.append("This arm **fails 2020-2024** (recent melt-up window).")
            else:
                report.append("This arm **fails 2010-2024** (long full-cycle window).")
        
        report.append("")
        
        # Detailed metrics
        report.append("### Performance by Window")
        report.append("")
        
        for window_name, (start, end) in WINDOWS.items():
            metrics = arm_results.get(window_name, {})
            
            if not metrics:
                report.append(f"**{window_name}** ({start} to {end}): *Data unavailable*")
                report.append("")
                continue
            
            is_primary = window_name in ["2020_2024", "2010_2024"]
            stress = "stress test" if "stress" in window_name else "primary window"
            
            report.append(f"**{window_name}** ({start} to {end}) - {stress}")
            report.append("")
            sharpe = metrics.get('sharpe')
            sortino = metrics.get('sortino')
            
            report.append(f"- **Strategy Total Return:** {metrics.get('abs_return_pct', 0.0):.2f}% "
                         f"(ann. {metrics.get('ann_return_pct', 0.0):.2f}%)")
            report.append(f"- **SPY Total Return:** {metrics.get('spy_return_pct', 0.0):.2f}% "
                         f"(ann. {metrics.get('spy_ann_return_pct', 0.0):.2f}%)")
            report.append(f"- **Excess Return:** {metrics.get('excess_return_pct', 0.0):+.2f}pp "
                         f"(ann. {metrics.get('excess_ann_return_pct', 0.0):+.2f}pp)")
            report.append(f"- **Sharpe Ratio:** {sharpe:.2f if sharpe is not None else 'N/A'}")
            report.append(f"- **Sortino Ratio:** {sortino:.2f if sortino is not None else 'N/A'}")
            report.append(f"- **Max Drawdown:** {metrics.get('max_drawdown_pct', 0.0):.2f}% "
                         f"(vs SPY {metrics.get('spy_max_drawdown_pct', 0.0):.2f}%)")
            report.append(f"- **Beta:** {metrics.get('beta', 0.0):.2f}")
            report.append(f"- **Correlation:** {metrics.get('correlation', 0.0):.2f}")
            report.append(f"- **Annual Turnover:** {metrics.get('turnover_annual', 0.0):.2f}x")
            
            verdict = format_verdict(
                metrics.get('abs_return_pct', 0.0),
                metrics.get('spy_return_pct', 0.0),
                is_primary
            )
            report.append(f"- **Verdict:** {verdict}")
            report.append("")
        
        report.append("---")
        report.append("")
    
    # Final recommendation
    report.append("## Final Recommendation")
    report.append("")
    
    # Count arms that KEEP
    keep_count = 0
    keep_arms = []
    
    for arm_id, arm_info in ARMS.items():
        arm_results = results.get(arm_id, {})
        primary_2020_2024 = arm_results.get("2020_2024", {})
        primary_2010_2024 = arm_results.get("2010_2024", {})
        
        keep_2020_2024 = (
            primary_2020_2024.get("abs_return_pct", 0.0) >= primary_2020_2024.get("spy_return_pct", 0.0)
            if primary_2020_2024 else False
        )
        keep_2010_2024 = (
            primary_2010_2024.get("abs_return_pct", 0.0) >= primary_2010_2024.get("spy_return_pct", 0.0)
            if primary_2010_2024 else False
        )
        
        if keep_2020_2024 and keep_2010_2024:
            keep_count += 1
            keep_arms.append(arm_id)
    
    if keep_count == 0:
        report.append("**ABANDON:** None of the arms meet the primary KEEP bar (≥ SPY on both 2020-2024 and 2010-2024).")
        report.append("")
        report.append("The growth/quality v1 engine **does not** provide a beat-SPY solution as implemented.")
    elif keep_count == len(ARMS):
        report.append(f"**KEEP:** All {keep_count} arms meet the primary KEEP bar!")
        report.append("")
        report.append("Recommendation: Proceed with the best-performing arm as the flagship absolute track.")
    else:
        report.append(f"**MIXED:** {keep_count} of {len(ARMS)} arms meet the primary KEEP bar: {', '.join(keep_arms)}")
        report.append("")
        report.append("Recommendation: Proceed with passing arm(s); abandon failing arms.")
    
    report.append("")
    report.append("---")
    report.append("")
    report.append("## Notes")
    report.append("")
    report.append("- **Honest labeling:** This is a concentrated equity bet (tech/growth/quality concentration), not mystical alpha.")
    report.append("- **Mag7 awareness:** Recent outperformance is heavily driven by Mag7/tech concentration. 2022 and 2000-2002 stress tests show the downside.")
    report.append("- **No covered calls:** This engine is pure long equity. Wheel hybrid remains a separate track for income R&D.")
    report.append("- **Data:** Free data (yfinance). Costs assumed at 7 bps round-trip.")
    report.append("- **Rebalance:** QQQ is buy-and-hold; equal-weight and quality-screen rebalance quarterly.")
    report.append("")
    
    # Write report
    report_path = output_dir / "SUMMARY.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report))
    
    logger.info("Summary report generated", path=str(report_path))


def main():
    parser = argparse.ArgumentParser(
        description="Run growth/quality v1 bake-offs vs SPY"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="results/growth_quality_v1",
        help="Output directory for results (default: results/growth_quality_v1)",
    )
    parser.add_argument(
        "--nav",
        type=float,
        default=10000.0,
        help="Initial NAV (default: 10000)",
    )
    parser.add_argument(
        "--arm",
        type=str,
        choices=list(ARMS.keys()) + ["all"],
        default="all",
        help="Run specific arm or all (default: all)",
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
    
    # Determine which arms and windows to run
    arms_to_run = list(ARMS.keys()) if args.arm == "all" else [args.arm]
    windows_to_run = list(WINDOWS.keys()) if args.window == "all" else [args.window]
    
    logger.info(
        "Starting bake-offs",
        arms=arms_to_run,
        windows=windows_to_run,
        output_dir=str(output_dir),
    )
    
    # Run all combinations
    all_results = {}
    
    for arm_id in arms_to_run:
        arm_results = {}
        
        for window_name in windows_to_run:
            start_date, end_date = WINDOWS[window_name]
            
            # Map arm_id to actual arm name
            arm_mapping = {
                "arm_a_qqq": "qqq",
                "arm_b_equal_weight": "equal_weight",
                "arm_c_quality_screen": "quality_screen",
            }
            arm_name = arm_mapping.get(arm_id, arm_id)
            
            metrics = run_single_backtest(
                arm=arm_name,
                window_name=window_name,
                start_date=start_date,
                end_date=end_date,
                output_dir=output_dir,
                initial_nav=args.nav,
            )
            
            arm_results[window_name] = metrics
        
        all_results[arm_id] = arm_results
    
    # Save consolidated results
    consolidated_path = output_dir / "consolidated_results.json"
    with open(consolidated_path, "w") as f:
        json.dump(all_results, f, indent=2)
    
    logger.info("Consolidated results saved", path=str(consolidated_path))
    
    # Generate summary report
    generate_summary_report(all_results, output_dir)
    
    print("\n" + "=" * 80)
    print("Growth Quality v1 Bake-Offs Complete")
    print("=" * 80)
    print(f"Results directory: {output_dir}/")
    print(f"Summary report: {output_dir}/SUMMARY.md")
    print(f"Consolidated results: {consolidated_path}")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
