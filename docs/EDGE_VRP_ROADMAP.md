# Edge Roadmap: Volatility Risk Premium Harvest

**Status**: Phase 1 scaffold (infrastructure only, no live IV data)  
**Owner**: Research  
**Last updated**: 2026-09-25

---

## Executive Summary

**Problem**: Always-on covered call overwriting lags SPY in bull markets due to capped upside. Historical backtests (Section 8b) show:
- 2000-2024 bluechip: +353.7% vs SPY +534.6% (-180.9% excess)
- 2000-2024 expanded: +4048.8% vs SPY +534.6% (+3514% excess) **but uses synthetic IV, not market IV**

**Thesis**: A wheel strategy can beat SPY **total return** if it:
1. **Harvests volatility risk premium (VRP)** when IV is rich vs realized vol
2. **Reduces/stops overwriting** when IV is cheap (preserves equity beta)
3. **Uses directional sleeve** to earn equity exposure when VRP is low
4. **Adapts regime-aware**: defensive in crashes, hold delta in melt-ups

**This document**: Defines signal stack, regime policy, data requirements, and phased implementation path.

---

## 1. Why Always-On Covered Calls Lose to SPY

### Structural Handicaps

**Capped upside**:
- Covered call at 5% OTM caps month's gain to ~5%
- SPY can +10%, +20%, +50% in single year (2020, 2021)
- Strategy collects premium (2-3% monthly) but misses large moves

**Assignment drag**:
- Called away at strike → lose delta at worst time (stock rallying)
- Re-establish position at higher price → reduce effective shares held
- Rinse-repeat in bull trends = permanent delta erosion

**Realized in backtests**:
- 25-year bluechip CAGR: 6.2% (wheel) vs 7.7% (SPY)
- 5-year 2020-2024: +55% (wheel) vs +95% (SPY) = -40% excess

### Required Edge

To beat SPY, wheel must:
1. **Sell options only when IV > fair** (positive VRP)
2. **Hold equity beta when IV is cheap** (stop/thin CC, hold shares)
3. **Earn directional alpha** in low-VRP regimes (30% directional sleeve)
4. **Survive crashes** (defensive sizing, cash raise)

**Current gap**: Backtest uses Black-Scholes + realized vol, **not market IV**. No edge detection = always-on overwriting in all regimes.

---

## 2. Signal Stack: Detecting Volatility Risk Premium

### 2.1 Core Signal: IV - RV Spread (VRP)

**Definition**:
```
VRP = (ATM IV - Realized Vol) / Realized Vol
```

**Example**:
- ATM IV (21-day) = 25%
- Realized vol (21-day trailing) = 18%
- VRP = (25 - 18) / 18 = 38.9% → Rich IV, write options

**Thresholds** (to be calibrated):
- VRP > 20%: Rich IV → harvest (write CC/CSP)
- VRP 0-20%: Neutral → selective writes or hold delta
- VRP < 0%: Cheap IV → stop writes, hold equity

### 2.2 IV Rank / Percentile

**Definition**:
```
IV Rank = (Current IV - Min IV_52w) / (Max IV_52w - Min IV_52w)
```

**Use case**: Contextualize absolute IV level
- IV = 30% may be "high" for low-vol name (MSFT)
- IV = 30% may be "low" for high-vol name (NVDA)

**Thresholds**:
- IV Rank > 50%: Above median → favor writes
- IV Rank < 30%: Below median → thin writes or skip

### 2.3 Term Structure

**Signal**: Front-month IV vs 3-month IV
- Inverted (front > back): Elevated near-term fear → harvest short DTE
- Normal (front < back): Calm → standard term structure

### 2.4 Skew

**Signal**: OTM put IV vs ATM IV
- High put skew → crash hedging demand → harvest CSP premium
- Flat skew → normal regime

### 2.5 Liquidity

**Filter**: Only write options with:
- Bid-ask spread < 10% of mid (or < $0.10 for cheap options)
- Volume > 100 contracts daily
- Open interest > 500 contracts

**Avoid**: Wide spreads erode theoretical edge

---

## 3. Regime Policy: When to Write vs Hold Delta

### Regime States

**HARVEST_VRP** (default wheel behavior):
- Conditions: VRP > 20%, IV Rank > 40%
- Policy: Write CC/CSP at target strikes (5-10% OTM)
- Target: 70% wheel sleeve, 30% directional
- Goal: Collect premium when IV is rich

**HOLD_DELTA** (preserve equity beta):
- Conditions: VRP < 10% OR (VRP < 20% AND equity uptrend)
- Policy: Skip CC writes or widen strikes to 15-20% OTM (sell lottery tickets only)
- Keep shares unencumbered, ride trend
- Directional sleeve: 50-60% (boost equity exposure)
- Goal: Earn equity gains when overwriting would cap upside

**DEFENSIVE** (crash / high realized vol):
- Conditions: Realized vol spike (21d RV > 40%) OR VRP inverted (< -10%)
- Policy: Reduce new risk, raise cash to 30-40%
- BTC ITM options at loss if needed (stop bleed)
- Thin or stop CSP writes (avoid falling knives)
- Goal: Preserve capital, reduce drawdown

### Regime Transitions

```
HARVEST_VRP <---> HOLD_DELTA (based on VRP)
      |
      v
  DEFENSIVE (realized vol spike, VRP inversion)
      |
      v
  HARVEST_VRP or HOLD_DELTA (stabilization)
```

**Hysteresis**: Require 3-5 day confirmation to switch regimes (avoid whipsaw)

---

## 4. Directional Sleeve Mandate

**Purpose**: Earn equity beta when VRP is low (Option sleeve cannot harvest)

**Target allocation**:
- HARVEST_VRP: 30% directional (baseline)
- HOLD_DELTA: 50-60% directional (boost during melt-ups)
- DEFENSIVE: 10-20% directional (risk-off)

**Selection**:
- SPY tracking (simple beta capture)
- OR sector ETFs (XLF, XLK, XLV) for diversification
- OR agent-scored liquid names (top quintile momentum/quality)

**Risk**: Directional sleeve must perform in low-VRP regimes or strategy still lags SPY.

---

## 5. Data Requirements

### 5.1 Historical IV Surface

**What we need**:
- Daily ATM IV (21-day, 45-day) for ~50-100 liquid names
- Start date: 2000-01-01 (match equity history)
- End date: 2024-12-31 (present)
- Frequency: EOD snapshots (not tick)

**Providers**:
1. **Polygon.io**: Options quotes API (EOD ATM IV reconstruction)
   - Cost: $399/mo (Starter) or $999/mo (Advanced)
   - Coverage: 2015+ (limited pre-2015)
   - Quality: Good liquidity filter
   
2. **ThetaData**: Historical options chains
   - Cost: $99/mo (retail) or $399/mo (pro)
   - Coverage: 2010+ (some names back to 2007)
   - Quality: Raw OPRA ticks, requires IV calc
   
3. **OPRA via direct feed** (e.g., Databento, Intrinio):
   - Cost: $500-2000/mo depending on history depth
   - Coverage: 2000+ (best for long backtest)
   - Quality: Highest (exchange-direct)

**Recommendation**: Start with **Polygon.io Starter ($399/mo)** for 2015-2024 proof-of-concept. If Phase 2 validates edge, upgrade to OPRA-class provider for full 2000-2024.

### 5.2 Realized Volatility

**Already have**: Calculated from equity price history (yfinance, free)

### 5.3 Benchmark: SPY Total Return

**Critical**: Must compare to **SPY total return** (includes dividends), not price-only return.

**Current gap**: yfinance SPY data is price-only (~2% annual dividend yield missing).

**Fix**:
- Use `^SPXTR` (S&P 500 Total Return Index) if available
- OR adjust SPY returns: `total_return = price_return + 2% annually`
- OR fetch dividend history and reconstruct

**Impact**: SPY total return ~2% higher annually than price return. Our 2000-2024 results may understate SPY outperformance.

---

## 6. Phased Implementation

### Phase 1: Scaffold (THIS PR) ✅

**Goal**: Infrastructure without live IV data

**Deliverables**:
- `IVProvider` protocol (abstract interface)
- `SyntheticIVFromRealizedProvider` (research-only, for testing)
- `EdgeGate` (VRP/IV rank filters)
- `Regime` state machine (HARVEST/HOLD/DEFENSIVE)
- Engine integration (plumb gate + regime into write path)
- CLI flags (`--edge-mode`, `--min-vrp`, etc.)
- Tests (gate blocks/allows, regime transitions)
- Docs (this roadmap + whitepaper pointers)

**Status**: In progress

**Output**: Code compiles, tests pass, **but NO CLAIM of edge** (synthetic IV only).

---

### Phase 2: Wire Real IV Data (NEXT)

**Goal**: Replace synthetic IV with market IV from provider

**Tasks**:
1. Subscribe to Polygon.io Starter ($399/mo)
2. Implement `PolygonIVProvider`:
   - Fetch daily ATM IV for universe (21-day, 45-day)
   - Cache to disk (`data/iv_cache/{symbol}/{date}.json`)
   - Handle missing data (delisted stocks, gaps)
3. Implement `FileIVProvider` / `CsvIVProvider`:
   - Read cached IV snapshots
   - Allow offline backtest replay
4. Re-run 2015-2024 backtests with **real market IV**
5. Compare:
   - Edge-gated (real IV) vs always-on (synthetic IV)
   - Regime-aware (HOLD_DELTA in melt-ups) vs static 70/30

**Success criteria**:
- Edge-gated strategy beats always-on by ≥2% annually
- Regime-aware reduces melt-up lag (2020-2021 test)
- VRP signal has ≥55% hit rate (writes profitable > 55% of time)

**If edge does NOT exist**: Kill project or pivot to pure equity quant.

---

### Phase 3: Walk-Forward + New Paper Track (6-12 months out)

**Goal**: Validate edge in unseen data + live conditions

**Walk-forward backtest**:
- Train signal thresholds on 2015-2019 (calibrate `min_vrp`, `min_iv_rank`)
- Test on 2020-2024 (out-of-sample)
- Require beat-SPY in test period

**New paper track** (DO NOT contaminate `wheel-10k-paper-v1`):
- Launch `vrp-wheel-v1` paper track (Alpaca paper, $10k NAV)
- Run for 6-12 months with live IV from Polygon
- Compare to:
  - SPY total return (live benchmark)
  - Legacy `wheel-10k-paper-v1` (control)
  - Directional-only sleeve (SPY tracking)

**Success criteria**:
- `vrp-wheel-v1` beats SPY by ≥3% after 12 months (annualized)
- Max DD ≤ SPY max DD (risk-adjusted edge, not just return)
- Edge persists across ≥2 regime shifts (HARVEST → HOLD → HARVEST)

**If paper track fails**: Kill or redesign.

---

### Phase 4: Production Risk/Ops (12+ months out)

**Prerequisites**:
- Phase 3 paper track success
- Legal/compliance sign-off (if raising external capital)
- Risk framework (position limits, drawdown stops)

**Infrastructure**:
- Real-time IV monitoring (intraday regime checks)
- Execution algos (TWAP, limit orders, spread capture)
- Live position reconciliation vs Alpaca
- Alerting (failed writes, breached risk limits)
- Performance attribution (VRP alpha vs directional alpha)

**Capital scale**:
- Start: $50k-100k (small real-money test)
- Scale to $500k-1M if Sharpe > 1.5 for 12+ months

---

## 7. Explicit Falsifiers (Kill Criteria)

**We will STOP development if**:

1. **Phase 2 shows no edge**:
   - Real IV gating does NOT beat always-on by ≥2% annually
   - VRP signal hit rate < 52% (coin flip)
   - Regime-aware does NOT reduce melt-up lag

2. **Phase 3 walk-forward fails**:
   - Out-of-sample test period (2020-2024) underperforms always-on
   - Edge exists in 2015-2019 but disappears 2020-2024 (overfit)

3. **Phase 3 paper track fails**:
   - `vrp-wheel-v1` lags SPY by >1% after 12 months
   - Max DD exceeds SPY max DD by >10%
   - Edge vanishes after market regime shift

4. **Structural issues**:
   - Bid-ask spreads + slippage erode theoretical VRP edge
   - IV data quality poor (gaps, stale quotes, delisted names)
   - Directional sleeve lags SPY (undermines low-VRP periods)

**Pivot options if falsified**:
- Pure equity quant (drop options entirely)
- Tail hedging only (sell risk-off CC, buy OTM puts)
- Delta-one replication (synthetic forwards, no overwriting)

---

## 8. Current Status Summary

**What we HAVE**:
- ✅ Equity backtest engine (Black-Scholes + realized vol)
- ✅ Expanded 45-name universe (diversification validated)
- ✅ CSP collateral fixes (no over-leverage)
- ✅ 25-year historical sample (2000-2024)

**What we DON'T have (yet)**:
- ❌ Market IV data (still using synthetic realized vol)
- ❌ Proof VRP edge exists (synthetic ≠ real)
- ❌ Regime-aware backtests (no HOLD_DELTA test yet)
- ❌ SPY total return benchmark (missing ~2% annual dividend yield)

**Phase 1 scope (this PR)**:
- Build plumbing for IV providers + edge gate + regime
- Run sanity checks with synthetic IV (NOT claiming edge)
- Document roadmap + falsifiers
- Keep live `wheel-10k-paper-v1` untouched (do not contaminate control)

**Next milestone**: Phase 2 (wire Polygon.io, validate edge exists)

---

## 9. Non-Claims (Explicit)

**We are NOT claiming**:
- ❌ Synthetic IV (BS + realized vol) = proof of VRP edge
- ❌ Expanded universe results (Section 8b) = beat-SPY alpha (those use synthetic IV)
- ❌ Phase 1 scaffold = production-ready strategy
- ❌ Always-on wheel can beat SPY without IV data

**We ARE claiming**:
- ✅ Expanded universe improves diversification (40x return over 25yr)
- ✅ Blue-chip universe proves strategy survives recessions
- ✅ IF market IV edge exists, this roadmap is the path to validate it
- ✅ Phase 1 scaffold enables Phase 2 real IV drop-in

**Bottom line**: Treat Phase 1 as **infrastructure investment**. Edge validation starts in Phase 2.

---

## 10. References

- **Whitepaper**: `docs/WHITEPAPER_WHEEL_HYBRID.md` (Section 8b: historical results)
- **Design doc**: `docs/WHEEL_BACKTEST_DESIGN.md` (universe, premium model)
- **Academic**: Coval & Shumway (2001), "Expected Option Returns" (VRP evidence)
- **Industry**: CBOE BuyWrite Index (BXM) — always lags SPY in bulls, beats in bears

---

## Appendix: Estimated Costs

| Item | Provider | Monthly Cost | Annual Cost |
|------|----------|--------------|-------------|
| **Phase 2 IV data** | Polygon.io Starter | $399 | $4,788 |
| **Phase 3 OPRA history** | Databento | $800 | $9,600 |
| **Phase 3 paper track** | Alpaca (free) | $0 | $0 |
| **Phase 4 real-money** | Alpaca (live) | $0 | $0 |
| **Total (Year 1)** | | | **$14,388** |

**ROI threshold**: If strategy generates >$15k annually on $50k capital (30% return), data costs are justified.
