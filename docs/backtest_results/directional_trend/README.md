# Directional Trend Overlay — Backtest Results

This directory contains committed backtest results for the directional sleeve trend/momentum overlay strategy.

---

## Quick Start: Reproduce Results

### Prerequisites

```bash
cd /workspace
pip3 install --user structlog pandas numpy yfinance pydantic python-dotenv
```

### Run Full 2020-2024 Bake-off (Expanded Universe)

```bash
export PATH="/home/ubuntu/.local/bin:$PATH"
export PYTHONPATH="/workspace:$PYTHONPATH"

python3 scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --universe expanded \
  --nav 10000 \
  --out docs/backtest_results/directional_trend/2020_2024_expanded_rerun
```

**Expected Output:**
- Baseline Hybrid: +338% (+243pp vs SPY)
- Trend Hybrid: +455% (+360pp vs SPY)
- Improvement: +117pp excess vs SPY
- Runtime: ~30 seconds

---

## Committed Results

### `2020_2024_expanded/summary.json`

**Window**: 2020-01-01 to 2024-12-31  
**Universe**: Expanded (45 names)  
**Initial NAV**: $10,000

#### Headline Metrics

| Strategy | Abs Return | Excess vs SPY | Sharpe | Sortino | Max DD |
|----------|-----------|--------------|--------|---------|--------|
| Baseline Hybrid | +338% | +243pp | 1.19 | 1.72 | -44.1% |
| **Trend Hybrid** | **+455%** | **+360pp** | **1.44** | **2.11** | **-37.6%** |
| **Delta** | **+117pp** | **+117pp** | **+0.25** | **+0.39** | **+6.5pp** |

#### Trade Statistics

| Metric | Baseline | Trend Overlay |
|--------|----------|---------------|
| CC Writes | 306 | 311 |
| CSP Writes | 34 | 89 |
| Directional Buys | 19 | 179 |
| Directional Sells | 8 | 173 |
| Premium Collected | $17,019 | $25,770 |
| Turnover | 2.16x | 26.98x |

**Key Insight**: Higher turnover from trend-following is more than offset by better timing (buying strength, selling weakness).

---

## Parameter Sensitivity

### Test Different SMA Windows

```bash
# SMA50 (shorter-term trend)
python3 scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 --end 2024-12-31 \
  --universe expanded \
  --sma-window 50 \
  --momentum-lookback 63 \
  --out docs/backtest_results/directional_trend/2020_2024_sma50

# SMA250 (longer-term trend)
python3 scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 --end 2024-12-31 \
  --universe expanded \
  --sma-window 250 \
  --momentum-lookback 126 \
  --out docs/backtest_results/directional_trend/2020_2024_sma250
```

### Test SMA-Only (No Dual Momentum)

```bash
python3 scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 --end 2024-12-31 \
  --universe expanded \
  --no-dual-momentum \
  --out docs/backtest_results/directional_trend/2020_2024_sma_only
```

### Custom Universe

```bash
python3 scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 --end 2024-12-31 \
  --custom-tickers SPY QQQ IWM EFA TLT \
  --out docs/backtest_results/directional_trend/2020_2024_etf_sleeve
```

---

## Interpretation Guide

### Success Criteria

✅ **Strong improvement**: Excess delta ≥ 2pp AND Sharpe delta > 0.1  
⚠️ **Marginal improvement**: Excess delta > 0 OR Sharpe delta > 0  
❌ **No improvement**: Excess delta ≤ 0 AND Sharpe delta ≤ 0

### Risk Metrics

- **Max DD improvement**: Lower is better (less drawdown)
- **Sharpe/Sortino improvement**: Higher is better (risk-adjusted returns)
- **Beta shift**: Closer to 1.0 = more SPY-like exposure

---

## Limitations & Caveats

### Premium Model

- Uses Black-Scholes with realized volatility (21-day)
- **NOT** market implied volatility
- Wheel premium estimates are conservative

### Transaction Costs

- No explicit spread or commission modeling
- Real trading would have ~$5-15 per option round-trip
- High turnover (27x) may erode gains in practice

### Lookback Bias

- Universe filtered by IPO date (avoids pre-IPO data)
- SMA200 requires 200 days of history (handled)

---

## Next Steps

1. **Validate on other windows**: Test 2015-2024, 2018-2024
2. **Parameter optimization**: Grid search over SMA/momentum windows
3. **Live paper track**: Deploy to new track (do NOT contaminate `wheel-10k-paper-v1`)
4. **Walk-forward validation**: Train on 2015-2019, test on 2020-2024

---

## Files in This Directory

```
docs/backtest_results/directional_trend/
├── README.md (this file)
└── 2020_2024_expanded/
    └── summary.json (committed results)
```

---

## References

- **Design Doc**: `docs/DIRECTIONAL_SLEEVE_TREND.md`
- **Script**: `scripts/run_directional_trend_bakeoff.py`
- **Engine**: `src/backtesting/wheel_hybrid/directional_trend.py`
- **Tests**: `tests/test_directional_trend.py`

---

**Last Updated**: 2026-09-25  
**PR**: #5
