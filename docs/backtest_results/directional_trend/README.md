# Directional Trend Overlay — Backtest Results

**Status**: ❌ **FAILED** — Trend overlay underperforms citeable baseline by -6.7pp

This directory contains committed backtest results showing that the directional trend/momentum overlay does NOT improve the beat-SPY path on an apples-to-apples comparison.

---

## Key Finding: Baseline Validated, Overlay Failed

### Citeable Bluechip Results (2020-2024)

**Baseline Hybrid**: +55.0% (-40.3% vs SPY) — ✅ Matches whitepaper exactly  
**Trend Overlay**: +48.3% (-47.0% vs SPY) — ❌ WORSE by -6.7pp

**Conclusion**: Trend overlay creates excessive turnover (1.56x → 39.69x) that erodes gains despite collecting more premium.

### Non-Citeable Expanded Results (2020-2024)

**⚠️ DO NOT CITE**: Expanded universe shows +117pp improvement, but this is **NOT RELIABLE** due to:
- Survivorship bias (NVDA mega-winner)
- Problematic names (XLNX acquired/delisted)
- Selection bias favoring winners

---

## Reproduce Results

### Prerequisites

```bash
cd /workspace
pip3 install --user structlog pandas numpy yfinance pydantic python-dotenv
export PATH="/home/ubuntu/.local/bin:$PATH"
export PYTHONPATH="/workspace:$PYTHONPATH"
```

### Run Citeable Bluechip Bake-off

```bash
python3 scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --universe bluechip \
  --nav 10000 \
  --out docs/backtest_results/directional_trend/2020_2024_bluechip_rerun
```

**Expected Output:**
- Baseline: +55.0% (-40.3% vs SPY)
- Trend: +48.3% (-47.0% vs SPY)
- Delta: -6.7pp underperformance
- Runtime: ~5 seconds

---

## Committed Results

### `2020_2024_bluechip/summary.json` (CITEABLE)

**Window**: 2020-01-01 to 2024-12-31  
**Universe**: Bluechip (6 names: F, T, BAC, INTC, PFE, GE)  
**Initial NAV**: $10,000

#### Headline Metrics

| Strategy | Abs Return | Excess vs SPY | Sharpe | Sortino | Max DD | Turnover |
|----------|-----------|--------------|--------|---------|--------|----------|
| Baseline Hybrid | +55.0% | -40.3pp | 0.50 | 0.69 | -37.7% | 1.56x |
| **Trend Hybrid** | **+48.3%** | **-47.0pp** | **0.47** | **0.65** | **-36.0%** | **39.69x** |
| **Delta** | **-6.7pp** ❌ | **-6.7pp** ❌ | **-0.03** ❌ | **-0.04** ❌ | **+1.7pp** | **+38x** ❌ |

**✅ Baseline Validation**: Matches whitepaper exactly (+55.0%, -40.3% vs SPY, Sharpe 0.50, $6,981 premium, 195 CC writes)

**❌ Trend Overlay Failure**: Underperforms despite +$1,680 more premium. Excessive turnover (39x vs 1.6x) creates timing/churn losses.

---

### `2020_2024_expanded/summary.json` (NON-CITEABLE)

**⚠️ WARNING**: DO NOT CITE — Survivorship bias, mega-winner bias (NVDA), problematic names (XLNX)

| Strategy | Abs Return | Excess vs SPY | Sharpe |
|----------|-----------|--------------|--------|
| Baseline | +338% | +243pp | 1.19 |
| Trend | +455% | +360pp | 1.44 |
| Delta | +117pp | +117pp | +0.25 |

**Not Reliable**: Expanded results are an optimistic upper bound, not evidence of beat-SPY capability.

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
