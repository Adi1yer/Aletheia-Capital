#!/usr/bin/env python3
"""Run income drip bake-off: momentum growth + dividend/CC income drips."""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.growth_quality.engine import GrowthQualityBacktest
from src.backtesting.growth_quality.universe import get_universe_for_arm
from src.backtesting.income_drip.engine import IncomeDripBacktest
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


# Test windows (matching PR #10)
WINDOWS = {
    "2020_2024": ("2020-01-01", "2024-12-31"),
    "2010_2024": ("2010-01-01", "2024-12-31"),
    "2022_stress": ("2022-01-01", "2022-12-31"),
    "2000_2002_stress": ("2000-01-01", "2002-12-31"),
    "2008_2009_stress": ("2008-01-01", "2009-12-31"),
}


# Strategy arms
ARMS = {
    "arm_1_pure_momentum": {
        "name": "Arm 1: Pure Momentum (Arm C Baseline)",
        "description": "100% Arm C momentum quality (12-1 month, top 30, quarterly EW) - control from PR #10",
        "type": "pure_momentum",
        "growth_weight": 1.0,
        "ballast_weight": 0.0,
        "cc_enabled": False,
    },
    "arm_2_momentum_div_drip": {
        "name": "Arm 2: Momentum + Dividend Drip",
        "description": "80% Arm C + 20% dividend ballast; dividends drip into Arm C quarterly",
        "type": "income_drip",
        "growth_weight": 0.80,
        "ballast_weight": 0.20,
        "cc_enabled": False,
    },
    "arm_3_momentum_div_cc_drip": {
        "name": "Arm 3: Momentum + Dividend + Light CC Drip",
        "description": "80% Arm C + 20% dividend ballast with 50% light CC overwrite (7.5% OTM, 45d); all income drips into Arm C",
        "type": "income_drip",
        "growth_weight": 0.80,
        "ballast_weight": 0.20,
        "cc_enabled": True,
        "cc_overwrite_pct": 0.50,
        "cc_otm_pct": 0.075,
        "cc_tenor_days": 45,
    },
}


def run_pure_momentum_arm(
    window_name: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
    initial_nav: float = 10_000.0,
) -> Dict:
    """Run pure Arm C momentum (control)."""
    logger.info("Running pure momentum arm", window=window_name)
    
    backtest = GrowthQualityBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=initial_nav,
        rebalance_frequency="quarterly",
        trading_cost_pct=0.0007,  # 7 bps
        benchmark_ticker="^SPXTR",
        top_n=30,
    )
    
    data_provider = YahooFinanceProvider()
    
    # Get initial universe (will refresh at each rebalance)
    universe = get_universe_for_arm("point_in_time_quality")
    
    try:
        results = backtest.run(
            universe,
            data_provider,
            arm_name=f"arm_1_pure_momentum_{window_name}",
            arm_type="point_in_time_quality",
        )
        
        if not results:
            logger.error("Pure momentum backtest failed", window=window_name)
            return {}
        
        # Save results
        window_output_dir = output_dir / window_name
        backtest.save_results(window_output_dir, arm_name="arm_1_pure_momentum")
        
        return results.get("summary", {})
        
    except Exception as e:
        logger.error("Pure momentum backtest failed with exception", window=window_name, error=str(e))
        import traceback
        traceback.print_exc()
        return {}


def run_income_drip_arm(
    arm_id: str,
    arm_info: Dict,
    window_name: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
    initial_nav: float = 10_000.0,
) -> Dict:
    """Run income drip arm (with or without CCs)."""
    logger.info("Running income drip arm", arm=arm_id, window=window_name)
    
    backtest = IncomeDripBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=initial_nav,
        growth_weight=arm_info["growth_weight"],
        ballast_weight=arm_info["ballast_weight"],
        rebalance_frequency="quarterly",
        trading_cost_pct=0.0007,  # 7 bps
        benchmark_ticker="^SPXTR",
        cc_enabled=arm_info["cc_enabled"],
        cc_overwrite_pct=arm_info.get("cc_overwrite_pct", 0.50),
        cc_otm_pct=arm_info.get("cc_otm_pct", 0.075),
        cc_tenor_days=arm_info.get("cc_tenor_days", 45),
    )
    
    data_provider = YahooFinanceProvider()
    
    try:
        results = backtest.run(
            data_provider,
            arm_name=f"{arm_id}_{window_name}",
        )
        
        if not results:
            logger.error("Income drip backtest failed", arm=arm_id, window=window_name)
            return {}
        
        # Save results
        window_output_dir = output_dir / window_name
        backtest.save_results(window_output_dir, arm_name=arm_id)
        
        return results.get("summary", {})
        
    except Exception as e:
        logger.error("Income drip backtest failed with exception", arm=arm_id, window=window_name, error=str(e))
        import traceback
        traceback.print_exc()
        return {}


def format_verdict(strategy_return: float, benchmark_return: float, is_primary: bool = False) -> str:
    """Format verdict based on relative performance."""
    if strategy_return >= benchmark_return:
        verdict = "✓ BEATS" if is_primary else "✓ PASS"
    else:
        verdict = "✗ LAGS" if is_primary else "✗ UNDER"
    
    excess = strategy_return - benchmark_return
    return f"{verdict} ({excess:+.1f}pp)"


def generate_summary_report(results: Dict[str, Dict[str, Dict]], output_dir: Path):
    """Generate markdown summary report with KEEP/ABANDON recommendation."""
    
    report = []
    report.append("# Income Drip Bake-Off Results: Momentum + Dividend/CC Income")
    report.append("")
    report.append("**Product Thesis:** Momentum + liquid concentration is the beat-SPY *driver*. ")
    report.append("Dividends and covered-call premiums are a *funding drip* into that driver — not a hedge story.")
    report.append("")
    report.append("**KEEP Bar:** Income drip arm beats pure Arm C on risk-adjusted grounds OR beats SPY ")
    report.append("with materially milder drawdowns than pure Arm C (without lagging Arm C badly on total return).")
    report.append("")
    report.append("---")
    report.append("")
    
    # Summary table
    report.append("## Summary Table")
    report.append("")
    report.append("| Arm | Window | Strategy TR | SPY TR | vs SPY | Sharpe | Max DD | Verdict |")
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
        
        # Configuration
        report.append("**Configuration:**")
        report.append(f"- Growth sleeve (Arm C momentum): {arm_info['growth_weight']*100:.0f}%")
        report.append(f"- Ballast sleeve (dividend payers): {arm_info['ballast_weight']*100:.0f}%")
        if arm_info["cc_enabled"]:
            report.append(f"- Covered calls: {arm_info['cc_overwrite_pct']*100:.0f}% overwrite, {arm_info['cc_otm_pct']*100:.1f}% OTM, {arm_info['cc_tenor_days']}d tenor")
        else:
            report.append("- Covered calls: None")
        report.append("")
        
        arm_results = results.get(arm_id, {})
        
        if not arm_results:
            report.append("*No results available*")
            report.append("")
            continue
        
        # Performance by window
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
            sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "N/A"
            sortino_str = f"{sortino:.2f}" if sortino is not None else "N/A"
            report.append(f"- **Sharpe Ratio:** {sharpe_str}")
            report.append(f"- **Sortino Ratio:** {sortino_str}")
            report.append(f"- **Max Drawdown:** {metrics.get('max_drawdown_pct', 0.0):.2f}% "
                         f"(vs SPY {metrics.get('spy_max_drawdown_pct', 0.0):.2f}%)")
            report.append(f"- **Beta:** {metrics.get('beta', 0.0):.2f}")
            report.append(f"- **Correlation:** {metrics.get('correlation', 0.0):.2f}")
            
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
    
    # Compare Arm 2 and Arm 3 vs Arm 1 (pure momentum)
    arm1_results = results.get("arm_1_pure_momentum", {})
    arm2_results = results.get("arm_2_momentum_div_drip", {})
    arm3_results = results.get("arm_3_momentum_div_cc_drip", {})
    
    # Primary windows
    arm1_2020 = arm1_results.get("2020_2024", {})
    arm2_2020 = arm2_results.get("2020_2024", {})
    arm3_2020 = arm3_results.get("2020_2024", {})
    
    arm1_2010 = arm1_results.get("2010_2024", {})
    arm2_2010 = arm2_results.get("2010_2024", {})
    arm3_2010 = arm3_results.get("2010_2024", {})
    
    def compare_arms(drip_arm_name: str, drip_2020: Dict, drip_2010: Dict) -> str:
        """Compare a drip arm vs pure Arm C."""
        if not drip_2020 or not drip_2010 or not arm1_2020 or not arm1_2010:
            return "INSUFFICIENT DATA"
        
        # Check if drip beats pure Arm C on Sharpe (risk-adjusted)
        drip_sharpe_2020 = drip_2020.get("sharpe", 0)
        arm1_sharpe_2020 = arm1_2020.get("sharpe", 0)
        drip_sharpe_2010 = drip_2010.get("sharpe", 0)
        arm1_sharpe_2010 = arm1_2010.get("sharpe", 0)
        
        sharpe_beats = (drip_sharpe_2020 >= arm1_sharpe_2020 and drip_sharpe_2010 >= arm1_sharpe_2010)
        
        # Check if drip beats SPY with lower DD than pure Arm C
        drip_tr_2020 = drip_2020.get("abs_return_pct", 0)
        drip_tr_2010 = drip_2010.get("abs_return_pct", 0)
        spy_tr_2020 = drip_2020.get("spy_return_pct", 0)
        spy_tr_2010 = drip_2010.get("spy_return_pct", 0)
        
        drip_dd_2020 = abs(drip_2020.get("max_drawdown_pct", 100))
        arm1_dd_2020 = abs(arm1_2020.get("max_drawdown_pct", 100))
        drip_dd_2010 = abs(drip_2010.get("max_drawdown_pct", 100))
        arm1_dd_2010 = abs(arm1_2010.get("max_drawdown_pct", 100))
        
        beats_spy = (drip_tr_2020 >= spy_tr_2020 and drip_tr_2010 >= spy_tr_2010)
        lower_dd = (drip_dd_2020 < arm1_dd_2020 - 3.0 or drip_dd_2010 < arm1_dd_2010 - 3.0)  # At least 3pp improvement
        
        # Check if drip doesn't lag Arm C badly
        arm1_tr_2020 = arm1_2020.get("abs_return_pct", 0)
        arm1_tr_2010 = arm1_2010.get("abs_return_pct", 0)
        lag_threshold = -10.0  # Can lag by up to 10pp
        
        lags_badly = ((drip_tr_2020 - arm1_tr_2020) < lag_threshold or (drip_tr_2010 - arm1_tr_2010) < lag_threshold)
        
        if sharpe_beats:
            return "✓ KEEP - Beats pure Arm C on risk-adjusted returns (Sharpe)"
        elif beats_spy and lower_dd and not lags_badly:
            return "✓ KEEP - Beats SPY with materially lower drawdowns than Arm C, without lagging badly"
        else:
            return "✗ ABANDON - Does not meet KEEP bar (no risk-adjusted advantage vs pure Arm C)"
    
    arm2_verdict = compare_arms("Arm 2", arm2_2020, arm2_2010)
    arm3_verdict = compare_arms("Arm 3", arm3_2020, arm3_2010)
    
    report.append(f"**Arm 2 (Dividend Drip):** {arm2_verdict}")
    report.append("")
    report.append(f"**Arm 3 (Dividend + CC Drip):** {arm3_verdict}")
    report.append("")
    
    if "✓ KEEP" in arm2_verdict or "✓ KEEP" in arm3_verdict:
        report.append("**Overall Verdict: KEEP** at least one income drip variant for further evaluation.")
        report.append("")
        report.append("Recommended next steps:")
        report.append("- Consider income drip as a tactical allocation or alternative to pure Arm C")
        report.append("- Monitor dividend sustainability and covered call assignment risk in live tracking")
        report.append("- Evaluate tax efficiency (qualified dividends + short-term CC gains)")
    else:
        report.append("**Overall Verdict: ABANDON** income drip as production default.")
        report.append("")
        report.append("The dividend/CC drip does not provide sufficient risk-adjusted advantage over pure Arm C momentum.")
        report.append("Stick with pure Arm C (100% momentum quality) as the growth engine flagship.")
        report.append("")
        report.append("This bake-off remains as research archive for future reference.")
    
    report.append("")
    report.append("---")
    report.append("")
    report.append("## Pre-Registered Design Rules")
    report.append("")
    report.append("### Methodology")
    report.append("")
    report.append("- **Growth sleeve (Arm C):** 12-1 month momentum, top 30 liquid large-cap quality names")
    report.append("- **Ballast sleeve:** Top 20 liquid dividend payers by trailing 12-month yield (≥1.5%)")
    report.append("- **Rebalance frequency:** Quarterly (Jan, Apr, Jul, Oct)")
    report.append("- **Dividend drip:** All dividends from ballast accumulate and deploy into growth at quarterly rebalance")
    report.append("- **Covered calls (Arm 3 only):** 50% overwrite, 7.5% OTM, 45-day tenor, synthetic Black-Scholes pricing")
    report.append("- **Trading costs:** 7 bps round-trip (conservative for paper brokerage)")
    report.append("- **No lookahead:** All universes selected using only point-in-time information")
    report.append("")
    report.append("### Data Sources")
    report.append("")
    report.append("- **Price data:** yfinance (free)")
    report.append("- **Dividend data:** yfinance trailing 12-month dividends")
    report.append("- **Option pricing:** Synthetic Black-Scholes using realized volatility * 1.1 (IV proxy)")
    report.append("- **Benchmark:** ^SPXTR (SPY total return) where available, SPY fallback")
    report.append("")
    report.append("### Honest Framing")
    report.append("")
    report.append("This is 'income buys growth,' NOT 'CC hedges drawdowns.'")
    report.append("")
    report.append("Covered calls on ballast generate premium income but cap upside on those names.")
    report.append("The growth sleeve (Arm C momentum) is NEVER overwritten — it stays pure long.")
    report.append("")
    report.append("Dividend/CC income provides a steady drip to buy more growth names, but does not hedge the growth book itself.")
    report.append("")
    
    # Write report
    report_path = output_dir / "SUMMARY.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report))
    
    logger.info("Summary report generated", path=str(report_path))


def main():
    parser = argparse.ArgumentParser(
        description="Run income drip bake-off: momentum + dividend/CC income"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="results/income_drip_v1",
        help="Output directory for results (default: results/income_drip_v1)",
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
        "Starting income drip bake-offs",
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
            
            if arm_info["type"] == "pure_momentum":
                metrics = run_pure_momentum_arm(
                    window_name=window_name,
                    start_date=start_date,
                    end_date=end_date,
                    output_dir=output_dir,
                    initial_nav=args.nav,
                )
            else:
                metrics = run_income_drip_arm(
                    arm_id=arm_id,
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
    print("Income Drip Bake-Off Complete")
    print("=" * 80)
    print(f"Results directory: {output_dir}/")
    print(f"Summary report: {output_dir}/SUMMARY.md")
    print(f"Consolidated results: {consolidated_path}")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
