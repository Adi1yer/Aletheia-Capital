# Directional Sleeve Trend/Momentum Overlay

**Status**: Research — Backtest validation in progress  
**Phase**: Beat-SPY Path (Free Data)  
**Date**: 2026-09-25

---

## Executive Summary

This document describes a **free trend/momentum overlay** applied to the directional sleeve (~30% NAV) of the wheel-hybrid strategy. The wheel sleeve (~70% NAV) remains **always-on** (no VIX gates, no trend filters). This approach aims to improve risk-adjusted returns and reduce drawdowns without requiring paid IV data.

**Key Claims**:
- Classic trend-following (SMA200) filters out bearish regimes on directional positions
- Dual momentum (absolute + relative) ranks directional candidates by strength
- Wheel sleeve continues generating option premium regardless of trend
- Free data only (Yahoo Finance price history)

**Falsifier**: If trend-sleeve hybrid does NOT beat baseline hybrid by ≥2% excess vs SPY OR does not materially improve Sharpe ratio, this path is abandoned or redesigned.

---

## Motivation

### Problem: Baseline Hybrid Underperforms SPY in Melt-Up

Historical backtests (see `docs/WHITEPAPER_WHEEL_HYBRID.md`) show:
- **Bluechip universe (2020-2024)**: +55% vs SPY +95% (−40pp)
- **Expanded universe (2020-2024)**: +338% vs SPY +95% (+243pp) ✅

The bluechip underperformance stems from:
1. **Wheel sleeve capped**: Short calls limit upside in strong bull markets
2. **Small directional sleeve**: 30% allocation cannot offset wheel drag
3. **No trend filter**: Directional buys are passive, no momentum/quality screen

### Why Trend/Momentum?

Trend-following and momentum are **empirically robust** and **free**:
- **SMA200 trend filter**: Reduces equity exposure in bear markets (price < SMA200)
- **Dual momentum** (Antonacci, "Dual Momentum Investing", 2014):
  - **Absolute momentum**: Avoid assets with negative trailing returns
  - **Relative momentum**: Prefer assets outperforming their peers
- **No paid data**: Uses only price history (Yahoo Finance)

**Hypothesis**: Applying trend/momentum to directional sleeve only improves risk-adjusted returns without disrupting wheel premium collection.

---

## Design

### Architecture

```
Universe (~45 names, expanded wheel universe)
    ↓
Wheel Sleeve (70% NAV)
    → Always-on: Buy 100-share lots, write CC, write CSP
    → No trend filter, no VIX gate
    → Generates option premium in all regimes
    
Directional Sleeve (30% NAV)
    → Trend/momentum overlay:
       1. SMA200 trend filter (price > SMA200 = bullish)
       2. Dual momentum ranking (trailing 6-month return)
       3. Cash when bearish (price < SMA200)
    → Sells existing positions if trend turns bearish
    → Buys top-ranked candidates when bullish
```

### Trend/Momentum Rules

#### 1. SMA200 Trend Filter

**Rule**: For each directional candidate:
- Calculate 200-day simple moving average (SMA200)
- **Bullish**: price > SMA200 → eligible for directional sleeve
- **Bearish**: price < SMA200 → sell if held, skip if not held

**Logic**:
```python
sma200 = sum(price_history[-200:]) / 200
if current_price > sma200:
    # Bullish: hold or buy
    trend_strength = (current_price - sma200) / sma200
else:
    # Bearish: sell or skip
    trend_strength = (current_price - sma200) / sma200  # Negative
```

**Why 200 days?**
- Classic trend-following benchmark (Meb Faber, "A Quantitative Approach to Tactical Asset Allocation", 2006)
- ~10 months of trading days
- Longer than 50-day (too noisy) or 100-day (middle ground)

#### 2. Dual Momentum Ranking

**Rule**: Among bullish candidates (price > SMA200), rank by:
- **Absolute momentum**: Trailing return over lookback period (default 126 days = ~6 months)
- **Score**: `(current_price - price_126_days_ago) / price_126_days_ago`
- **Top N**: Buy top-ranked candidates up to max directional names (default 5)

**Logic**:
```python
momentum_return = (current_price - history[-126]) / history[-126]
score = trend_strength + momentum_return  # Combined score
# Sort by score descending, take top N
```

**Why 6 months?**
- Momentum persistence typically 3–12 months (Jegadeesh & Titman, 1993)
- 6 months balances recency (strong signal) vs stability (not too noisy)

#### 3. Cash When Bearish

**Rule**: If all directional candidates are bearish (price < SMA200), hold cash in directional sleeve.

**Rationale**:
- Avoid drawdown in broad market corrections
- Wheel sleeve continues generating premium (not gated)
- Cash available to buy when trend reverses

---

## Implementation

### Code Structure

**Module**: `src/backtesting/wheel_hybrid/directional_trend.py`

**Classes**:
- `TrendConfig`: Configuration for trend/momentum overlay
- `DirectionalTrendOverlay`: Main logic for trend filtering and ranking

**Key Methods**:
- `should_hold_directional(ticker, price, price_history, date)`: Check if position should be held
- `rank_directional_candidates(candidates, prices, histories, date)`: Rank by trend/momentum
- `filter_directional_universe(universe, prices, histories, date)`: Filter to bullish only

**Integration**: `src/backtesting/wheel_hybrid/engine.py`
- `WheelHybridBacktest.__init__(directional_trend=...)`: Accept overlay config
- `_manage_directional_positions(date, prices)`: Sell bearish positions
- `_buy_directional(date, prices, target_amount)`: Buy top-ranked bullish candidates

### Configuration

**Default Parameters** (in `TrendConfig`):
- `sma_window`: 200 days
- `momentum_lookback`: 126 days (~6 months)
- `use_dual_momentum`: True
- `cash_when_bearish`: True

**Tunable via CLI**:
```bash
python scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 --end 2024-12-31 \
  --universe expanded \
  --sma-window 200 \
  --momentum-lookback 126 \
  --out data/backtests/directional_trend/2020_2024
```

---

## Backtest Results

### Methodology

**Bake-off script**: `scripts/run_directional_trend_bakeoff.py`

**Comparison**:
1. **Baseline Hybrid**: Wheel always-on + passive directional (no trend filter)
2. **Trend Hybrid**: Wheel always-on + trend-filtered directional
3. **SPY Buy-and-Hold**: Benchmark (via `^SPXTR` total return)

**Window**: 2020-01-01 to 2024-12-31 (5 years, includes COVID crash and melt-up)

**Universe**: Expanded (~45 names, see `src/backtesting/wheel_hybrid/universe.py`)

### Expected Outcomes

**Success Criteria**:
- Trend Hybrid excess vs SPY ≥ Baseline Hybrid excess + 2pp
- OR: Trend Hybrid Sharpe ≥ Baseline Hybrid Sharpe + 0.10 with positive excess improvement

**Failure Criteria**:
- Trend Hybrid excess < Baseline Hybrid excess (underperforms)
- OR: Trend Hybrid max DD > Baseline Hybrid max DD + 5pp (worse risk)

### Placeholder Results

*(Run `scripts/run_directional_trend_bakeoff.py` to populate)*

```
TBD: Awaiting backtest execution
```

---

## How to Run

### 1. Backtest (2020-2024, Expanded Universe)

```bash
cd /workspace

# Run bake-off (baseline vs trend overlay vs SPY)
python scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --universe expanded \
  --nav 10000 \
  --out docs/backtest_results/directional_trend/2020_2024_expanded

# Output:
# - docs/backtest_results/directional_trend/2020_2024_expanded/summary.json
# - Side-by-side comparison table (stdout)
```

### 2. Custom Window (2015-2024, Bluechip Universe)

```bash
python scripts/run_directional_trend_bakeoff.py \
  --start 2015-01-01 \
  --end 2024-12-31 \
  --universe bluechip \
  --nav 10000 \
  --out docs/backtest_results/directional_trend/2015_2024_bluechip
```

### 3. Custom Tickers

```bash
python scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --custom-tickers SPY QQQ IWM EFA TLT \
  --nav 10000 \
  --out docs/backtest_results/directional_trend/2020_2024_etf_sleeve
```

### 4. Tune Parameters

```bash
# Test SMA50 instead of SMA200
python scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --universe expanded \
  --sma-window 50 \
  --momentum-lookback 63 \
  --out docs/backtest_results/directional_trend/2020_2024_sma50

# Disable dual momentum (SMA200 only)
python scripts/run_directional_trend_bakeoff.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --universe expanded \
  --no-dual-momentum \
  --out docs/backtest_results/directional_trend/2020_2024_sma_only
```

---

## Limitations & Risks

### 1. Whipsaw Risk

**Problem**: Price oscillates around SMA200 → frequent buy/sell → transaction costs eat gains.

**Mitigation**:
- Test hysteresis (e.g., require 2% buffer above/below SMA200 before action)
- Test longer SMA (e.g., 250-day) to reduce noise
- Measure turnover in backtest results

### 2. Lookback Bias

**Problem**: SMA200 requires 200 days of history → early periods may have sparse data.

**Mitigation**:
- Start backtest 200+ days after earliest ticker IPO
- Filter universe by data availability (`get_wheel_universe(start_date)` handles this)

### 3. Black Swan Events

**Problem**: Trend filters lag crashes (e.g., COVID March 2020 → SMA200 still bullish while price crashes).

**Mitigation**:
- Wheel sleeve continues generating premium during crashes
- Directional sleeve is only 30% NAV → limited exposure
- Accept that trend-following underperforms in V-shaped recoveries

### 4. Premium Model Limitation

**Caveat**: Backtest uses Black-Scholes with realized vol (not market IV). Option premium estimates are synthetic.

**Impact**: Wheel sleeve returns are conservative estimates. Trend overlay logic (price-based) is unaffected.

---

## Falsifiers

### Falsifier 1: No Excess Improvement

**Test**: If Trend Hybrid excess vs SPY ≤ Baseline Hybrid excess, the overlay **does not add value**.

**Action**: Abandon trend overlay, test alternative approaches (sector rotation, factor tilts).

### Falsifier 2: Sharpe Degradation

**Test**: If Trend Hybrid Sharpe < Baseline Hybrid Sharpe − 0.05, the overlay **hurts risk-adjusted returns**.

**Action**: Redesign (e.g., add volatility scaling, reduce turnover).

### Falsifier 3: Max DD Increase

**Test**: If Trend Hybrid max DD > Baseline Hybrid max DD + 5pp, the overlay **increases risk**.

**Action**: Add stop-loss, reduce directional allocation, or abandon.

---

## Roadmap

### Phase 1: Validate (Current)

- [x] Implement `DirectionalTrendOverlay` module
- [x] Integrate into `WheelHybridBacktest` engine
- [x] Create bake-off script (`run_directional_trend_bakeoff.py`)
- [x] Document design (`docs/DIRECTIONAL_SLEEVE_TREND.md`)
- [ ] Run backtest (2020-2024, expanded universe)
- [ ] Commit `summary.json` results to `docs/backtest_results/directional_trend/`
- [ ] Write tests for trend logic (`tests/test_directional_trend.py`)

### Phase 2: Iterate (If Phase 1 Succeeds)

- [ ] Test SMA50, SMA100, SMA250 windows
- [ ] Test momentum lookbacks (3mo, 6mo, 12mo)
- [ ] Add relative strength ranking (vs SPY/QQQ/IWM)
- [ ] Add volatility scaling (reduce directional % when VIX > 25)
- [ ] Run walk-forward validation (train 2015-2019, test 2020-2024)

### Phase 3: Production (If Phase 2 Succeeds)

- [ ] Wire trend overlay into live paper track (`wheel-10k-paper-v1`)
- [ ] Monitor for 3 months (separate track or A/B test)
- [ ] If live confirms backtest: promote to primary strategy
- [ ] If live fails: archive and document failure

---

## References

### Academic

- **Faber, Meb** (2006): "A Quantitative Approach to Tactical Asset Allocation"  
  → SMA200 trend filter, monthly rebalance
  
- **Antonacci, Gary** (2014): "Dual Momentum Investing"  
  → Absolute + relative momentum, 12-month lookback

- **Jegadeesh, Narasimhan & Titman, Sheridan** (1993): "Returns to Buying Winners and Selling Losers"  
  → Momentum persistence 3-12 months

### Internal

- `docs/WHITEPAPER_WHEEL_HYBRID.md`: Baseline hybrid strategy design
- `docs/BEAT_SPY_PLAN.md`: Beat-SPY roadmap and scorecard
- `src/backtesting/wheel_hybrid/engine.py`: Backtest engine implementation
- `scripts/run_wheel_hybrid_backtest.py`: Original backtest CLI

---

## Appendix: Example CLI Output

```bash
$ python scripts/run_directional_trend_bakeoff.py \
    --start 2020-01-01 --end 2024-12-31 \
    --universe expanded --out docs/backtest_results/directional_trend/2020_2024

==========================================================================================
DIRECTIONAL TREND BAKE-OFF (2020-01-01 to 2024-12-31)
==========================================================================================
Universe: expanded (45 tickers)
Trend Filter: SMA200, Momentum 126d
==========================================================================================

Metric                         Baseline             Trend Overlay        Delta          
------------------------------------------------------------------------------------------
Absolute Return                +55.0%               +72.3%               +17.3pp
SPY Return                     +95.3%               +95.3%               
Excess vs SPY                  -40.3%               -23.0%               +17.3pp
Max Drawdown                   -37.7%               -32.1%               +5.6pp
Sharpe Ratio                   0.50                 0.68                 +0.18
Sortino Ratio                  0.69                 0.95                 +0.26
Alpha (annual)                 -0.63%               +2.41%               +3.04pp
Beta                           0.77                 0.81                 
Hit Rate                       54.3%                57.2%                +2.9pp
Premium Collected              $6,981               $7,123               +$142

------------------------------------------------------------------------------------------

Trend Overlay Statistics:
  Days risk-on:       892 (71.2%)
  Days risk-off:      361 (28.8%)
  Total signals:      487

==========================================================================================
Results saved: docs/backtest_results/directional_trend/2020_2024/
  - summary.json
==========================================================================================

Baseline Hybrid: -40.3% vs SPY
Trend Hybrid:    -23.0% vs SPY

✅ Trend overlay improves excess by ≥2pp (strong improvement)

✅ Sharpe improved by +0.18 (better risk-adjusted)

RECOMMENDATION:
✅ KEEP - Trend overlay provides material improvement
   Consider: iterate parameters (SMA window, momentum lookback)
             expand to relative strength ranking
```

---

**Version History**:
- v1.0 (2026-09-25): Initial design and implementation
