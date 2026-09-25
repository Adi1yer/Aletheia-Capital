# VIX-Gated Wheel-Hybrid Backtest Results

## Executive Summary

Implemented **FREE VIX-based regime gating** for wheel-hybrid strategy and ran comprehensive bake-off vs always-on baseline using the **real wheel-hybrid engine**.

**Key Result:** VIX-gated strategy **underperformed** always-on by **-21.22%** over 2020-2024 bluechip universe.

**Status:** ❌ **FAIL** (did not beat always-on by ≥2%)

## Honest Disclaimers

1. **Index-level vol signal** — VIX is SPX implied vol, NOT individual stock IV
2. **Free public data only** — CBOE VIX via yfinance (no API key)
3. **Regime signal, not edge** — NOT a claim about name-level VRP or beat-SPY
4. **Real engine** — Uses production wheel-hybrid backtest (not simplified simulator)
5. **Auditable results** — Committed VIX cache + JSON for reproducibility

## Backtest Configuration

| Parameter | Value |
|-----------|-------|
| Window | 2020-01-02 to 2024-12-31 (5 years) |
| Universe | Bluechip 6: F, T, BAC, INTC, PFE, GE |
| Initial Capital | $10,000 |
| Wheel Allocation | 70% |
| VIX Gate Threshold | VRP > 10% (VIX - RV > 10% of RV) |
| Benchmark | ^SPXTR (SPY total return) |

## Results

### Performance Summary

| Strategy | Total Return | Sharpe | Premium Collected | CC Writes |
|----------|--------------|--------|-------------------|-----------|
| SPY Benchmark | **+95.30%** | N/A | N/A | N/A |
| **Always-On** | **+55.00%** | 0.50 | $6,981 | 195 |
| **VIX-Gated** | **+33.78%** | 0.36 | $1,491 | 54 |

### Alpha Analysis

| Comparison | Alpha |
|------------|-------|
| VIX-Gated vs Always-On | **-21.22%** ❌ |
| VIX-Gated vs SPY | **-61.51%** ❌ |

### Edge Gate Statistics

| Metric | Value |
|--------|-------|
| Writes Allowed | 1,472 (14.7%) |
| Blocked (Low VRP) | 8,534 (85.3%) |
| Blocked (No IV) | 0 (0%) |
| **Block Rate** | **85.3%** |

## Why VIX-Gated Underperformed

### Root Cause: VRP Inversion

VIX (SPX implied vol) was frequently **below** individual stock realized vol during 2020-2024:

```
VRP = (VIX - Realized Vol) / Realized Vol

Example from 2024-12-26:
- VIX: 14.7% (index vol)
- F realized vol: 23.4% (name vol)
- VRP: -37% (NEGATIVE!)
- Gate blocked write (VRP < 10% threshold)
```

### Why This Happens

1. **Index vol ≠ name vol** — SPX diversification reduces volatility vs single stocks
2. **Correlation matters** — Individual stocks often more volatile than index
3. **2020-2024 low-VIX regime** — Index vol compressed more than name vol
4. **No single-name IV data** — Using index proxy for stock-specific decisions fails

### What VIX Actually Measures

- **VIX = SPX 30-day implied volatility** (from SPX option prices)
- Represents **market-wide** vol expectations
- Does NOT capture **name-specific** vol factors:
  - Earnings risk
  - Sector rotation
  - Idiosyncratic shocks
  - Single-name option skew

## Technical Implementation

### VIX Provider

- **Source:** CBOE ^VIX via yfinance (free, no API key)
- **Coverage:** 2000-01-01 to present (6,725 days cached)
- **Cache:** Local CSV at `data/vix_cache/vix_daily.csv`
- **Protocol:** Implements `IVProvider` interface (get_atm_iv, get_iv_rank, get_iv_rv_spread)

### Integration

- **Engine:** Uses existing `WheelHybridBacktest` (real premium model, portfolio, metrics)
- **Gate:** `EdgeGate` with VRP threshold (min_vrp=0.10)
- **Regime:** Optional `RegimeDetector` (not used in this test)

### Reproducibility

```bash
# Run bake-off
python3 scripts/run_vrp_bakeoff.py \
  --start 2020-01-02 \
  --end 2024-12-31 \
  --nav 10000 \
  --universe bluechip \
  --iv-source vix \
  --min-vrp 0.10 \
  --out docs/backtest_results/vix_gated

# Results
- docs/backtest_results/vix_gated/bakeoff_2020-01-02_2024-12-31.json
- data/vix_cache/vix_daily.csv (committed for CI)
```

## Comparison to Prior Work

| Metric | Legacy (This Test) | VIX-Gated (This Test) | Existing Bluechip |
|--------|-------------------|----------------------|-------------------|
| Final NAV | $15,500 | $13,378 | $15,500 |
| Total Return | +55.0% | +33.8% | +55.0% |
| CC Writes | 195 | 54 | 195 |
| Premium | $6,981 | $1,491 | $6,981 |
| Sharpe | 0.50 | 0.36 | 0.50 |

Legacy matches existing committed backtest results (`docs/backtest_results/wheel_hybrid/2020_2024_10k_bluechip/summary.json`), confirming we're using the **real engine**.

## Conclusion

### What We Learned

1. **VIX is not a name-level IV proxy** — Index vol ≠ stock vol
2. **Free VIX data works** — Infrastructure is solid, data loads reliably
3. **Gate logic works** — Correctly blocks writes when VRP < threshold
4. **Real engine produces citeable results** — Not a toy simulator

### Why This Failed

- **Wrong signal for decision** — Using index vol to gate stock option writes
- **VRP inverted** — VIX < name RV for 85% of opportunities
- **Strategy mismatch** — VIX measures **market risk**, not **name-specific edge**

### What Would Help

1. **Single-name IV data** — Polygon/Theta/OPRA for stock-specific IV
2. **VIX for regime only** — Use VIX to detect market stress (> 30 → defensive), not for name writes
3. **Hybrid approach** — VIX macro filter + name IV for micro decisions
4. **Different universe** — Test on lower-priced stocks (wheel-classic)

## Status

| Requirement | Status |
|-------------|--------|
| FREE VIX data (no API key) | ✅ |
| Integrate with existing engine | ✅ |
| Real bake-off (not toy simulator) | ✅ |
| Committed auditable results | ✅ |
| Honest labeling (regime signal) | ✅ |
| Tests passing | ✅ (8/8) |
| ≥2% outperformance | ❌ (-21%) |

**Final Verdict:** Infrastructure complete and validated. Strategy hypothesis (use VIX as name IV proxy) **falsified** by data. This is a **scientifically valuable negative result**.

## Files

- `src/backtesting/wheel_hybrid/vix_iv_provider.py` — VIX provider (259 lines)
- `scripts/run_vrp_bakeoff.py` — Updated to support `--iv-source vix`
- `tests/test_vix_iv_provider.py` — 8 tests (all passing)
- `docs/backtest_results/vix_gated/bakeoff_2020-01-02_2024-12-31.json` — Results
- `data/vix_cache/vix_daily.csv` — VIX data (6,725 days, committed)
