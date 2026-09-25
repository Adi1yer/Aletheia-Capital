# VIX/SPY Index Regime Bake-Off

## Objective

Test whether a **FREE** VIX-based index regime control can improve wheel-hybrid backtest returns vs an always-on baseline, using only public data (no paid API keys).

## Methodology

### Index-Level Regime Signal (Correct Approach)

Uses **VIX vs SPY realized vol** to determine market volatility regime:

- **VIX**: CBOE Volatility Index (SPX 30-day implied vol) via yfinance `^VIX`
- **SPY RV**: S&P 500 ETF realized volatility calculated from price history
- **Index VRP**: `(VIX - SPY_RV) / SPY_RV`

This is a **macro/index regime signal**, NOT name-specific IV:
- ✅ Correct: Compare VIX (index IV) to SPY realized vol (index RV)
- ❌ Wrong (previous attempt): Compare VIX to individual stock RV (F, BAC, INTC, etc.)

### Regime States (RegimeDetector)

Three regime states control covered call write intensity:

1. **HARVEST_VRP**: Index VRP > 10% → write CCs aggressively
   - VIX is rich vs SPY realized vol → harvest volatility premium
   
2. **HOLD_DELTA**: Index VRP < -5% → skip/thin CC writes
   - VIX is cheap vs SPY realized vol → preserve equity beta
   
3. **DEFENSIVE**: SPY RV > 40% OR index VRP < -10% → skip CC writes
   - Market crash / vol spike → reduce risk, raise cash

Regime transitions require 3+ consecutive days confirmation (hysteresis to avoid whipsaw).

### Backtest Configuration

- **Period**: 2020-01-01 to 2024-12-31 (5 years, including COVID crash + recovery)
- **Universe**: Bluechip (F, T, BAC, INTC, PFE, GE)
- **Initial NAV**: $10,000
- **Allocation**: 70% wheel / 30% directional
- **Benchmark**: SPY total return (`^SPXTR`)
- **Data**: 100% free (yfinance for prices & VIX, no Polygon/Theta)

## Results

| Metric | Legacy (Always-On) | VIX/SPY Regime | Delta |
|--------|-------------------:|---------------:|------:|
| **Absolute Return** | +55.00% | +36.78% | **-18.22%** |
| **vs SPY** | -40.30% | -58.51% | -18.21% |
| **Sharpe Ratio** | 0.50 | 0.40 | -0.10 |
| **Sortino Ratio** | 0.69 | 0.57 | -0.12 |
| **Alpha (annual)** | -0.63% | -3.38% | -2.75% |
| **Max Drawdown** | -37.67% | -37.57% | +0.10% |
| **Premium Collected** | $6,981 | $4,999 | -$1,982 |
| **CC Writes** | 195 | 119 | -76 |
| **Trade Turnover** | 1.56 | 0.97 | -0.59 |

### Key Findings

1. **VIX/SPY regime underperformed by -18.22%** vs always-on baseline
   - Failed ≥2% improvement hurdle by wide margin
   
2. **Regime was too conservative**: Only 119 CC writes vs 195 baseline (61% write rate)
   - Regime detector spent extended periods in DEFENSIVE mode (late 2024)
   - Skipped profitable overwrite opportunities
   
3. **Index VRP signal worked correctly**: Regime transitions observed based on VIX vs SPY RV
   - Logs confirm defensive mode triggered when appropriate
   - Hysteresis prevented rapid state changes
   
4. **Threshold sensitivity**: Current thresholds may be too tight for bluechip bluechips
   - `harvest_min_vrp=0.10` (10% index VRP to harvest)
   - `hold_max_vrp=-0.05` (-5% index VRP to hold delta)
   - `defensive_rv_spike=0.40` (40% SPY RV to go defensive)

## Why Previous VIX Attempt Failed

The **first VIX bake-off** (now superseded) made a fundamental error:

### Wrong Approach (Name-Level VIX Mismatch)
```python
# ❌ WRONG: Used VIX as ticker-level IV for name-level VRP gate
edge_gate.should_write_cc(
    ticker="F",  # Ford stock
    realized_vol=ford_rv,  # Ford's 30% realized vol
    iv=vix,  # 18% SPX implied vol ← MISMATCH!
)
# Result: VRP = (0.18 - 0.30) / 0.30 = -40% (negative)
# Blocked 85% of writes because index vol < single-stock vol
```

**Why this was wrong:**
- VIX measures SPX index vol (~16-20% typical)
- Individual stocks have higher vol than index due to idiosyncratic risk
  - Ford: ~25-35% vol
  - BAC: ~20-30% vol
  - INTC: ~25-40% vol
- Comparing VIX to stock RV creates systematic negative VRP
- This isn't a regime signal; it's a category error

### Correct Approach (Index Regime)
```python
# ✅ CORRECT: Compare VIX to SPY RV (both index measures)
regime_detector.update(
    vrp_avg=compute_index_vrp(vix, spy_rv),  # Index VRP
    rv_avg=spy_rv,  # SPY realized vol
)
# VIX = 20%, SPY RV = 15% → VRP = +33% → HARVEST mode
# VIX = 15%, SPY RV = 18% → VRP = -17% → HOLD_DELTA mode
```

## Conclusions

### Technical Implementation: ✅ SUCCESS

1. **Index regime correctly wired**: VIX vs SPY RV, not name-level mismatch
2. **RegimeDetector integration works**: Engine updates regime daily, controls writes
3. **FREE data only**: yfinance VIX + SPY prices, no API keys
4. **Tests green**: `test_vix_regime_provider.py` validates index signals

### Trading Performance: ❌ FAIL

1. **VIX/SPY regime underperforms always-on by -18.22%**
   - Misses ≥2% improvement hurdle
   - Premium collected: $4,999 vs $6,981 baseline (-28%)
   
2. **Regime too conservative for 2020-2024 period**
   - Stayed defensive too long (late 2024 vol spike)
   - Missed profitable CC opportunities during melt-ups
   
3. **Threshold tuning required** if regime approach is pursued:
   - Loosen DEFENSIVE trigger (maybe 45-50% SPY RV)
   - Tighten HARVEST_VRP requirement (maybe 5% instead of 10%)
   - Test on different market periods (2022 bear, 2023 rally separately)

### Recommendation

**Do NOT deploy VIX/SPY regime to live trading** without significant tuning and out-of-sample validation:

- Current thresholds underperform on 2020-2024 bluechip
- 5-year backtest is not sufficient for regime strategy validation
- Consider:
  1. Parameter sweep across regime thresholds
  2. Walk-forward optimization with out-of-sample testing
  3. Separate bull/bear/sideways period analysis
  4. Compare to simpler rules (e.g., "skip CC when VIX < 15")

**Always-on baseline (+55% return) remains the production default** until regime approach proves ≥2% improvement consistently.

## How to Reproduce

```bash
# Run VIX/SPY regime bake-off (2020-2024 bluechip)
python3 scripts/run_vrp_bakeoff.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --nav 10000 \
  --iv-source vix-regime \
  --out docs/backtest_results/vix_gated

# Results saved to:
# - docs/backtest_results/vix_gated/bakeoff_2020-01-01_2024-12-31.json
```

## Files

- `src/backtesting/wheel_hybrid/vix_regime_provider.py`: FREE VIX/SPY index regime provider
- `src/backtesting/wheel_hybrid/regime.py`: RegimeDetector with HARVEST/HOLD/DEFENSIVE states
- `src/backtesting/wheel_hybrid/engine.py`: WheelHybridBacktest with regime updates
- `scripts/run_vrp_bakeoff.py`: Bake-off runner (--iv-source vix-regime)
- `tests/test_vix_regime_provider.py`: Unit tests for index VRP signals

## Attribution

Implemented as FREE alternative to paid IV sources, using only public data:
- VIX: CBOE Volatility Index via yfinance
- SPY prices: Yahoo Finance historical data
- No Polygon, Theta, or paid API keys required

Regime states inspired by standard volatility regime frameworks (Derman 1999, VIX white paper).
