#!/usr/bin/env python3
"""
Phase A covered-call overwrite intensity bake-off.

Tests partial overwrite (50%, 75%, 100%) on bluechip universe 2020-2024
to evaluate BXMH-style exposure retention vs always-on full overwrite.

Usage:
    python scripts/run_cc_overwrite_bakeoff.py --start 2020-01-02 --end 2024-12-31 --out results/cc_bakeoff_2020_2024
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.wheel_hybrid.engine import WheelHybridBacktest
from src.backtesting.wheel_hybrid.universe import BLUECHIP_UNIVERSE
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


def run_arm(
    arm_name: str,
    start_date: str,
    end_date: str,
    cc_overwrite_pct: float,
    cc_target_otm_pct: float,
    output_dir: Path,
):
    """Run one backtest arm with given parameters."""
    
    logger.info(
        "Running arm",
        arm=arm_name,
        overwrite_pct=cc_overwrite_pct,
        otm_pct=cc_target_otm_pct,
    )
    
    backtest = WheelHybridBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=10_000.0,
        wheel_pct=0.70,
        directional_pct=0.30,
        cc_target_otm_pct=cc_target_otm_pct,
        cc_overwrite_pct=cc_overwrite_pct,
        benchmark_ticker="^SPXTR",
    )
    
    data_provider = YahooFinanceProvider()
    results = backtest.run(BLUECHIP_UNIVERSE, data_provider)
    
    if not results:
        logger.error("Arm failed", arm=arm_name)
        return None
    
    # Save arm results
    arm_dir = output_dir / arm_name
    backtest.save_results(arm_dir)
    
    summary = results.get("summary", {})
    
    logger.info(
        "Arm complete",
        arm=arm_name,
        abs_return_pct=summary.get("abs_return_pct", 0),
        spy_return_pct=summary.get("spy_return_pct", 0),
        excess_return_pct=summary.get("excess_return_pct", 0),
        sharpe=summary.get("sharpe", 0),
        max_dd_pct=summary.get("max_drawdown_pct", 0),
    )
    
    return {
        "arm": arm_name,
        "cc_overwrite_pct": cc_overwrite_pct,
        "cc_target_otm_pct": cc_target_otm_pct,
        "summary": summary,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Phase A CC overwrite intensity bake-off (bluechip 2020-2024)"
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2020-01-02",
        help="Start date (default: 2020-01-02)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default="2024-12-31",
        help="End date (default: 2024-12-31)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output directory for bake-off results",
    )
    
    args = parser.parse_args()
    
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(
        "Starting CC overwrite bake-off",
        start=args.start,
        end=args.end,
        universe=BLUECHIP_UNIVERSE,
        output=str(output_dir),
    )
    
    # Define arms
    arms_config = [
        # Arm A: Baseline (100% overwrite, 5% OTM)
        {
            "name": "arm_a_baseline_100pct_5otm",
            "overwrite_pct": 1.00,
            "otm_pct": 0.05,
            "description": "Baseline: 100% overwrite, 5% OTM (current default)",
        },
        # Arm B: 75% overwrite
        {
            "name": "arm_b_75pct_5otm",
            "overwrite_pct": 0.75,
            "otm_pct": 0.05,
            "description": "75% overwrite, 5% OTM",
        },
        # Arm C: 50% overwrite
        {
            "name": "arm_c_50pct_5otm",
            "overwrite_pct": 0.50,
            "otm_pct": 0.05,
            "description": "50% overwrite, 5% OTM (BXMH-style)",
        },
        # Arm D: 50% overwrite + farther OTM
        {
            "name": "arm_d_50pct_10otm",
            "overwrite_pct": 0.50,
            "otm_pct": 0.10,
            "description": "50% overwrite, 10% OTM (more upside retention)",
        },
    ]
    
    # Run all arms
    results = []
    for arm_config in arms_config:
        result = run_arm(
            arm_name=arm_config["name"],
            start_date=args.start,
            end_date=args.end,
            cc_overwrite_pct=arm_config["overwrite_pct"],
            cc_target_otm_pct=arm_config["otm_pct"],
            output_dir=output_dir,
        )
        
        if result:
            result["description"] = arm_config["description"]
            results.append(result)
    
    # Save comparison table
    comparison_file = output_dir / "comparison.json"
    with open(comparison_file, "w") as f:
        json.dump(results, f, indent=2)
    
    # Generate markdown summary
    markdown_file = output_dir / "summary.md"
    generate_markdown_summary(results, args.start, args.end, markdown_file)
    
    # Print summary
    print_comparison_table(results)
    
    logger.info("Bake-off complete", output=str(output_dir))
    
    return 0


def generate_markdown_summary(results: list, start_date: str, end_date: str, output_file: Path):
    """Generate markdown summary for PR body."""
    
    if not results:
        return
    
    baseline = results[0]["summary"]
    spy_return = baseline.get("spy_return_pct", 0)
    
    md = []
    md.append("# Phase A: Covered Call Overwrite Intensity Bake-off\n")
    md.append(f"**Period:** {start_date} to {end_date}\n")
    md.append(f"**Universe:** Bluechip 6-name ({', '.join(BLUECHIP_UNIVERSE)})\n")
    md.append(f"**Benchmark:** SPY Total Return = {spy_return:+.2f}%\n")
    md.append("\n")
    md.append("## Results Summary\n")
    md.append("\n")
    md.append("| Arm | Overwrite % | OTM % | Total Return | vs SPY | Sharpe | Sortino | Max DD | Upside Cap | Downside Cap | CC Writes |\n")
    md.append("|-----|-------------|-------|--------------|--------|--------|---------|--------|------------|--------------|----------|\n")
    
    for r in results:
        s = r["summary"]
        arm = r["arm"].replace("arm_", "").replace("_", " ").upper()
        overwrite = r["cc_overwrite_pct"] * 100
        otm = r["cc_target_otm_pct"] * 100
        total_ret = s.get("abs_return_pct", 0)
        excess = s.get("excess_return_pct", 0)
        sharpe = s.get("sharpe", 0)
        sortino = s.get("sortino", 0)
        max_dd = s.get("max_drawdown_pct", 0)
        up_cap = s.get("upside_capture_pct", 0)
        down_cap = s.get("downside_capture_pct", 0)
        cc_writes = s.get("trade_counts", {}).get("cc_writes", 0)
        
        md.append(
            f"| {arm} | {overwrite:.0f}% | {otm:.0f}% | "
            f"{total_ret:+.2f}% | {excess:+.2f}pp | "
            f"{sharpe:.2f} | {sortino:.2f} | {max_dd:.2f}% | "
            f"{up_cap:.1f}% | {down_cap:.1f}% | {cc_writes} |\n"
        )
    
    md.append("\n")
    md.append("## Key Findings\n")
    md.append("\n")
    
    baseline_ret = results[0]["summary"].get("abs_return_pct", 0)
    baseline_excess = results[0]["summary"].get("excess_return_pct", 0)
    
    md.append(f"- **Baseline (100% overwrite):** {baseline_ret:+.2f}% total return, {baseline_excess:+.2f}pp vs SPY\n")
    
    for r in results[1:]:
        s = r["summary"]
        ret = s.get("abs_return_pct", 0)
        excess = s.get("excess_return_pct", 0)
        delta_ret = ret - baseline_ret
        delta_excess = excess - baseline_excess
        
        md.append(
            f"- **{r['description']}:** {ret:+.2f}% total return ({delta_ret:+.2f}pp vs baseline), "
            f"{excess:+.2f}pp vs SPY ({delta_excess:+.2f}pp improvement)\n"
        )
    
    md.append("\n")
    md.append("## Recommendation\n")
    md.append("\n")
    
    best = max(results, key=lambda x: x["summary"].get("abs_return_pct", 0))
    best_excess = best["summary"].get("excess_return_pct", 0)
    best_ret = best["summary"].get("abs_return_pct", 0)
    
    if best["arm"] == results[0]["arm"]:
        md.append("**KEEP default (100% overwrite) for now.** Partial overwrite did not improve absolute excess vs SPY by meaningful margin.\n")
    elif best_excess > baseline_excess + 2.0:
        md.append(
            f"**KEEP {best['description']} as new default.** "
            f"Improved absolute excess vs SPY by {best_excess - baseline_excess:+.2f}pp "
            f"({best_ret:+.2f}% vs {baseline_ret:+.2f}%) without catastrophic DD/Sharpe collapse.\n"
        )
    else:
        md.append(
            f"**BORDERLINE.** {best['description']} marginally improved vs baseline "
            f"({best_excess - baseline_excess:+.2f}pp), but below 2pp threshold for production change. "
            f"Keep code as research knob (default=1.0).\n"
        )
    
    md.append("\n")
    md.append("## Notes\n")
    md.append("\n")
    md.append("- Premium estimates: Synthetic Black-Scholes with 21-day realized vol (labeled honestly, not market IV)\n")
    md.append("- Regime/VRP gating: OFF (Phase A mechanics only)\n")
    md.append("- Partial overwrite = BXMH-style: write calls on only N% of eligible lots, rest stay uncovered long equity\n")
    md.append("- Citeable protocol: Bluechip liquid universe, frozen rules, no tuning on eval window\n")
    md.append("\n")
    
    with open(output_file, "w") as f:
        f.writelines(md)
    
    logger.info("Markdown summary saved", path=str(output_file))


def print_comparison_table(results: list):
    """Print comparison table to console."""
    
    if not results:
        print("No results to display.")
        return
    
    print("\n" + "=" * 120)
    print("Phase A: Covered Call Overwrite Intensity Bake-off")
    print("=" * 120)
    
    print(f"\n{'Arm':<30} {'Overwrite':<12} {'OTM':<8} {'Total Ret':<12} {'vs SPY':<10} "
          f"{'Sharpe':<8} {'Sortino':<8} {'Max DD':<10} {'Up Cap':<10} {'Down Cap':<10} {'CC Writes':<10}")
    print("-" * 120)
    
    for r in results:
        s = r["summary"]
        arm = r["description"][:28]
        overwrite = f"{r['cc_overwrite_pct']*100:.0f}%"
        otm = f"{r['cc_target_otm_pct']*100:.0f}%"
        total_ret = f"{s.get('abs_return_pct', 0):+.2f}%"
        excess = f"{s.get('excess_return_pct', 0):+.2f}pp"
        sharpe = f"{s.get('sharpe', 0):.2f}"
        sortino = f"{s.get('sortino', 0):.2f}"
        max_dd = f"{s.get('max_drawdown_pct', 0):.2f}%"
        up_cap = f"{s.get('upside_capture_pct', 0):.1f}%"
        down_cap = f"{s.get('downside_capture_pct', 0):.1f}%"
        cc_writes = s.get('trade_counts', {}).get('cc_writes', 0)
        
        print(f"{arm:<30} {overwrite:<12} {otm:<8} {total_ret:<12} {excess:<10} "
              f"{sharpe:<8} {sortino:<8} {max_dd:<10} {up_cap:<10} {down_cap:<10} {cc_writes:<10}")
    
    print("-" * 120)
    
    baseline = results[0]["summary"]
    spy_return = baseline.get("spy_return_pct", 0)
    
    print(f"\nBenchmark (SPY): {spy_return:+.2f}%")
    print(f"Baseline (100% overwrite): {baseline.get('abs_return_pct', 0):+.2f}% "
          f"({baseline.get('excess_return_pct', 0):+.2f}pp vs SPY)")
    
    print("\n" + "=" * 120 + "\n")


if __name__ == "__main__":
    sys.exit(main())
