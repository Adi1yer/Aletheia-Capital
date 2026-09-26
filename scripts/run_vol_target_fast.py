#!/usr/bin/env python3
"""
Vol-Target Overlay: Post-process baseline results with 15% vol targeting.
Much faster than re-running full backtest - just scales existing returns.
"""

import json
import math
from pathlib import Path
from typing import Dict, List, Tuple

def calculate_metrics(
    equity_curve: List[float],
    spy_curve: List[float],
    years: float
) -> Dict:
    """Calculate performance metrics from equity curves."""
    
    # Returns
    start_nav = equity_curve[0]
    end_nav = equity_curve[-1]
    abs_return_pct = ((end_nav - start_nav) / start_nav) * 100
    ann_return_pct = (((end_nav / start_nav) ** (1.0 / years)) - 1) * 100
    
    spy_start = spy_curve[0]
    spy_end = spy_curve[-1]
    spy_return_pct = ((spy_end - spy_start) / spy_start) * 100
    spy_ann_return_pct = (((spy_end / spy_start) ** (1.0 / years)) - 1) * 100
    
    excess_return_pct = abs_return_pct - spy_return_pct
    excess_ann_return_pct = ann_return_pct - spy_ann_return_pct
    
    # Daily returns
    daily_returns = []
    for i in range(1, len(equity_curve)):
        ret = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
        daily_returns.append(ret)
    
    # Sharpe (annualized, assuming 252 trading days)
    if daily_returns:
        mean_return = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_return) ** 2 for r in daily_returns) / len(daily_returns)
        daily_vol = math.sqrt(variance)
        ann_vol = daily_vol * math.sqrt(252)
        sharpe = (ann_return_pct / 100) / ann_vol if ann_vol > 0 else 0
        
        # Sortino (downside deviation)
        downside_returns = [r for r in daily_returns if r < 0]
        if downside_returns:
            downside_var = sum(r ** 2 for r in downside_returns) / len(daily_returns)
            downside_vol = math.sqrt(downside_var) * math.sqrt(252)
            sortino = (ann_return_pct / 100) / downside_vol if downside_vol > 0 else 0
        else:
            sortino = 0
    else:
        sharpe = 0
        sortino = 0
        ann_vol = 0
    
    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0
    current_dd = 0
    
    for nav in equity_curve:
        if nav > peak:
            peak = nav
        dd = ((nav - peak) / peak) * 100
        if dd < max_dd:
            max_dd = dd
        current_dd = dd
    
    # SPY max drawdown
    spy_peak = spy_curve[0]
    spy_max_dd = 0
    
    for spy_nav in spy_curve:
        if spy_nav > spy_peak:
            spy_peak = spy_nav
        dd = ((spy_nav - spy_peak) / spy_peak) * 100
        if dd < spy_max_dd:
            spy_max_dd = dd
    
    return {
        "start_nav": start_nav,
        "end_nav": end_nav,
        "abs_return_pct": round(abs_return_pct, 2),
        "ann_return_pct": round(ann_return_pct, 2),
        "spy_return_pct": round(spy_return_pct, 2),
        "spy_ann_return_pct": round(spy_ann_return_pct, 2),
        "excess_return_pct": round(excess_return_pct, 2),
        "excess_ann_return_pct": round(excess_ann_return_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "spy_max_drawdown_pct": round(spy_max_dd, 2),
        "current_drawdown_pct": round(current_dd, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "ann_volatility_pct": round(ann_vol * 100, 2),
        "years": round(years, 2)
    }


def apply_vol_target(
    baseline_curve: List[float],
    spy_curve: List[float],
    target_vol: float = 0.15,
    lookback_days: int = 63
) -> Tuple[List[float], List[float], float]:
    """
    Apply vol-targeting to baseline equity curve.
    
    Returns:
        (vol_targeted_curve, exposure_scalars, avg_exposure)
    """
    
    # Calculate baseline daily returns
    baseline_returns = []
    for i in range(1, len(baseline_curve)):
        ret = (baseline_curve[i] - baseline_curve[i-1]) / baseline_curve[i-1]
        baseline_returns.append(ret)
    
    # Apply vol-targeting
    vol_targeted_curve = [baseline_curve[0]]  # Start with same initial NAV
    exposure_scalars = []
    
    for i in range(len(baseline_returns)):
        # Calculate trailing realized vol
        if i < lookback_days:
            # Not enough history, use full exposure
            exposure = 1.0
        else:
            trailing_returns = baseline_returns[i - lookback_days:i]
            mean_return = sum(trailing_returns) / len(trailing_returns)
            variance = sum((r - mean_return) ** 2 for r in trailing_returns) / len(trailing_returns)
            daily_vol = math.sqrt(variance)
            realized_vol = daily_vol * math.sqrt(252)  # Annualize
            
            # Scale exposure
            if realized_vol > 0:
                exposure = min(1.0, target_vol / realized_vol)
            else:
                exposure = 1.0
        
        exposure_scalars.append(exposure)
        
        # Apply vol-targeted return
        vol_targeted_return = baseline_returns[i] * exposure
        new_nav = vol_targeted_curve[-1] * (1 + vol_targeted_return)
        vol_targeted_curve.append(new_nav)
    
    avg_exposure = sum(exposure_scalars) / len(exposure_scalars) if exposure_scalars else 1.0
    
    return vol_targeted_curve, exposure_scalars, avg_exposure


def main():
    print("=" * 80)
    print("VOL-TARGET OVERLAY: POST-PROCESSING BASELINE 80/20")
    print("=" * 80)
    print()
    
    results = {}
    
    for window in ["2020_2024", "2010_2024"]:
        print(f"Processing {window}...")
        
        # Load baseline equity curve
        equity_path = Path(f"results/income_drip_sharpe_v1/sleeve_grid/{window}/equity_curve_sleeve_80_20.csv")
        
        if not equity_path.exists():
            print(f"  ERROR: {equity_path} not found")
            continue
        
        # Parse CSV
        baseline_curve = []
        spy_curve = []
        
        with open(equity_path) as f:
            header = f.readline()  # Skip header
            for line in f:
                parts = line.strip().split(',')
                if len(parts) >= 3:
                    baseline_curve.append(float(parts[1]))  # strategy_value
                    spy_curve.append(float(parts[2]))  # benchmark_value
        
        if not baseline_curve:
            print(f"  ERROR: No data in {equity_path}")
            continue
        
        # Determine years
        if window == "2020_2024":
            years = 4.99
        else:  # 2010_2024
            years = 14.97
        
        # Calculate baseline metrics
        baseline_metrics = calculate_metrics(baseline_curve, spy_curve, years)
        
        print(f"  Baseline: Sharpe {baseline_metrics['sharpe']:.3f}, Return {baseline_metrics['ann_return_pct']:.2f}%")
        
        # Apply vol-targeting
        vol_targeted_curve, exposures, avg_exposure = apply_vol_target(
            baseline_curve,
            spy_curve,
            target_vol=0.15,
            lookback_days=63
        )
        
        # Calculate vol-targeted metrics
        vol_metrics = calculate_metrics(vol_targeted_curve, spy_curve, years)
        vol_metrics["target_vol_pct"] = 15.0
        vol_metrics["lookback_days"] = 63
        vol_metrics["avg_exposure_pct"] = round(avg_exposure * 100, 1)
        vol_metrics["min_exposure_pct"] = round(min(exposures) * 100, 1) if exposures else 100.0
        vol_metrics["max_exposure_pct"] = round(max(exposures) * 100, 1) if exposures else 100.0
        
        print(f"  Vol-Target: Sharpe {vol_metrics['sharpe']:.3f}, Return {vol_metrics['ann_return_pct']:.2f}%")
        print(f"  Avg Exposure: {vol_metrics['avg_exposure_pct']:.1f}%")
        
        # Compare
        sharpe_delta = vol_metrics['sharpe'] - baseline_metrics['sharpe']
        print(f"  Sharpe Delta: {sharpe_delta:+.3f}")
        
        results[window] = {
            "baseline": baseline_metrics,
            "vol_target": vol_metrics,
            "sharpe_delta": round(sharpe_delta, 3)
        }
        print()
    
    # Apply KEEP bar
    print("=" * 80)
    print("KEEP / ABANDON VERDICT")
    print("=" * 80)
    print()
    
    if "2020_2024" in results and "2010_2024" in results:
        delta_2020 = results["2020_2024"]["sharpe_delta"]
        delta_2010 = results["2010_2024"]["sharpe_delta"]
        
        improves_both = (delta_2020 >= 0 and delta_2010 >= 0)
        
        print(f"2020-2024: Sharpe {delta_2020:+.3f} {'✓' if delta_2020 >= 0 else '✗'}")
        print(f"2010-2024: Sharpe {delta_2010:+.3f} {'✓' if delta_2010 >= 0 else '✗'}")
        print()
        
        if improves_both:
            verdict = "KEEP"
            print(f"✓ KEEP - Vol-targeting improves Sharpe on BOTH windows")
        else:
            verdict = "ABANDON"
            print(f"✗ ABANDON - Vol-targeting does not improve Sharpe on BOTH windows")
        
        results["verdict"] = verdict
    else:
        results["verdict"] = "INCOMPLETE"
    
    # Save results
    output_dir = Path("results/income_drip_sharpe_v1/vol_target")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = output_dir / "vol_target_results.json"
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print()
    print(f"Results saved to: {output_path}")
    print()
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
