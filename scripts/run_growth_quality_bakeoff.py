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


# Strategy arms (FIXED FOR CITEABILITY)
ARMS = {
    "arm_a_qqq": {
        "name": "Arm A: QQQ Buy-and-Hold",
        "description": "Nasdaq-100 ETF - citeable concentration baseline",
        "arm_type": "fixed",
        "universe_func": "qqq",
        "citeable": True,
        "keep_candidate": False,  # Baseline only
    },
    "arm_b_hindsight": {
        "name": "Arm B: Hindsight Quality Basket ⚠️ LOOKAHEAD",
        "description": "⚠️ HINDSIGHT / LOOKAHEAD - NOT CITEABLE. Fixed 2024 winner list (upper bound demo only)",
        "arm_type": "fixed",
        "universe_func": "hindsight_quality",
        "citeable": False,
        "keep_candidate": False,  # Cannot KEEP regardless of returns
    },
    "arm_c_point_in_time": {
        "name": "Arm C: Point-in-Time Quality",
        "description": "Liquid large-cap quality screen using only past information (PRIMARY KEEP CANDIDATE)",
        "arm_type": "point_in_time_quality",
        "universe_func": "point_in_time_quality",
        "citeable": True,
        "keep_candidate": True,
    },
    "arm_d_sp100": {
        "name": "Arm D: Equal-Weight S&P 100",
        "description": "Non-hindsight concentration control (rules-based diversified baseline)",
        "arm_type": "fixed",
        "universe_func": "sp100_equal_weight",
        "citeable": True,
        "keep_candidate": True,
    },
}


def run_single_backtest(
    arm: str,
    arm_info: Dict,
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
    universe = get_universe_for_arm(arm_info["universe_func"])
    
    # Determine rebalance frequency
    if arm_info["universe_func"] == "qqq":
        rebalance_freq = "none"  # Buy-and-hold
    else:
        rebalance_freq = "quarterly"
    
    # Initialize backtest
    backtest = GrowthQualityBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=initial_nav,
        rebalance_frequency=rebalance_freq,
        trading_cost_pct=0.0007,  # 7 bps round-trip
        benchmark_ticker="^SPXTR",  # SPY total return
        top_n=30 if arm_info["universe_func"] == "point_in_time_quality" else None,
    )
    
    # Run with Yahoo Finance provider
    data_provider = YahooFinanceProvider()
    
    try:
        results = backtest.run(
            universe,
            data_provider,
            arm_name=f"{arm}_{window_name}",
            arm_type=arm_info["arm_type"],
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
        import traceback
        traceback.print_exc()
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
    """Generate markdown summary report with proper hindsight labeling."""
    
    report = []
    report.append("# Growth Quality v1 Bake-Off Results vs SPY (FIXED FOR CITEABILITY)")
    report.append("")
    report.append("**Strategy:** Concentrated liquid quality/growth equity (long-only, no covered calls)")
    report.append("")
    report.append("**KEEP Bar:** Strategy total return ≥ SPY total return on BOTH primary windows (2020-2024 AND 2010-2024)")
    report.append("")
    report.append("**ONLY CITEABLE ARMS (A, C, D) are KEEP candidates.** Arm B is hindsight/lookahead demo only.")
    report.append("")
    report.append("---")
    report.append("")
    
    # Summary table
    report.append("## Summary Table")
    report.append("")
    report.append("| Arm | Window | Strategy TR | SPY TR | Excess | Sharpe | Max DD | Verdict | Notes |")
    report.append("|-----|--------|-------------|--------|--------|--------|--------|---------|-------|")
    
    for arm_id, arm_info in ARMS.items():
        arm_results = results.get(arm_id, {})
        
        for window_name, _ in WINDOWS.items():
            metrics = arm_results.get(window_name, {})
            
            if not metrics:
                citeable_note = "⚠️ LOOKAHEAD" if not arm_info["citeable"] else ""
                report.append(f"| {arm_id} | {window_name} | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE | {citeable_note} |")
                continue
            
            strategy_tr = metrics.get("abs_return_pct", 0.0)
            spy_tr = metrics.get("spy_return_pct", 0.0)
            excess = metrics.get("excess_return_pct", 0.0)
            sharpe = metrics.get("sharpe")
            max_dd = metrics.get("max_drawdown_pct", 0.0)
            
            is_primary = window_name in ["2020_2024", "2010_2024"]
            
            # Mark hindsight arms clearly
            if not arm_info["citeable"]:
                verdict = "⚠️ LOOKAHEAD - NOT CITEABLE"
                citeable_note = "⚠️ HINDSIGHT"
            else:
                verdict = format_verdict(strategy_tr, spy_tr, is_primary)
                citeable_note = ""
            
            sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "N/A"
            
            report.append(
                f"| {arm_id} | {window_name} | {strategy_tr:.1f}% | {spy_tr:.1f}% | "
                f"{excess:+.1f}pp | {sharpe_str} | {max_dd:.1f}% | {verdict} | {citeable_note} |"
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
        
        # Check primary KEEP bar (only for citeable arms that are KEEP candidates)
        if arm_info["keep_candidate"] and arm_info["citeable"]:
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
        elif not arm_info["citeable"]:
            report.append("### **VERDICT: ⚠️ HINDSIGHT / LOOKAHEAD - NOT CITEABLE**")
            report.append("")
            report.append("This arm uses 2024 hindsight winners and CANNOT be cited as tradeable edge.")
            report.append("It demonstrates an UPPER BOUND only. Do not recommend as flagship regardless of returns.")
        else:
            report.append("### **VERDICT: BASELINE (not a KEEP candidate)**")
            report.append("")
            report.append("This arm is a citeable baseline for comparison.")
        
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
    
    # Count CITEABLE arms that KEEP (exclude hindsight)
    keep_count = 0
    keep_arms = []
    
    for arm_id, arm_info in ARMS.items():
        # Only consider citeable KEEP candidates
        if not arm_info["keep_candidate"] or not arm_info["citeable"]:
            continue
            
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
    
    citeable_candidate_count = sum(1 for a in ARMS.values() if a["keep_candidate"] and a["citeable"])
    
    if keep_count == 0:
        report.append(f"**ABANDON:** None of the {citeable_candidate_count} citeable KEEP candidate arms meet the primary KEEP bar (≥ SPY on both 2020-2024 and 2010-2024).")
        report.append("")
        report.append("The growth/quality v1 engine **does not** provide a citeable beat-SPY solution as implemented.")
    elif keep_count == citeable_candidate_count:
        report.append(f"**KEEP:** All {keep_count} citeable KEEP candidate arms meet the primary KEEP bar!")
        report.append("")
        report.append(f"Passing arms: {', '.join(keep_arms)}")
        report.append("")
        report.append("Recommendation: Proceed with the best-performing citeable arm as the flagship absolute track.")
    else:
        report.append(f"**MIXED:** {keep_count} of {citeable_candidate_count} citeable KEEP candidate arms meet the primary KEEP bar: {', '.join(keep_arms)}")
        report.append("")
        report.append("Recommendation: Proceed with passing arm(s); abandon failing arms.")
    
    report.append("")
    report.append("---")
    report.append("")
    report.append("## Important Notes on Methodology")
    report.append("")
    report.append("### Arm B: Hindsight / Lookahead Warning")
    report.append("")
    report.append("⚠️ **ARM B IS NOT CITEABLE**  ")
    report.append("Arm B uses a fixed list of 2024 winners (AAPL, MSFT, GOOGL, AMZN, NVDA, etc.) selected with full hindsight.")
    report.append("This is SURVIVORSHIP BIAS and LOOK-AHEAD BIAS.")
    report.append("")
    report.append("**Use only as UPPER BOUND demonstration.**  ")
    report.append("Do NOT cite as tradeable edge. Do NOT recommend as flagship regardless of returns.")
    report.append("")
    report.append("### Arm A: QQQ Baseline")
    report.append("")
    report.append("Arm A (QQQ buy-and-hold) is a citeable concentration baseline.")
    report.append("If QQQ beats SPY, it supports the product direction but is 'buy QQQ,' not Aletheia alpha.")
    report.append("")
    report.append("### Arms C & D: Citeable KEEP Candidates")
    report.append("")
    report.append("Only Arms C (point-in-time quality) and D (S&P 100 equal-weight) are citeable KEEP candidates.")
    report.append("They use ONLY information available at each rebalance date (no hindsight).")
    report.append("")
    report.append("---")
    report.append("")
    report.append("## Data & Methodology")
    report.append("")
    report.append("- **Free data:** yfinance for all price history")
    report.append("- **Benchmark:** ^SPXTR (SPY total return) where available, SPY price-only fallback")
    report.append("- **Trading costs:** 7 bps round-trip (conservative for paper brokerage)")
    report.append("- **Rebalance frequency:** Quarterly for Arms C & D; buy-and-hold for Arm A; quarterly for Arm B")
    report.append("- **No covered calls:** This is pure long equity")
    report.append("- **Initial NAV:** $10,000")
    report.append("- **Point-in-time selection (Arm C):** Uses only data available as of each rebalance date")
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
        arm_info = ARMS[arm_id]
        arm_results = {}
        
        for window_name in windows_to_run:
            start_date, end_date = WINDOWS[window_name]
            
            metrics = run_single_backtest(
                arm=arm_id,
                arm_info=arm_info,
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
