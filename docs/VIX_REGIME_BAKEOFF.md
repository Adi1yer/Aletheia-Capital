# VIX Regime Bake-Off Results

## Executive Summary

This document reports the results of a **VIX-gated regime control** bake-off for the wheel-hybrid strategy. The goal was to test whether using free public VIX data to gate covered call writes would improve returns vs an always-on baseline.

**Key Finding:** VIX-gated strategy **underperformed** always-on by **-10.02%** over 2020-2024.

**Status vs ≥2% hurdle:** ✗ FAIL

## Important Disclaimers

1. **This is regime simulation only** — NOT a claim about single-name IV edge or VRP mispricing
2. **Free VIX data** — Uses CBOE VIX (^VIX via yfinance), no paid option IV data
3. **Simplified backtest** — Does not model execution, slippage, chain selection, assignment, etc.
4. **Honest labeling** — Results are reported accurately; the thesis was NOT validated in this test

## Backtest Configuration

| Parameter | Value |
|-----------|-------|
| Window | 2020-01-01 to 2024-12-31 |
| Universe | Bluechip 10: AAPL, MSFT, JPM, JNJ, PG, KO, DIS, BA, CAT, MMM |
| Initial Capital | $10,000 |
| Wheel Allocation | 70% |
| VIX Gate Thresholds | 30th/70th percentile |

## Results

### Performance Summary

| Strategy | Total Return | Sharpe | Premium Collected |
|----------|--------------|--------|-------------------|
| SPY Benchmark | **+95.30%** | N/A | N/A |
| Always-On Wheel | **+36.84%** | 1.172 | $2,238.72 |
| VIX-Gated Wheel | **+26.81%** | 1.214 | $1,236.28 |

### Alpha Analysis

| Comparison | Alpha |
|------------|-------|
| VIX-Gated vs Always-On | **-10.02%** |
| VIX-Gated vs SPY | **-68.48%** |

## Regime Gating Logic

The VIX-gated strategy uses a **VIX percentile rank** approach:

```
VIX Percentile < 30th: Intensity = 0.3-0.7 (hold more delta, write less)
VIX Percentile 30-70th: Intensity = 0.7-1.0 (neutral zone)
VIX Percentile > 70th: Intensity = 1.0 (write aggressively)
```

**Intensity** controls what fraction of eligible lots get covered calls written.

## Why VIX-Gated Underperformed

Potential reasons for underperformance:

1. **2020-2024 was mostly low VIX** — VIX stayed crushed for much of the period except COVID spike
2. **Conservative gating penalized returns** — Holding back premium in low-VIX environments lost potential gains
3. **Simplified simulator doesn't capture realistic execution** — Real wheel would have more nuanced lot management
4. **No transaction costs modeled** — More frequent regime changes might add slippage in reality
5. **Bluechip universe may not benefit from vol regime** — High-quality stocks have stable IV

## Code and Reproducibility

### Run Bake-Off

```bash
python3 scripts/run_vrp_bakeoff.py --preset bluechip-2020-2024 --capital 10000
```

### Key Files

- `src/backtesting/wheel_hybrid/vix_provider.py` — Free VIX data via yfinance
- `src/backtesting/wheel_hybrid/edge_gate.py` — Regime gating logic
- `src/backtesting/wheel_hybrid/simulator.py` — Wheel-hybrid backtest engine
- `scripts/run_vrp_bakeoff.py` — Bake-off runner
- `tests/test_vix_gated_wheel.py` — Test suite (12 tests, all passing)

### Results Files

- `docs/backtest_results/vix_gated/summary_2020-01-01_2024-12-31.json` — Metrics
- `docs/backtest_results/vix_gated/equity_curves_2020-01-01_2024-12-31.csv` — Daily equity

## Future Work (Out of Scope)

To improve VIX-gated strategy:

1. **Test longer windows** — Include 2008, 2015-2016 high-VIX periods
2. **Refine intensity mapping** — Current thresholds may be too conservative
3. **Add realized vol comparison** — VIX vs SPY realized vol ratio (not just percentile)
4. **Test on wheel-classic universe** — Lower-priced stocks (F, SOFI, NOK) might show different regime sensitivity
5. **Model realistic execution** — Add slippage, chain selection, assignment

## Conclusion

The free VIX-gated regime control **did not improve** wheel-hybrid returns in this test. The strategy:
- ✗ Failed to beat always-on by ≥2%
- ✗ Failed to beat SPY benchmark
- ✓ Maintained similar Sharpe ratio (1.214 vs 1.172)
- ✓ Reduced premium collection (as intended during low-VIX periods)

**This negative result is scientifically valid and important.** It suggests that:
- Naive VIX percentile gating is not sufficient for alpha
- The 2020-2024 period did not favor vol regime strategies
- More sophisticated gating rules or different universes might be needed

The implementation is **production-ready** for testing alternative gating rules and time windows, but the current VIX-percentile approach does not validate the VRP thesis for this universe and period.
