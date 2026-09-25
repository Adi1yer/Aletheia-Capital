#!/usr/bin/env python3
"""Generate synthetic fixture backtest data for documentation purposes."""

import json
from pathlib import Path

OUTPUT_DIR = Path("data/backtests/wheel_hybrid/fixture_sample")

def main():
    """Generate fixture data."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Summary metrics (synthetic)
    summary = {
        "start_nav": 10000.0,
        "end_nav": 13245.67,
        "abs_return_pct": 32.46,
        "abs_return_usd": 3245.67,
        "spy_return_pct": 35.2,
        "excess_return_pct": -2.74,
        "excess_return_usd": -274.33,
        "max_drawdown_pct": -16.8,
        "current_drawdown_pct": 0.0,
        "sharpe": 0.74,
        "sortino": 0.98,
        "beta": 0.68,
        "correlation": 0.79,
        "alpha_annual_pct": 1.45,
        "hit_rate_pct": 53.8,
        "hit_sessions": 542,
        "total_sessions": 1008,
        "turnover": 0.38,
        "premium_collected": 2847.23,
        "trade_counts": {
            "buys": 87,
            "sells": 82,
            "cc_writes": 156,
            "csp_writes": 94,
            "btc_calls": 68,
            "btc_puts": 42,
            "assignments_call": 54,
            "assignments_put": 31,
        },
        "note": "SYNTHETIC FIXTURE DATA for demonstration purposes only. "
                "Run scripts/run_wheel_hybrid_backtest.py for real simulation.",
    }
    
    # Assumptions
    assumptions = {
        "start_date": "2020-01-01",
        "end_date": "2024-12-31",
        "initial_nav": 10000.0,
        "wheel_pct": 0.7,
        "directional_pct": 0.3,
        "max_wheel_names": 4,
        "max_directional_names": 5,
        "rf_rate": 0.0,
        "vol_window": 21,
        "universe": ["F", "T", "SOFI", "NIO", "PLUG", "VALE"],
        "note": "Fixture assumptions - not from real backtest",
    }
    
    # Save files
    with open(OUTPUT_DIR / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    with open(OUTPUT_DIR / "assumptions.json", "w") as f:
        json.dump(assumptions, f, indent=2)
    
    readme = """# Fixture Sample Backtest Data

**WARNING**: This is **synthetic fixture data** for demonstration purposes only.

The data in this directory shows the expected output format of the wheel hybrid backtest,
but the numbers are not from a real simulation.

## To Generate Real Backtest Data

Run the backtest CLI:

```bash
poetry run python scripts/run_wheel_hybrid_backtest.py \\
  --start 2020-01-01 \\
  --end 2024-12-31 \\
  --nav 10000 \\
  --out data/backtests/wheel_hybrid/2020_2024_10k
```

This will:
1. Download historical price data via yfinance
2. Simulate wheel strategy with synthetic option pricing
3. Output real results to the specified directory

## Files in This Directory

- `summary.json` - Performance metrics (Sharpe, DD, alpha, etc.)
- `assumptions.json` - Backtest configuration snapshot
- `README.md` - This file

Real backtests will also include:
- `equity_curve.csv` - Daily NAV and SPY levels
- `trades.csv` - Complete trade log

## Interpreting the Fixture Results

The fixture shows:
- **Abs Return**: +32.5% over 5 years (~5.8% CAGR)
- **SPY Return**: +35.2% (hypothetical, actual 2020-2024 was higher)
- **Excess**: -2.7% (underperformed SPY, but see alpha)
- **Alpha**: +1.45% annually (positive despite negative excess, due to beta < 1)
- **Beta**: 0.68 (lower market exposure than SPY)
- **Max DD**: -16.8% (vs SPY ~-25% in 2022 bear)
- **Sharpe**: 0.74 (decent risk-adjusted return)
- **Premium Collected**: $2,847 (cumulative option income)

**Interpretation**: Strategy captured ~68% of SPY's upside (beta) but with lower drawdown.
Positive alpha suggests the option premium added value after adjusting for market exposure.
However, in a strong bull market (2020-2024 was post-COVID recovery), capped upside from
covered calls dragged total returns.

This is **expected behavior** for a wheel strategy in a melt-up regime. The thesis claims
risk-adjusted outperformance (Sharpe, alpha), not absolute return maximization.

Real backtest results may differ significantly due to:
- Actual historical prices and volatility
- Bid-ask spreads and slippage (not modeled in fixtures)
- Assignment timing and roll decisions
- Universe selection and liquidity constraints
"""
    
    with open(OUTPUT_DIR / "README.md", "w") as f:
        f.write(readme)
    
    print(f"✓ Fixture data generated: {OUTPUT_DIR}/")
    print(f"  - summary.json")
    print(f"  - assumptions.json")
    print(f"  - README.md")
    print()
    print("NOTE: This is synthetic data for demonstration only.")
    print("Run scripts/run_wheel_hybrid_backtest.py for real simulation.")


if __name__ == "__main__":
    main()
