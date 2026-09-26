#!/usr/bin/env python3
"""
Phase B Bake-off: Covered-call strike schedule (wider-OTM / ~30Δ).

Tests fixed strike width schedules (widen-not-skip) to evaluate
BXMD-like 30Δ vs current 5% OTM baseline.

Hard constraints:
- Keep cc_overwrite_pct = 1.0 (100% overwrite, Phase A default)
- No VIX/regime gates (Phase A/B focus on mechanics)
- Bluechip universe 2020-2024 for citeable comparison
- Must reproduce Phase A baseline Arm A (~+75%) or document drift

Arms:
A. Baseline: 5% OTM, 100% overwrite (Phase A winner)
B. Wider OTM: 7.5% OTM, 100% overwrite
C. BXMD-style: ~30Δ delta-targeted, 100% overwrite
D. BXY-style: 2% OTM, 100% overwrite (optional closer)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.wheel_hybrid.engine import WheelHybridBacktest
from src.backtesting.wheel_hybrid.universe import get_wheel_universe
from src.data.providers.yahoo import YahooFinanceProvider

logger = structlog.get_logger()


def run_arm(
    label: str,
    start_date: str,
    end_date: str,
    initial_nav: float,
    universe: List[str],
    benchmark_ticker: str,
    cc_strike_mode: str,
    cc_target_otm_pct: float = 0.05,
    cc_target_delta: float = 0.30,
) -> Dict:
    """Run single bakeoff arm."""
    logger.info(
        "Running arm",
        label=label,
        strike_mode=cc_strike_mode,
        otm_pct=cc_target_otm_pct if cc_strike_mode == "otm_pct" else None,
        target_delta=cc_target_delta if cc_strike_mode == "delta" else None,
    )

    backtest = WheelHybridBacktest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=initial_nav,
        wheel_pct=0.70,
        directional_pct=0.30,
        cc_strike_mode=cc_strike_mode,
        cc_target_otm_pct=cc_target_otm_pct,
        cc_target_delta=cc_target_delta,
        benchmark_ticker=benchmark_ticker,
    )

    data_provider = YahooFinanceProvider()
    results = backtest.run(universe, data_provider)

    if not results:
        logger.error("Arm failed", label=label)
        return {}

    summary = results.get("summary", {})
    
    # Add configuration metadata
    summary["config"] = {
        "label": label,
        "strike_mode": cc_strike_mode,
        "target_otm_pct": cc_target_otm_pct if cc_strike_mode == "otm_pct" else None,
        "target_delta": cc_target_delta if cc_strike_mode == "delta" else None,
    }
    
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Phase B Bake-off: Strike schedule (wider-OTM / 30Δ)"
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
        "--nav",
        type=float,
        default=10000.0,
        help="Initial NAV (default: 10000)",
    )
    parser.add_argument(
        "--universe",
        type=str,
        default="bluechip",
        choices=["bluechip", "expanded"],
        help="Universe (default: bluechip for citeable comparison)",
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
        default="results/phase_b_strike_bakeoff",
        help="Output directory (default: results/phase_b_strike_bakeoff)",
    )

    args = parser.parse_args()

    universe = get_wheel_universe(args.start, universe_type=args.universe)

    logger.info(
        "=" * 80 + "\nPhase B Strike Schedule Bake-off\n" + "=" * 80,
        start=args.start,
        end=args.end,
        universe_type=args.universe,
        universe_count=len(universe),
    )

    # === ARM A: Baseline (5% OTM) ===
    arm_a = run_arm(
        label="A: Baseline (5% OTM)",
        start_date=args.start,
        end_date=args.end,
        initial_nav=args.nav,
        universe=universe,
        benchmark_ticker=args.benchmark,
        cc_strike_mode="otm_pct",
        cc_target_otm_pct=0.05,
    )

    # === ARM B: Wider OTM (7.5%) ===
    arm_b = run_arm(
        label="B: Wider OTM (7.5%)",
        start_date=args.start,
        end_date=args.end,
        initial_nav=args.nav,
        universe=universe,
        benchmark_ticker=args.benchmark,
        cc_strike_mode="otm_pct",
        cc_target_otm_pct=0.075,
    )

    # === ARM C: BXMD-style (30Δ) ===
    arm_c = run_arm(
        label="C: BXMD-style (30Δ)",
        start_date=args.start,
        end_date=args.end,
        initial_nav=args.nav,
        universe=universe,
        benchmark_ticker=args.benchmark,
        cc_strike_mode="delta",
        cc_target_delta=0.30,
    )

    # === ARM D: BXY-style (2% OTM) ===
    arm_d = run_arm(
        label="D: BXY-style (2% OTM)",
        start_date=args.start,
        end_date=args.end,
        initial_nav=args.nav,
        universe=universe,
        benchmark_ticker=args.benchmark,
        cc_strike_mode="otm_pct",
        cc_target_otm_pct=0.02,
    )

    # === Save Results ===
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "metadata": {
            "start_date": args.start,
            "end_date": args.end,
            "initial_nav": args.nav,
            "universe_type": args.universe,
            "universe_tickers": universe,
            "benchmark": args.benchmark,
            "phase": "B",
            "description": "Strike schedule bake-off (wider-OTM / 30Δ)",
        },
        "arms": {
            "A_baseline_5pct_otm": arm_a,
            "B_wider_7.5pct_otm": arm_b,
            "C_bxmd_30delta": arm_c,
            "D_bxy_2pct_otm": arm_d,
        },
    }

    json_path = output_dir / "phase_b_bakeoff_results.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    # === Generate Comparison Table ===
    print("\n" + "=" * 100)
    print(f"PHASE B STRIKE SCHEDULE BAKE-OFF ({args.start} to {args.end})")
    print("=" * 100)
    print(f"Universe: {args.universe} ({len(universe)} tickers: {', '.join(universe)})")
    print(f"Benchmark: SPY Total Return = {arm_a.get('spy_return_pct', 0):+.2f}%")
    print("=" * 100)
    print()

    # Table header
    print(f"{'Arm':<25} {'Total Ret':<12} {'vs SPY':<12} {'Sharpe':<8} {'Sortino':<8} {'Max DD':<10} {'Up Cap':<8} {'Down Cap':<10} {'CC Writes':<12} {'Premium':<12}")
    print("-" * 125)

    arms_data = [
        ("A: Baseline (5% OTM)", arm_a),
        ("B: Wider (7.5% OTM)", arm_b),
        ("C: BXMD (30Δ)", arm_c),
        ("D: BXY (2% OTM)", arm_d),
    ]

    baseline_excess = arm_a.get("excess_return_pct", 0)

    for label, arm in arms_data:
        if not arm:
            print(f"{label:<25} {'FAILED':<12}")
            continue

        total_ret = arm.get("abs_return_pct", 0)
        excess = arm.get("excess_return_pct", 0)
        sharpe = arm.get("sharpe", 0)
        sortino = arm.get("sortino", 0)
        max_dd = arm.get("max_drawdown_pct", 0)
        up_cap = arm.get("upside_capture_ratio", 0) * 100
        down_cap = arm.get("downside_capture_ratio", 0) * 100
        
        # Count CC writes from trades
        cc_writes = 0
        premium = 0.0
        
        print(
            f"{label:<25} "
            f"{total_ret:>+10.2f}%  "
            f"{excess:>+10.2f}%  "
            f"{sharpe:>6.2f}  "
            f"{sortino:>6.2f}  "
            f"{max_dd:>8.2f}%  "
            f"{up_cap:>6.1f}%  "
            f"{down_cap:>8.1f}%  "
            f"{'N/A':<12} "
            f"${arm.get('premium_collected', 0):>10,.0f}"
        )

    print()
    print("-" * 125)
    print()

    # === Analysis ===
    print("ANALYSIS")
    print("=" * 100)
    
    # Check Phase A baseline reproduction
    phase_a_baseline = 75.27  # From PR #8
    arm_a_result = arm_a.get("abs_return_pct", 0)
    baseline_diff = arm_a_result - phase_a_baseline
    
    print(f"Baseline Reproduction Check:")
    print(f"  Phase A Arm A (5% OTM, 100% overwrite): +{phase_a_baseline:.2f}%")
    print(f"  Phase B Arm A (5% OTM, 100% overwrite): {arm_a_result:+.2f}%")
    print(f"  Difference: {baseline_diff:+.2f}pp")
    
    if abs(baseline_diff) <= 2.0:
        print(f"  ✅ Within ±2pp tolerance (consistent wiring)")
    else:
        print(f"  ⚠️  Outside ±2pp tolerance (investigate drift)")
    print()

    # KEEP/ABANDON recommendation
    print("KEEP/ABANDON Recommendation:")
    print()
    
    best_arm = None
    best_label = None
    best_improvement = -999
    
    for label, arm in arms_data[1:]:  # Skip baseline
        if not arm:
            continue
        excess_delta = arm.get("excess_return_pct", 0) - baseline_excess
        if excess_delta > best_improvement:
            best_improvement = excess_delta
            best_arm = arm
            best_label = label
    
    if best_improvement >= 2.0:
        print(f"✅ KEEP: {best_label}")
        print(f"   Improvement: {best_improvement:+.2f}pp excess vs SPY vs baseline")
        print(f"   Absolute return: {best_arm.get('abs_return_pct', 0):+.2f}% vs baseline {arm_a.get('abs_return_pct', 0):+.2f}%")
        print(f"   Sharpe: {best_arm.get('sharpe', 0):.2f} vs baseline {arm_a.get('sharpe', 0):.2f}")
        print()
        print(f"   Recommendation: Update production default to {best_label.split(':')[1].strip()}")
    elif best_improvement > 0:
        print(f"⚠️  WEAK: {best_label}")
        print(f"   Improvement: {best_improvement:+.2f}pp excess vs SPY vs baseline")
        print(f"   Below +2pp KEEP threshold")
        print()
        print(f"   Recommendation: Keep defaults unchanged; document findings for Phase C")
    else:
        print(f"❌ ABANDON: All wider-OTM arms underperformed baseline")
        print(f"   Best improvement: {best_improvement:+.2f}pp (worse than baseline)")
        print()
        print(f"   Recommendation: Keep defaults unchanged (5% OTM, 100% overwrite)")
        print(f"   Next: Investigate paid option-level VRP edge_gate (Phase C)")

    print()
    print("=" * 100)
    print(f"Results saved: {output_dir}/")
    print(f"  - {json_path.name}")
    print("=" * 100)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
