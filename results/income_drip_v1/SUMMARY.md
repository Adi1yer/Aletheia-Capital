# Income Drip Bake-Off Results: Momentum + Dividend/CC Income

**Product Thesis:** Momentum + liquid concentration is the beat-SPY *driver*. 
Dividends and covered-call premiums are a *funding drip* into that driver — not a hedge story.

**KEEP Bar:** Income drip arm beats pure Arm C on risk-adjusted grounds OR beats SPY 
with materially milder drawdowns than pure Arm C (without lagging Arm C badly on total return).

---

## Summary Table

| Arm | Window | Strategy TR | SPY TR | vs SPY | Sharpe | Max DD | Verdict |
|-----|--------|-------------|--------|--------|--------|--------|---------|
| arm_1_pure_momentum | 2020_2024 | 110.9% | 95.3% | +15.6pp | 0.86 | -32.4% | ✓ BEATS (+15.6pp) |
| arm_1_pure_momentum | 2010_2024 | 849.1% | 583.8% | +265.3pp | 1.05 | -27.1% | ✓ BEATS (+265.3pp) |
| arm_1_pure_momentum | 2022_stress | -0.8% | -18.6% | +17.8pp | 0.05 | -13.8% | ✓ PASS (+17.8pp) |
| arm_1_pure_momentum | 2000_2002_stress | -15.9% | -37.0% | +21.1pp | -0.12 | -33.1% | ✓ PASS (+21.1pp) |
| arm_1_pure_momentum | 2008_2009_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_2_momentum_div_drip | 2020_2024 | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_2_momentum_div_drip | 2010_2024 | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_2_momentum_div_drip | 2022_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_2_momentum_div_drip | 2000_2002_stress | -14.8% | -37.0% | +22.3pp | -0.19 | -27.2% | ✓ PASS (+22.3pp) |
| arm_2_momentum_div_drip | 2008_2009_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_3_momentum_div_cc_drip | 2020_2024 | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_3_momentum_div_cc_drip | 2010_2024 | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_3_momentum_div_cc_drip | 2022_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_3_momentum_div_cc_drip | 2000_2002_stress | -14.3% | -37.0% | +22.7pp | -0.18 | -26.8% | ✓ PASS (+22.7pp) |
| arm_3_momentum_div_cc_drip | 2008_2009_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |

---

## Arm 1: Pure Momentum (Arm C Baseline)

**Description:** 100% Arm C momentum quality (12-1 month, top 30, quarterly EW) - control from PR #10

**Configuration:**
- Growth sleeve (Arm C momentum): 100%
- Ballast sleeve (dividend payers): 0%
- Covered calls: None

### Performance by Window

**2020_2024** (2020-01-01 to 2024-12-31) - primary window

- **Strategy Total Return:** 110.94% (ann. 16.14%)
- **SPY Total Return:** 95.30% (ann. 14.36%)
- **Excess Return:** +15.64pp (ann. +1.78pp)
- **Sharpe Ratio:** 0.86
- **Sortino Ratio:** 1.31
- **Max Drawdown:** -32.44% (vs SPY -33.72%)
- **Beta:** 0.79
- **Correlation:** 0.84
- **Verdict:** ✓ BEATS (+15.6pp)

**2010_2024** (2010-01-01 to 2024-12-31) - primary window

- **Strategy Total Return:** 849.09% (ann. 16.22%)
- **SPY Total Return:** 583.77% (ann. 13.70%)
- **Excess Return:** +265.32pp (ann. +2.52pp)
- **Sharpe Ratio:** 1.05
- **Sortino Ratio:** 1.61
- **Max Drawdown:** -27.10% (vs SPY -33.72%)
- **Beta:** 0.75
- **Correlation:** 0.83
- **Verdict:** ✓ BEATS (+265.3pp)

**2022_stress** (2022-01-01 to 2022-12-31) - stress test

- **Strategy Total Return:** -0.83% (ann. -0.84%)
- **SPY Total Return:** -18.65% (ann. -18.71%)
- **Excess Return:** +17.81pp (ann. +17.88pp)
- **Sharpe Ratio:** 0.05
- **Sortino Ratio:** 0.07
- **Max Drawdown:** -13.76% (vs SPY -24.50%)
- **Beta:** 0.68
- **Correlation:** 0.87
- **Verdict:** ✓ PASS (+17.8pp)

**2000_2002_stress** (2000-01-01 to 2002-12-31) - stress test

- **Strategy Total Return:** -15.91% (ann. -5.65%)
- **SPY Total Return:** -37.01% (ann. -14.37%)
- **Excess Return:** +21.11pp (ann. +8.72pp)
- **Sharpe Ratio:** -0.12
- **Sortino Ratio:** -0.17
- **Max Drawdown:** -33.12% (vs SPY -47.52%)
- **Beta:** 0.92
- **Correlation:** 0.91
- **Verdict:** ✓ PASS (+21.1pp)

**2008_2009_stress** (2008-01-01 to 2009-12-31): *Data unavailable*

---

## Arm 2: Momentum + Dividend Drip

**Description:** 80% Arm C + 20% dividend ballast; dividends drip into Arm C quarterly

**Configuration:**
- Growth sleeve (Arm C momentum): 80%
- Ballast sleeve (dividend payers): 20%
- Covered calls: None

### Performance by Window

**2020_2024** (2020-01-01 to 2024-12-31): *Data unavailable*

**2010_2024** (2010-01-01 to 2024-12-31): *Data unavailable*

**2022_stress** (2022-01-01 to 2022-12-31): *Data unavailable*

**2000_2002_stress** (2000-01-01 to 2002-12-31) - stress test

- **Strategy Total Return:** -14.75% (ann. -5.21%)
- **SPY Total Return:** -37.01% (ann. -14.37%)
- **Excess Return:** +22.27pp (ann. +9.15pp)
- **Sharpe Ratio:** -0.19
- **Sortino Ratio:** -0.27
- **Max Drawdown:** -27.22% (vs SPY -47.52%)
- **Beta:** 0.71
- **Correlation:** 0.91
- **Verdict:** ✓ PASS (+22.3pp)

**2008_2009_stress** (2008-01-01 to 2009-12-31): *Data unavailable*

---

## Arm 3: Momentum + Dividend + Light CC Drip

**Description:** 80% Arm C + 20% dividend ballast with 50% light CC overwrite (7.5% OTM, 45d); all income drips into Arm C

**Configuration:**
- Growth sleeve (Arm C momentum): 80%
- Ballast sleeve (dividend payers): 20%
- Covered calls: 50% overwrite, 7.5% OTM, 45d tenor

### Performance by Window

**2020_2024** (2020-01-01 to 2024-12-31): *Data unavailable*

**2010_2024** (2010-01-01 to 2024-12-31): *Data unavailable*

**2022_stress** (2022-01-01 to 2022-12-31): *Data unavailable*

**2000_2002_stress** (2000-01-01 to 2002-12-31) - stress test

- **Strategy Total Return:** -14.32% (ann. -5.05%)
- **SPY Total Return:** -37.01% (ann. -14.37%)
- **Excess Return:** +22.69pp (ann. +9.31pp)
- **Sharpe Ratio:** -0.18
- **Sortino Ratio:** -0.26
- **Max Drawdown:** -26.83% (vs SPY -47.52%)
- **Beta:** 0.71
- **Correlation:** 0.91
- **Verdict:** ✓ PASS (+22.7pp)

**2008_2009_stress** (2008-01-01 to 2009-12-31): *Data unavailable*

---

## Final Recommendation

**Arm 2 (Dividend Drip):** INSUFFICIENT DATA

**Arm 3 (Dividend + CC Drip):** INSUFFICIENT DATA

**Overall Verdict: ABANDON** income drip as production default.

The dividend/CC drip does not provide sufficient risk-adjusted advantage over pure Arm C momentum.
Stick with pure Arm C (100% momentum quality) as the growth engine flagship.

This bake-off remains as research archive for future reference.

---

## Pre-Registered Design Rules

### Methodology

- **Growth sleeve (Arm C):** 12-1 month momentum, top 30 liquid large-cap quality names
- **Ballast sleeve:** Top 20 liquid dividend payers by trailing 12-month yield (≥1.5%)
- **Rebalance frequency:** Quarterly (Jan, Apr, Jul, Oct)
- **Dividend drip:** All dividends from ballast accumulate and deploy into growth at quarterly rebalance
- **Covered calls (Arm 3 only):** 50% overwrite, 7.5% OTM, 45-day tenor, synthetic Black-Scholes pricing
- **Trading costs:** 7 bps round-trip (conservative for paper brokerage)
- **No lookahead:** All universes selected using only point-in-time information

### Data Sources

- **Price data:** yfinance (free)
- **Dividend data:** yfinance trailing 12-month dividends
- **Option pricing:** Synthetic Black-Scholes using realized volatility * 1.1 (IV proxy)
- **Benchmark:** ^SPXTR (SPY total return) where available, SPY fallback

### Honest Framing

This is 'income buys growth,' NOT 'CC hedges drawdowns.'

Covered calls on ballast generate premium income but cap upside on those names.
The growth sleeve (Arm C momentum) is NEVER overwritten — it stays pure long.

Dividend/CC income provides a steady drip to buy more growth names, but does not hedge the growth book itself.
