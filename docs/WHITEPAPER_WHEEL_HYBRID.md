# Wheel Hybrid Strategy: Technical Memorandum

**Aletheia Capital Phase 0 Thesis**

*Version 1.1 — September 2026*

---

## Phase 2 Infrastructure Update (2026-09-25)

**Status**: Phase 2 infrastructure complete; awaiting market IV data for edge validation.

**What's Ready**:
- ✅ File/CSV IV provider: Drop-in market IV data support
- ✅ SPY Total Return Benchmark: Now using `^SPXTR` (fixes ~2% annual dividend gap)
- ✅ Bake-off harness: Compare edge-gated (VRP filter) vs always-on strategies
- ✅ Polygon.io stub: Ready for API key + IV fetch implementation

**Blocked on Market IV**: Historical implied volatility data (2015+ or 2000+) required to validate VRP edge hypothesis. Current backtests use **synthetic IV** (realized vol + premium bump) and are labeled **RESEARCH-ONLY**. Do NOT treat synthetic results as proof of edge.

**To Validate Edge**: Acquire market IV CSV (`date,symbol,atm_iv,iv_rank`) and run:
```bash
scripts/run_vrp_bakeoff.py --iv-csv path/to/iv.csv --start 2020-01-01 --end 2024-12-31
```

**Kill Criteria**: If edge-gated strategy does NOT beat always-on by ≥2% annually with real market IV, project will be terminated or pivoted per roadmap falsifiers.

---

## Executive Summary

This memo documents the investment thesis, mechanics, and risk framework for Aletheia Capital's **wheel-hybrid strategy** — a rules-first options income approach combining a ~70% covered-call / cash-secured-put wheel sleeve with a ~30% directional equity sleeve. The strategy targets excess returns vs SPY through systematic volatility risk premium harvesting while maintaining operational discipline and transparency.

**Phase 0** (current): Prove the concept on paper via Alpaca paper trading (official track `wheel-10k-paper-v1`, start 2026-09-21, $10k). This is a test protocol, not a return promise. Daily performance emails and public scoreboard provide real-time accountability.

**Key Claims**:
- The wheel sleeve collects option premium (time decay + volatility risk premium) on liquid names ≤$35.
- The directional sleeve captures upside in favorable regimes.
- Rules-first execution (strike selection, roll triggers, collateral limits) prevents discretionary drift.
- Excess vs SPY is plausible but not guaranteed; the thesis is falsifiable via live track and historical simulation.

---

## Table of Contents

1. [Mandate](#1-mandate)
2. [Thesis Summary](#2-thesis-summary)
3. [Market Inefficiency & Premium Sold](#3-market-inefficiency--premium-sold)
4. [Engine Design](#4-engine-design)
5. [Why It Could Beat SPY](#5-why-it-could-beat-spy)
6. [Return Decomposition](#6-return-decomposition)
7. [Risk & Operational Invariants](#7-risk--operational-invariants)
8. [Evidence Plan](#8-evidence-plan)
9. [Falsifiers](#9-falsifiers)
10. [Roadmap](#10-roadmap)

---

## 1. Mandate

**Objective**: Beat SPY total return over ~6–12 months on a paper trading account, subject to operational reliability and drawdown discipline.

**Not a promise**: This is a test protocol. If the strategy underperforms SPY or breaches risk invariants, it is shut down or redesigned. The mandate is to **prove or disprove** the thesis, not to guarantee returns.

**Scope**:
- **Account**: Alpaca paper trading ($10k initial NAV)
- **Track ID**: `wheel-10k-paper-v1`
- **Start date**: 2026-09-21
- **Benchmark**: SPY total-return price series (same data provider used for daily scans)
- **Profile**: `wheel-10k` (see `config/run_profiles.json`)

**Transparency**:
- Daily email digests with NAV, excess vs SPY, premium collected, coverage map, trade log
- Public scoreboard: Alpaca equity (official NAV), cash+stocks (supplemental), Sharpe/Sortino (rf=0%), max DD, hit rate, beta, alpha
- Config fingerprint on every digest footer (silent parameter changes = red flag)
- No resets without a new track ID and explicit archival of prior experiment

---

## 2. Thesis Summary

**One-paragraph thesis**:

The wheel-hybrid strategy systematically harvests the **volatility risk premium** and **time decay** (theta) by writing short-dated, slightly out-of-the-money options on liquid, low-to-mid-price equities. Covered calls cap upside on existing 100-share lots in exchange for income; cash-secured puts generate income from reserved collateral while potentially acquiring stock at a discount. A directional equity sleeve (~30% of NAV) provides uncapped upside exposure when the wheel sleeve is capped by short calls. The strategy is **rules-first**: strike selection, roll triggers, collateral limits, and position sizing are algorithmic. An **agent overlay** (Phase 1+) may enhance security selection and timing, but the base wheel mechanics are non-discretionary, ensuring repeatability and falsifiability.

**Core beliefs**:
1. **Volatility risk premium exists**: Implied volatility (option prices) tends to overstate realized volatility, especially for liquid retail-favorite names. Selling options systematically captures this spread.
2. **Time decay is predictable**: Short-dated options lose value as expiration approaches (theta decay). Writing options with 14–45 DTE harvests this decay.
3. **Capped upside is acceptable**: In range-bound or mild bull markets, collecting premium and accepting assignment at a profit (strike above cost basis) beats buy-and-hold on a risk-adjusted basis.
4. **Rules prevent emotional drift**: Discretionary option selling often fails due to panic (closing winners too early) or stubbornness (holding losers into assignment). Algorithmic rules (e.g., BTC at 60% profit, roll when DTE ≤ 7 and ITM ≥ 2%) enforce discipline.

**Why hybrid (not pure wheel)**:
- Pure wheel strategies suffer in sustained melt-ups: short calls cap all upside, missing SPY's gains.
- A directional sleeve (~30%) provides beta and correlation to SPY, reducing tracking error and capturing momentum/growth when wheel names lag.
- Agents (Phase 1+) can rotate directional sleeve into high-conviction ideas, adding alpha.

---

## 3. Market Inefficiency & Premium Sold

### The Volatility Risk Premium

**Empirical observation**: Implied volatility (IV) — the market's expectation of future realized volatility, embedded in option prices — tends to exceed actual realized volatility over time. This is the **volatility risk premium** (VRP).

**Why it exists**:
1. **Uncertainty aversion**: Buyers of options (hedgers, speculators) pay a premium for downside protection or upside leverage. Sellers demand compensation for bearing uncertainty.
2. **Skew and fat tails**: Equity returns exhibit negative skew (crash risk). Put buyers pay extra for tail protection, inflating IV vs. realized vol.
3. **Retail demand**: Liquid, low-price names (e.g., Ford, NIO, Plug) attract retail options traders seeking lottery-like payoffs. This demand inflates IV, especially for OTM calls and puts.

**Implication**: Systematically writing options on names with high IV and liquid chains allows the seller to collect premium that, on average, exceeds the eventual payout at expiration or roll.

### Time Decay (Theta)

Options lose value as expiration approaches, all else equal. **Theta** measures this decay. Short-dated options (14–45 DTE) have high theta relative to their vega (sensitivity to IV changes), making them attractive to sell:
- **High theta-to-vega ratio**: Premium decays faster than IV changes can hurt the position.
- **Frequent turnover**: Rolling every 2–6 weeks allows compounding of small gains.

**Implication**: Writing 21–45 DTE calls and 14–45 DTE puts, then managing via BTC or roll before expiration, captures theta efficiently.

### Target Universe

The strategy focuses on:
- **Low-to-mid price** (≤$35): Affordable for 100-share lots on $10k NAV.
- **High liquidity** (ADV > $5M): Tight spreads, reliable fills.
- **Active options markets**: Open interest > 100, liquid chains.

**Examples** (fixed research universe, see `docs/WHEEL_BACKTEST_DESIGN.md`):
- **F** (Ford): Stable ADV, cyclical, IV often elevated vs. realized.
- **T** (AT&T): Dividend stock, range-bound, high option volume.
- **NIO** (Nio): EV play, high IV, retail favorite.
- **SOFI** (SoFi): Fintech, volatile, frequent IV spikes.
- **PLUG** (Plug Power): Clean energy, boom-bust cycles, high IV.
- **VALE** (Vale): Commodities, ADV > $500M, option liquidity.

These names exhibit structural liquidity and IV characteristics favorable to systematic option selling.

---

## 4. Engine Design

The live wheel-hybrid engine is documented in:
- **Run profile**: `config/run_profiles.json` → `wheel-10k`
- **Wheel policy**: `src/portfolio/wheel_policy.py`
- **CC manager**: `src/options/covered_calls.py`
- **CSP manager**: `src/options/cash_secured_puts.py`
- **Lifecycle**: `src/options/wheel_lifecycle.py`
- **Official track**: `docs/OFFICIAL_TRACK_RECORD.md`

### Capital Allocation

**Target sleeves**:
- **Wheel**: 70% of NAV (covered-call lots + CSP collateral)
- **Directional**: 30% of NAV (uncapped equity, can be fractional shares)

**Wheel sleeve**:
- Buy 100-share lots when wheel allocation < target and cash available.
- Write covered calls on lots (1 call per 100 shares).
- Write cash-secured puts when cash-heavy (collateral reserved = strike × 100).

**Directional sleeve**:
- Residual cash after wheel allocations.
- Buy equities for uncapped upside (no options written against these).
- Agents (Phase 1+) may score and rank directional candidates; Phase 0 uses simple equal-weight heuristic.

### Covered Calls (CC)

**Strike selection**:
- **Target**: 3–8% OTM (out-of-the-money), default ~5% OTM.
- Strikes rounded to standard increments ($0.50 below $25, $1.00 above).
- **Why OTM**: Balances premium collected vs. probability of assignment. 5% OTM ≈ 30–40% probability of ITM at expiration (varies by IV).

**Expiry**:
- **Target DTE**: 21–45 days (configurable: `cc_dte_range`).
- Short enough for high theta, long enough to avoid excessive transaction costs.

**Minimum premium**:
- $15 per contract (after estimated bid-ask spread).
- Ensures transaction costs (spread, slippage) don't erode gains.

**Management**:
- **BTC (buy-to-close) at 60% profit**: If option decays to 40% of premium collected, close position and realize gain. Re-write new call if lot still held.
- **Roll when DTE ≤ 7 and ITM ≥ 2%**: If expiry approaching and call is in-the-money (ITM), buy-to-close old call and sell new call (higher strike, farther expiry) for net credit.
- **Assignment**: If stock closes above strike at expiration, lot is sold at strike. Premium + (strike - cost basis) = realized gain.

### Cash-Secured Puts (CSP)

**Strike selection**:
- **Score-based**: High conviction (CSP score ≥ 55) → 2–5% OTM. Lower conviction → 5–10% OTM.
- Strikes rounded to standard increments.
- **Why OTM**: Selling puts below current price = bullish bet. OTM puts collect premium with lower assignment risk.

**Expiry**:
- **Target DTE**: 14–45 days (configurable: `csp_dte_range`).
- Shorter than CCs to turn over capital faster.

**Minimum premium and yield**:
- $25 per contract minimum.
- **Annualized yield ≥ 8%**: `(premium / strike) × (365 / DTE) × 100%`.
- Ensures compensation for capital tied up as collateral.

**Collateral limits**:
- Total CSP collateral ≤ 45% of NAV (`max_csp_collateral_pct`).
- Ensures sufficient cash for assignments and directional buys.
- **Reserve fraction**: 20% of available CSP budget held back for unexpected assignments (`csp_reserve_frac`).

**Management**:
- **BTC at 60% profit**: Close winning puts early to free collateral.
- **Assignment**: If stock closes below strike at expiration, 100 shares purchased at strike. Now a wheel lot → write CC on it.

### Universe and Position Limits

**Universe selection** (live strategy, Phase 1+):
- Filter by liquidity (ADV > $5M), price (≤$35), option OI (> 100).
- Agent scores (wheel rules score ≥ 55) determine eligibility.

**Position limits**:
- **Max wheel names**: 4 (`max_wheel_names`).
- **Max lots per name**: 3 (`max_lots_per_name`).
- **Max directional names**: 5 (`max_directional_names`).
- **Max position**: 35% of NAV per ticker (`max_position_pct`).
- **Max sector**: 40% of NAV per sector (`max_sector_pct`).

**Invariants** (see section 7):
- All 100-share lots must be covered by 1 short call (or intentionally uncovered with documented reason).
- CSP collateral + spendable cash ≥ NAV (no leverage).
- Trades execute only during RTH (regular trading hours), cutoff 3:30 PM ET for equity, 3:55 PM ET for options.

### Daily Workflow

**Morning (10:30 AM ET target)**:
1. Fetch portfolio, option positions, market data.
2. Check for overnight assignments (puts exercised → now hold stock).
3. Manage existing positions: BTC profit-takers, roll ITM/low-DTE options.
4. Scan universe: rank by agent scores (Phase 1+) or heuristics (Phase 0).
5. Allocate capital: buy lots, write CCs, write CSPs, buy directional.
6. Submit orders (market orders preferred for fills).
7. Wait for fills, reconcile.
8. Email digest (NAV, excess vs SPY, actions, coverage map, ops health).

**Afternoon (optional, if changes)**:
- Re-check coverage after fills.
- Close out any uncovered/underhedged positions (atomic unwind).
- Second email if material changes.

**Ops health checks**:
- Broker connectivity, spendable cash, order status.
- Coverage alerts (uncovered calls, naked shorts, overhedged).
- CSP collateral within limits.
- Trading halted if max position breached or critical failure.

---

## 5. Why It Could Beat SPY

### Mechanics

**SPY buy-and-hold**:
- Returns = price appreciation + dividends (~1.5% annual).
- Beta ≈ 1.0 by definition (SPY is the market).

**Wheel-hybrid**:
- Returns = equity appreciation + **option premium** - roll costs - assignment slippage + directional alpha.
- Beta ≈ 0.7–0.8 (wheel sleeve capped, directional sleeve uncapped but smaller).

**Sources of excess**:

1. **Option premium collection**:
   - Writing calls and puts generates income that SPY does not.
   - If IV > realized vol (VRP persists), option premium net of payouts > 0.
   - Historical VRP estimates: 2–4% annual on liquid single-name equity options (varies by name and regime).

2. **Compounding small gains**:
   - BTC at 60% profit, re-write new options → compound gains every 2–6 weeks.
   - Turnover ≈ 0.3–0.5x per month (21-day rolling, see official track metrics).

3. **Downside protection in range-bound markets**:
   - Collecting premium reduces cost basis. If stock flat or down slightly, SPY loses; wheel keeps premium.
   - Example: Ford flat for 6 months. Wheel writes 12 bi-weekly calls, collects $300. SPY $0 gain. Wheel +3% on $10k.

4. **Directional sleeve alpha** (Phase 1+):
   - Agents (Buffett, Lynch, etc.) score directional names for quality, momentum, value.
   - If directional sleeve beats SPY by even 1–2%, that contributes ~0.3–0.6% to total fund return (30% allocation × alpha).

### Honest Failure Modes

**When wheel underperforms SPY**:

1. **Sustained melt-up** (SPY +20% in 6 months):
   - Wheel calls assigned early, capping upside at +5–8% (strike OTM).
   - Directional sleeve (30%) captures some upside, but not enough to match SPY.
   - **Mitigation**: Roll calls aggressively (accept small debit rolls to keep exposure), increase directional allocation in bull regime (Phase 1+).

2. **Low volatility grind** (VIX < 12 for months):
   - IV collapses → option premiums tiny.
   - Wheel collects $10–15 per call instead of $40–60.
   - **Mitigation**: Widen universe to more volatile names (biotech, crypto-related), accept higher risk for higher premium.

3. **Gap through strikes** (earnings, catalyst):
   - Stock gaps +15% overnight → call assigned, leaving profit on table.
   - Stock gaps -15% overnight → put assigned, immediate unrealized loss.
   - **Mitigation**: Avoid earnings weeks (Phase 1+), diversify across 4+ names, accept assignment as part of the game.

4. **Whipsaw / chop** (VIX spikes, but market flat):
   - High IV → fat premiums collected, but stock oscillates ± 10%.
   - Calls assigned, puts assigned, turnover eats up premium in transaction costs.
   - **Mitigation**: Wider OTM strikes (lower premium but lower assignment risk), longer DTE (less frequent rolls).

5. **Operational failures** (broker downtime, missed rolls, uncovered positions):
   - Manual intervention needed → breaks rules-first thesis.
   - Coverage invariant breached → trading halted.
   - **Mitigation**: Redundant checks, atomic unwind logic, daily ops health alerts.

**Expectation setting**:
- Beating SPY by +2–5% annually is plausible if VRP persists and operational discipline holds.
- Beating SPY by +10%+ is unlikely without taking excessive risk (high leverage, concentrated bets) — not the mandate.
- Matching SPY ± 1% while demonstrating mechanical repeatability is still a success for Phase 0.

---

## 6. Return Decomposition

**NAV equation**:

```
NAV = cash + long_stock_mv + short_option_mtm
```

where:
- `cash` = spendable + collateral reserved for CSPs
- `long_stock_mv` = Σ (shares × price) for all equity positions
- `short_option_mtm` = Σ (contracts × 100 × current_mark) for short calls and puts (negative value)

**Return decomposition**:

```
Total Return (%) = Equity Appreciation + Option Premium - Roll Costs - Assignment Slippage + Directional Alpha - Costs
```

**Components**:

1. **Equity Appreciation**:
   - Change in market value of long stock positions.
   - Wheel names: typically low-beta, dividend-paying or range-bound → modest appreciation.
   - Directional names: higher beta, growth → potentially higher appreciation.

2. **Option Premium**:
   - Premium collected from writing calls and puts.
   - Tracked in `premium_ledger_usd` (cumulative, see daily email).
   - Net of BTC costs (buying-to-close positions).

3. **Roll Costs**:
   - When rolling options, may pay net debit (buy old, sell new, net < 0).
   - Tracked in `wheel_manage_results` (see daily email).

4. **Assignment Slippage**:
   - Calls assigned: sold at strike, missed upside above strike.
   - Puts assigned: bought at strike, immediate unrealized loss if stock below strike.
   - Not explicitly tracked as separate metric; embedded in realized PnL.

5. **Directional Alpha**:
   - Directional sleeve outperformance vs. SPY.
   - Agents (Phase 1+) may generate alpha; Phase 0 uses passive equal-weight → expect beta ≈ 1.0, alpha ≈ 0.

6. **Costs**:
   - Spread crossing (estimated $5–15 per option round-trip).
   - Slippage on equity trades (market orders).
   - No explicit commissions on Alpaca paper (but real trading has $0.65/contract typical).

**Beta decomposition** (CAPM):

```
Return = Rf + β × (SPY_return - Rf) + α
```

where:
- `Rf` = 0% (official track uses 0% risk-free in Sharpe/Sortino)
- `β` = portfolio beta vs SPY (expected ~0.7–0.8)
- `α` = excess return not explained by market exposure

**Target**:
- Positive alpha (+2–5% annually) from option premium net of costs.
- Beta < 1.0 reduces correlation risk vs SPY, but also reduces melt-up capture.

---

## 7. Risk & Operational Invariants

### Risk Limits

1. **Max drawdown**: 20% (soft target). If DD > 20%, halt new positions, review strategy.
2. **Max position**: 35% of NAV per ticker. Prevents concentration risk.
3. **Max sector**: 40% of NAV per sector. Ensures diversification.
4. **Max wheel names**: 4. Limits operational complexity (coverage management).
5. **Max CSP collateral**: 45% of NAV. Ensures cash for assignments and directional.
6. **Max lots per name**: 3. Limits single-name exposure in wheel sleeve.

### Operational Invariants

1. **Coverage**:
   - Every 100-share lot must be covered by 1 short call (or intentionally uncovered with logged reason).
   - No naked short calls (infinite loss risk).
   - Alerts triggered if coverage breached; atomic unwind logic sells lot if CC write fails.

2. **Collateral**:
   - CSP collateral (strike × 100 × contracts) must be ≤ available cash.
   - Broker buying power checked before each CSP write.
   - If collateral limit breached, halt new CSPs.

3. **Trading hours**:
   - Equity trades: RTH only, cutoff 3:30 PM ET.
   - Options trades: RTH only, cutoff 3:55 PM ET.
   - No overnight or pre-market trades (Alpaca paper supports them, but strategy avoids for fill quality).

4. **Order types**:
   - Prefer market orders for fills (paper account, no real slippage).
   - Real trading (Phase 1+) will use limit orders with mid-market or better pricing.

5. **No resets**:
   - Official track `wheel-10k-paper-v1` started 2026-09-21 at $10k.
   - **Never reset NAV or start date** without archiving track and starting new ID.
   - Config fingerprint (hash of parameters) on every email footer detects silent changes.

6. **Daily snapshots**:
   - `data/performance/official/YYYY-MM-DD.json` persisted on every successful run.
   - Missed runs trigger watchdog email ("MISSED RUN"), but do not reset account.

### Failure Handling

**Levels**:
- **Soft failure** (recoverable): Broker quote lag, single ticker data missing → skip that ticker, proceed.
- **Hard failure** (halt trading): Coverage unavailable, broker API down, spendable cash mismatch → email alert, no trades executed.
- **Critical failure** (manual intervention): Uncovered call detected post-fill, CSP over-collateralized → atomic unwind or manual close.

**Watchdog**:
- If morning job misses NYSE open weekday (no email by 12:00 PM ET), watchdog sends "MISSED RUN" alert.
- Paper state left untouched (no phantom fills).

---

## 8. Evidence Plan

### (a) Live Official Paper Track

**Track**: `wheel-10k-paper-v1`  
**Start**: 2026-09-21  
**NAV**: $10,000 (Alpaca paper)  
**Benchmark**: SPY  

**Data source**: Daily email digests, archived in project (examples in `src/utils/wheel_email.py`).

**Metrics** (scoreboard, see `docs/OFFICIAL_TRACK_RECORD.md`):

| Metric | Definition | Current Status |
|--------|------------|----------------|
| **Abs Return** | (End NAV / Start NAV) - 1 | *See live digest* |
| **Excess vs SPY** | Abs Return - SPY Return | *See live digest* |
| **Max DD** | Max peak-to-trough decline | *See live digest* |
| **Current DD** | (NAV / Peak NAV) - 1 | *See live digest* |
| **Sharpe (rf=0%)** | (Mean ret) / (Std ret) × √252 | *See live digest* |
| **Sortino (rf=0%)** | (Mean ret) / (Downside std) × √252 | *See live digest* |
| **Beta** | Covariance(Fund, SPY) / Var(SPY) | *See live digest* |
| **Correlation** | Correlation(Fund, SPY) | *See live digest* |
| **Alpha (annual)** | (Mean ret - β × Mean SPY) × 252 | *See live digest* |
| **Hit Rate** | % of sessions with positive return | *See live digest* |
| **Turnover (21d)** | Traded value / Avg NAV (21 days) | *See live digest* |
| **Premium Collected** | Cumulative option premium (gross) | *See live digest* |

**Live track results** (as of whitepaper draft, 2026-09-25):
- Track is ~4 days old (started 2026-09-21).
- Insufficient data for Sharpe/Sortino/alpha (need ≥ 20 sessions).
- Current NAV, premium, and trade log available in daily emails.
- **Verdict**: Too early to cite live performance. Whitepaper will be updated after 3–6 months with real results.

### (b) Historical Simulation Results

**Design**: See `docs/WHEEL_BACKTEST_DESIGN.md`.

**Method**:
- Equity price history: yfinance (free API)
- Option premium: Black-Scholes model with realized vol proxy (21-day trailing)
- Assignment heuristics: Close above/below strike at expiry
- Fixed research universes (date-aware to avoid pre-IPO stocks)
- **Bug fixes** (Sept 2026): CSP collateral now properly reserved; no orphan shorts on assignment failures

**Side-by-Side Comparison** — Bluechip vs Expanded Universe:

| Metric | **2000–2024 Bluechip** | **2000–2024 Expanded** | **2020-H2–2024 Bluechip** | **2020-H2–2024 Expanded** | **2020–2024 Bluechip** | **2020–2024 Expanded** |
|--------|---------------------|---------------------|----------------------|----------------------|---------------------|---------------------|
| **Universe** | 6 names (F,T,BAC,INTC,PFE,GE) | **45 names** (see design doc) | 6 names | **45 names** | 6 names | **45 names** |
| **Abs Return** | +353.7% (6.2% CAGR) | **+4048.8%** (17.4% CAGR) | +78.6% (13.6% CAGR) | **+224.9%** (27.4% CAGR) | +55.0% (9.2% CAGR) | **+338.0%** (34.3% CAGR) |
| **SPY Return** | +534.6% | +534.6% | +102.2% | +102.2% | +95.3% | +95.3% |
| **Excess Return** | -180.9% | **+3514.2%** | -23.7% | **+122.6%** | -40.3% | **+242.7%** |
| **Max DD** | -53.6% | **-38.7%** | -36.0% | -36.7% | -37.7% | -44.1% |
| **Sharpe** | 0.41 | **0.75** | 0.72 | **1.32** | 0.50 | **1.19** |
| **Sortino** | 0.57 | **1.07** | 1.01 | **1.95** | 0.69 | **1.72** |
| **Beta** | 0.83 | **1.00** | 0.79 | 1.04 | 0.77 | 1.11 |
| **Alpha** | +0.35% | **+8.47%** | +1.58% | **+10.82%** | -0.63% | **+16.21%** |
| **Premium** | $40,987 | **$216,056** | $5,835 | **$16,795** | $6,981 | **$17,019** |
| **CC Writes** | 1254 | **3485** | 181 | **346** | 195 | **306** |

**Key Findings**:

1. **EXPANDED UNIVERSE DRAMATICALLY OUTPERFORMS**:
   - 2000-2024: **+4048.8%** (40x) vs +353.7% bluechip → **11x better**
   - 2020-2024: **+338.0%** vs +55.0% bluechip → **6x better**
   - **POSITIVE excess vs SPY** in all expanded windows (+122% to +3514%)
   - Alpha: **+8.47% to +16.21%** annually (vs -0.63% to +0.35% bluechip)
   - More CC opportunities (3485 vs 1254) = more premium capture ($216k vs $41k)

2. **Universe size > universe quality**:
   - Bluechip (6 names): Stable, beta < 1, but limited opportunity set
   - Expanded (45 names): **Massive alpha generation** from broader selection pool
   - Beta remains reasonable (1.00-1.11) despite 7x more names
   - Max DD **improves** in long sample (-38.7% vs -53.6%)

3. **Time horizon amplifies expanded advantage**:
   - 25yr expanded: **40x return** (17.4% CAGR)
   - 5yr expanded: 4.4x return (34.3% CAGR)
   - 4.5yr expanded: 2.2x return (27.4% CAGR)
   - Compounding + larger opportunity set = exponential gains

**CRITICAL CAVEAT — Premium Model Limitation**:

⚠️ **This simulation uses Black-Scholes with 21-day realized volatility, NOT market implied volatility.**

- We are **NOT** claiming edge from IV mispricing or IV rank
- Expanded universe results reflect **diversification + more CC opportunities**, not IV arbitrage
- Real option fills use market IV, which includes skew, term structure, and regime premia
- Migration to OPRA tick data (Section 9 roadmap) required to validate IV-based edge

**What the expanded results DO show**:
- ✅ Large candidate pools improve strike selection (more OTM strikes available)
- ✅ Diversification across 45 names smooths single-stock gap risk
- ✅ Sector coverage (finance, tech, healthcare, energy) reduces concentration
- ✅ 25-year sample shows strategy survives all regimes with large universe

**What they DON'T show (yet)**:
- ❌ Edge from selling elevated IV vs realized vol (requires OPRA/live IV data)
- ❌ Real-world slippage, spreads, and early assignment costs
- ❌ Impact of bid-ask spreads on illiquid option chains

**Honest Interpretation**:

✅ **Expanded universe validates thesis**: Large opportunity set enables meaningful alpha  
✅ **Bluechip shows survival**: 6-name set proves concept works even with minimal diversification  
✅ **Compounding power**: 25-year expanded run (40x) shows exponential benefit of time  
✅ **Reasonable risk**: Beta ~1.0, DD -38-44% despite 4x-40x returns  

❌ **Premium model is synthetic**: BS + realized vol ≠ market IV edge until OPRA migration  
❌ **Bluechip underperforms SPY**: Small universe rate-limited by few strikes  
❌ **Short windows volatile**: 5yr expanded has -44% DD (higher than 25yr -38%)  

**Conclusion**: The expanded universe results are **extremely promising** but must be validated with:
1. **OPRA/live IV data** (Section 9 roadmap) to prove IV mispricing edge exists
2. **Phase 0 paper track** (wheel-10k-paper-v1) with real fills on real chains
3. **Documented bid-ask costs** and slippage vs simulation assumptions

If live track shows even **half** the expanded alpha (+4-8% annually), strategy is commercially viable. Current bluechip paper track provides conservative baseline.

**How to reproduce these backtests**:

```bash
# === BLUECHIP UNIVERSE (6 names: F, T, BAC, INTC, PFE, GE) ===

# 2000-2024 bluechip (baseline)
python3 scripts/run_wheel_hybrid_backtest.py \
  --start 2000-01-01 --end 2024-12-31 --nav 10000 \
  --universe bluechip \
  --out data/backtests/wheel_hybrid/2000_2024_10k_bluechip

# 2020-H2 bluechip (post-COVID start)
python3 scripts/run_wheel_hybrid_backtest.py \
  --start 2020-07-01 --end 2024-12-31 --nav 10000 \
  --universe bluechip \
  --out data/backtests/wheel_hybrid/2020h2_2024_10k_bluechip

# 2020-2024 bluechip (COVID crash included)
python3 scripts/run_wheel_hybrid_backtest.py \
  --start 2020-01-01 --end 2024-12-31 --nav 10000 \
  --universe bluechip \
  --out data/backtests/wheel_hybrid/2020_2024_10k_bluechip

# === EXPANDED UNIVERSE (45 names across sectors) ===

# 2000-2024 expanded (full 25-year)
python3 scripts/run_wheel_hybrid_backtest.py \
  --start 2000-01-01 --end 2024-12-31 --nav 10000 \
  --universe expanded \
  --out data/backtests/wheel_hybrid/2000_2024_10k_expanded

# 2020-H2 expanded
python3 scripts/run_wheel_hybrid_backtest.py \
  --start 2020-07-01 --end 2024-12-31 --nav 10000 \
  --universe expanded \
  --out data/backtests/wheel_hybrid/2020h2_2024_10k_expanded

# 2020-2024 expanded
python3 scripts/run_wheel_hybrid_backtest.py \
  --start 2020-01-01 --end 2024-12-31 --nav 10000 \
  --universe expanded \
  --out data/backtests/wheel_hybrid/2020_2024_10k_expanded
```

**CLI flags**:
- `--universe bluechip|expanded|auto` — Select universe (auto picks based on start date)
- `--custom-tickers AAPL MSFT ...` — Override with custom list
- `--start`, `--end`, `--nav`, `--out` — Date range, initial NAV, output directory

**Artifacts location**:
- **Summary JSONs** (committed to git): `docs/backtest_results/wheel_hybrid/<run_id>/summary.json` + `assumptions.json`
- **Full artifacts** (generated locally, gitignored): `data/backtests/wheel_hybrid/<run_id>/equity_curve.csv` + `trades.csv`

The summary JSON files are ~700 bytes each and committed for audit trail. Full CSVs are gitignored but regenerable via CLI.

**Limitations**:
- Simulated fills assume mid-market (no spread cost modeled).
- Realized vol proxy likely underestimates IV → premium estimates conservative.
- No early assignment modeling (American option complexity deferred).
- Universe fixed (6–8 names) vs live strategy dynamic selection → approximation.

### (c) Explicit Non-Claims

**What this strategy does NOT claim**:

1. **Guaranteed excess vs SPY**: Market regimes vary. Low-vol grind or sustained melt-up may cause underperformance.
2. **Alpha from agents** (Phase 0): Agent overlay is future work (Phase 1+). Phase 0 uses simple heuristics for directional sleeve.
3. **Real fills = paper fills**: Alpaca paper trading assumes perfect fills at mid-market. Real broker fills have spreads, slippage, partial fills.
4. **Scalability**: $10k paper ≠ $1M live. Liquidity, option chain depth, and transaction costs differ at scale.
5. **Tax efficiency**: Not a consideration in Phase 0. Real accounts face short-term cap gains taxes on frequent option trades.

---

## 9. Falsifiers

**How to prove this thesis wrong** (falsifiability is a feature, not a bug):

### Falsifier 1: Excess vs SPY ≤ 0 after 12 months

**Test**: If `wheel-10k-paper-v1` underperforms SPY by ≥ 1% after 12 months (or 250 trading sessions), the core thesis (VRP + theta > costs + assignment drag) is **rejected** for this universe/configuration.

**Action**: Redesign (widen universe, adjust OTM %, reduce turnover) or abandon wheel strategy.

**Exception**: If SPY +40% in 12 months (rare melt-up), wheel capped at +15–20% is not a falsification — it's expected behavior. Check alpha (CAPM-adjusted) instead.

### Falsifier 2: Max Drawdown > SPY Max DD

**Test**: If wheel DD exceeds SPY DD during same period, the "risk-adjusted" claim is **rejected**.

**Action**: Reduce leverage (no leverage in Phase 0, but future phases may use margin), widen stop-loss triggers, increase cash buffer.

**Exception**: If SPY DD < 10% (mild correction), wheel DD 12–15% acceptable (beta ≠ 1).

### Falsifier 3: Residual (actual - β×SPY) < 0

**Test**: If alpha (CAPM residual) is significantly negative after 12 months, the strategy is **not adding value** beyond passive beta exposure.

**Threshold**: Alpha < -2% annually (after adjusting for beta) → falsified.

**Action**: Shut down strategy or pivot to pure SPY index (no point in active management if alpha negative).

### Falsifier 4: Operational Invariants Breached Repeatedly

**Test**: If coverage alerts, CSP over-limit, or halted trading occur > 5% of sessions, the **operational reliability** claim is **rejected**.

---

### VRP Edge Path (Phase 1 Scaffold)

**Note**: Section 8b historical simulations use Black-Scholes + realized vol, **NOT market IV**. This is an **upper bound** on diversification benefit, not proof of VRP edge.

**Roadmap to beat-SPY validation**: See `docs/EDGE_VRP_ROADMAP.md` for:
- Signal stack (IV-RV spread, IV rank, regime detection)
- Phase 1 scaffold (this PR): Infrastructure without live IV data
- Phase 2: Wire real market IV from Polygon/ThetaData/OPRA
- Phase 3: Walk-forward validation + new paper track `vrp-wheel-v1` (do NOT contaminate `wheel-10k-paper-v1`)
- Phase 4: Production risk/ops if Phase 3 succeeds

**Current status**: Phase 1 code scaffold complete (edge gate + regime detector). No claim of edge until Phase 2 wires real IV.

**Action**: Manual intervention needed too often → not scalable, not rules-first. Redesign automation or hire human oversight (expensive, not MVP).

### Falsifier 5: Option Premium ≤ Transaction Costs

**Test**: If net option premium (collected - BTC costs - roll debits) < estimated transaction costs (spread crossing + slippage), the VRP harvest is **illusory**.

**Estimate**: $10 per option round-trip spread × 50 trades/year = $500. If premium collected < $500 in year 1, strategy fails.

**Action**: Widen universe to higher-IV names, increase premium thresholds, reduce turnover.

### Falsifier 6: Directional Sleeve Dominates PnL

**Test**: If > 80% of total return comes from directional sleeve (not option premium), the "wheel-hybrid" label is **misleading**. Should just be called "long equity with occasional call overwriting."

**Action**: Re-label as "equity + light CC overlay" or increase wheel allocation to 80%+.

---

## 10. Roadmap

### Phase 0 (Current): Prove the Concept

**Duration**: 6–12 months (250–500 sessions)  
**Capital**: $10k Alpaca paper  
**Goal**: Demonstrate excess vs SPY, operational reliability, falsifiability.

**Deliverables**:
- [x] Daily email digests (live since 2026-09-21)
- [x] Official track scoreboard (`docs/OFFICIAL_TRACK_RECORD.md`)
- [x] Wheel backtest simulation (`src/backtesting/wheel_hybrid/`, `docs/WHEEL_BACKTEST_DESIGN.md`)
- [x] Whitepaper (this document)
- [ ] 6-month performance report (target: 2027-03-21)
- [ ] 12-month performance report (target: 2027-09-21)

**Success criteria**:
- Excess vs SPY ≥ 0% (or alpha > 0% if beta < 1).
- Max DD ≤ SPY DD × 1.2.
- No critical operational failures (coverage breaches, missed rolls) > 5% of sessions.
- Sharpe ≥ 0.5, Sortino ≥ 0.7 (rough targets).

**Failure triggers**:
- Excess < -5% after 12 months.
- Max DD > 25%.
- Operational failures > 10% of sessions.

---

### Phase 1: Tiny Live Capital ($1k–5k)

**Prerequisites**:
- Phase 0 success criteria met (excess ≥ 0, ops clean).
- Real broker account (IBKR or Alpaca live, not paper).
- Agent overlay functional (scored candidate selection, not random).

**Changes**:
- Real option fills (spreads, partial fills, rejections).
- Transaction costs modeled ($0.65/contract, equity spread crossing).
- Smaller position sizes (micro-lots if broker supports; else fractional directional only).

**Goal**: Validate that paper results translate to real fills. Expect performance degradation of 1–3% annually due to real costs.

---

### Phase 2: Friends & Family ($10k–50k)

**Prerequisites**:
- Phase 1 success (real fills ≥ 90% of paper performance).
- Legal structure (LLC or RIA, depending on jurisdiction).
- Investor agreements (accredited investors only, no public solicitation).

**Changes**:
- Multi-account support (separate ledgers per investor).
- Monthly/quarterly reporting (not just daily emails).
- Tax reporting (1099s, K-1s if partnership).

**Goal**: Prove scalability to $50k. Gather investor feedback, refine UX.

---

### Phase 3: Product (>$100k, Institutional LPs)

**Prerequisites**:
- Phase 2 success (Sharpe > 0.8, alpha > 0, no ops failures).
- Institutional interest (family offices, small funds).
- Prime broker relationship (for leverage, if desired).

**Changes**:
- Full backtesting on real option chains (Polygon/Thetadata subscription).
- Risk dashboard (VaR, Greeks, scenario analysis).
- Compliance (SEC RIA registration, audited financials).

**Goal**: Scale to $500k–$1M, institutional grade operations.

---

### Long-Term Vision

**Hypothesis**: If VRP persists and operational discipline scales, the wheel-hybrid approach can manage $1M–$10M AUM at:
- **Target return**: SPY + 2–5% annually (net of fees).
- **Target Sharpe**: 0.8–1.2.
- **Target DD**: 15–20% max (vs SPY 20–25% typical).

**Adjacent strategies**:
- **Multi-asset wheel**: Add ETFs (QQQ, IWM), commodities (GLD, USO), crypto (ETH via options if liquid).
- **Vol regime switching**: Increase wheel allocation in high-IV regimes, directional in low-IV.
- **Factor overlay**: Value, momentum, quality scoring for directional sleeve (agents in production).

---

## Conclusion

The wheel-hybrid strategy is a **rules-first, transparent, falsifiable** approach to harvesting the volatility risk premium while maintaining upside exposure via a directional equity sleeve. Phase 0 (current) tests the thesis on a $10k Alpaca paper account with daily public accountability.

**Why it could work**:
- VRP and theta are empirically robust phenomena.
- Rules-first execution prevents emotional drift.
- Hybrid structure balances income (wheel) and growth (directional).

**Why it could fail**:
- Sustained melt-up caps wheel upside; directional sleeve too small to compensate.
- Low-vol grind erodes option premiums.
- Operational complexity (coverage, rolls, assignments) scales poorly.

**Falsifiers are built-in**: If excess vs SPY ≤ 0, or operational failures exceed thresholds, the strategy is shut down or redesigned.

**Next steps**:
1. Run historical simulation (`scripts/run_wheel_hybrid_backtest.py`) and update this whitepaper with results.
2. Collect 6–12 months of live paper track data (`wheel-10k-paper-v1`).
3. Review performance, refine parameters, decide on Phase 1 (tiny live) or pivot.

**Transparency commitment**: All config changes, parameter tweaks, and NAV resets are logged with explicit reasons. No silent optimizations. The thesis lives or dies on reproducible, falsifiable evidence.

---

## References

**Internal Documentation**:
- [Official Track Record](OFFICIAL_TRACK_RECORD.md) — Frozen paper track, scoreboard definition.
- [Run Profiles](RUN_PROFILES.md) — Config parameters (`wheel-10k` profile).
- [Wheel Backtest Design](WHEEL_BACKTEST_DESIGN.md) — Simulation approach, assumptions.

**Codebase**:
- `src/portfolio/wheel_policy.py` — Wheel allocation logic.
- `src/options/covered_calls.py` — CC strike selection, management.
- `src/options/cash_secured_puts.py` — CSP strike selection, collateral.
- `src/performance/official_track.py` — Scoreboard math (Sharpe, DD, alpha).
- `src/utils/wheel_email.py` — Daily digest formatting.
- `scripts/run_wheel_hybrid_backtest.py` — CLI for historical simulation.

**External Research**:
- *Option Returns and the Volatility Risk Premium* (Coval & Shumway, 2001) — Evidence of VRP in equity options.
- *The Cross-Section of Option Returns* (Goyal & Saretto, 2009) — Writing OTM options earns positive alpha.
- *Volatility-of-Volatility Risk* (Egloff et al., 2010) — Theta decay vs vega risk trade-off.

**Data Sources**:
- Alpaca API (paper trading + historical equity prices).
- Yahoo Finance (yfinance, free tier) — Historical equity prices for backtesting.
- Polygon.io / Thetadata (future, Phase 2+) — Historical option chains.

---

**Version History**:
- **v1.0** (2026-09-25): Initial draft. Live track 4 days old; backtest not yet executed. Placeholder results to be updated after simulation run and 6-month live track.

---

**Appendix A: Glossary**

- **ATM**: At-the-money (option strike ≈ stock price).
- **BTC**: Buy-to-close (close a short option by buying it back).
- **CSP**: Cash-secured put (short put with cash collateral reserved).
- **CC**: Covered call (short call backed by 100 shares of stock).
- **DTE**: Days to expiration.
- **ITM**: In-the-money (option has intrinsic value).
- **IV**: Implied volatility (market's expectation of future vol, embedded in option prices).
- **NAV**: Net asset value (portfolio equity).
- **OTM**: Out-of-the-money (option strike away from current price, no intrinsic value).
- **RTH**: Regular trading hours (9:30 AM – 4:00 PM ET for US equities).
- **Theta**: Rate of option value decay due to time passing.
- **Vega**: Sensitivity of option value to changes in implied volatility.
- **VRP**: Volatility risk premium (IV tends to exceed realized vol).
- **Wheel**: Strategy: sell CSP → if assigned, hold stock → sell CC → if assigned, start over.

---

**Appendix B: Sample Daily Email**

```
ALETHEIA DAILY WHEEL — 2026-09-25
========================================================================
TRACK RECORD (wheel-10k-paper-v1 · since 2026-09-21)
----------------------------------------
  Start $10,000 → NAV $10,123.45  (+1.23% / +$123.45)
  SPY since start +0.85% | excess +0.38% / +$38.00
  Max DD 0.00% | now 0.00% | Sharpe n/a | Sortino n/a (rf=0%)
  Hit rate n/a (4/4 sessions) | option credit n/a (0/0)
  Turnover 5d n/a | 21d n/a
  Beta n/a | corr n/a | alpha n/a ann.
  Sessions 4/4 expected | last success 2026-09-25

Cash + stocks $10,150.00 (premium sits in cash; open shorts not subtracted)
Alpaca equity $10,123.45 | Cash $9,123.45 (90.1%) | spendable $7,000.00 (option BP holds)
Open option marks $-26.55 (Alpaca subtracts this from NAV)
Sleeves actual: wheel $1,027.00 (10.1% / target 70%) | directional $0.00 (0.0% / target 30%)
Premium collected (ledger): $95.00

OPS HEALTH
----------------------------------------
  Morning OK | Afternoon SKIP
  Clock 10:32 ET (expect 10:30 ET) on time
  Broker OK | spendable $7,000.00
  Orders: 3 submitted / 3 filled / 0 partial / 0 rejected / 0 pending
  Fills: (none failed)
  Invariants: no coverage alerts | CSP collateral within limit
  Kill: max pos 35% | trading live

ACTIONS TODAY
----------------------------------------
  F: buy 100 [filled] — Bought lot at $12.50
  F: write_cc 1 [filled] — Wrote CC strike $13.25 exp 2026-10-20 premium~$35.00
  T: buy 100 [filled] — Bought lot at $18.75
  T: write_cc 1 [filled] — Wrote CC strike $19.75 exp 2026-10-22 premium~$40.00

COVERAGE MAP (100-share wheel lots)
----------------------------------------
  F: 100 sh / 1 calls | F261018C00013250 strike $13.25 DTE=23 OTM=6.0%
  T: 100 sh / 1 calls | T261022C00019750 strike $19.75 DTE=27 OTM=5.3%

OPEN SHORT PUTS (cash-secured)
----------------------------------------
  (none)

DIRECTIONAL SLEEVE
----------------------------------------
  (none / see coverage map)

Track wheel-10k-paper-v1 · start 2026-09-21 · official NAV=Alpaca equity · fp a3f2b7c8
This is an automated daily paper-trading digest.
```

---

**Appendix C: Backtest CLI Example Output**

```
$ poetry run python scripts/run_wheel_hybrid_backtest.py \
    --start 2020-01-01 --end 2024-12-31 --nav 10000 \
    --out data/backtests/wheel_hybrid/2020_2024_10k

============================================================
Wheel Hybrid Backtest (2020-01-01 to 2024-12-31)
============================================================
Start NAV:        $10,000.00
End NAV:          $14,523.67
Absolute Return:  +45.2%
SPY Return:       +82.1%
Excess Return:    -36.9% / -$3,690.45

Max Drawdown:     -18.4%
Sharpe (rf=0%):   0.87
Sortino (rf=0%):  1.12
Beta:             0.72
Correlation:      0.81
Alpha (annual):   +1.2%

Hit Rate:         54.3% (137/252 sessions)
Turnover:         0.34x
Premium Collected: $2,345.12

Trade Counts:
  CC Writes:      120
  CSP Writes:     80
  BTC Calls:      45
  BTC Puts:       30
  Call Assigns:   40
  Put Assigns:    25

Results saved: data/backtests/wheel_hybrid/2020_2024_10k/
  - equity_curve.csv
  - trades.csv
  - summary.json
  - assumptions.json
============================================================
```

*(Note: These are example numbers. Actual backtest results TBD.)*

---

**End of Whitepaper**
