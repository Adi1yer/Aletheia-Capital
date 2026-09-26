# Growth Quality v1 Bake-Off Results vs SPY (FIXED FOR CITEABILITY)

**Strategy:** Concentrated liquid quality/growth equity (long-only, no covered calls)

**KEEP Bar:** Strategy total return ≥ SPY total return on BOTH primary windows (2020-2024 AND 2010-2024)

**ONLY CITEABLE ARMS (A, C, D) are KEEP candidates.** Arm B is hindsight/lookahead demo only.

---

## Summary Table

| Arm | Window | Strategy TR | SPY TR | Excess | Sharpe | Max DD | Verdict | Notes |
|-----|--------|-------------|--------|--------|--------|--------|---------|-------|
| arm_a_qqq | 2020_2024 | 145.8% | 95.3% | +50.5pp | 0.83 | -35.1% | ✓ KEEP (+50.5pp vs SPY) |  |
| arm_a_qqq | 2010_2024 | 1170.8% | 583.8% | +587.0pp | 0.93 | -35.1% | ✓ KEEP (+587.0pp vs SPY) |  |
| arm_a_qqq | 2022_stress | -33.3% | -18.6% | -14.6pp | -1.10 | -34.9% | ✗ UNDER (-14.6pp vs SPY) |  |
| arm_a_qqq | 2000_2002_stress | -74.0% | -37.0% | -37.0pp | -0.61 | -83.0% | ✗ UNDER (-37.0pp vs SPY) |  |
| arm_b_hindsight | 2020_2024 | 234.1% | 95.3% | +138.8pp | 1.17 | -31.6% | ⚠️ LOOKAHEAD - NOT CITEABLE | ⚠️ HINDSIGHT |
| arm_b_hindsight | 2010_2024 | 3011.8% | 583.8% | +2428.1pp | 1.33 | -31.6% | ⚠️ LOOKAHEAD - NOT CITEABLE | ⚠️ HINDSIGHT |
| arm_b_hindsight | 2022_stress | -24.8% | -18.6% | -6.2pp | -0.97 | -28.4% | ⚠️ LOOKAHEAD - NOT CITEABLE | ⚠️ HINDSIGHT |
| arm_b_hindsight | 2000_2002_stress | -0.4% | -37.0% | +36.6pp | 0.14 | -30.1% | ⚠️ LOOKAHEAD - NOT CITEABLE | ⚠️ HINDSIGHT |
| arm_c_point_in_time | 2020_2024 | 112.3% | 95.3% | +17.0pp | 0.82 | -36.3% | ✓ KEEP (+17.0pp vs SPY) |  |
| arm_c_point_in_time | 2010_2024 | 872.4% | 583.8% | +288.6pp | 0.96 | -36.3% | ✓ KEEP (+288.6pp vs SPY) |  |
| arm_c_point_in_time | 2022_stress | -6.0% | -18.6% | +12.6pp | -0.19 | -19.4% | ✓ PASS (+12.6pp vs SPY) |  |
| arm_c_point_in_time | 2000_2002_stress | -14.0% | -37.0% | +23.0pp | -0.09 | -31.1% | ✓ PASS (+23.0pp vs SPY) |  |
| arm_d_sp100 | 2020_2024 | 84.2% | 95.3% | -11.2pp | 0.72 | -33.4% | ✗ FAIL (-11.1pp vs SPY) |  |
| arm_d_sp100 | 2010_2024 | 584.1% | 583.8% | +0.4pp | 0.87 | -33.4% | ✓ KEEP (+0.4pp vs SPY) |  |
| arm_d_sp100 | 2022_stress | -1.8% | -18.6% | +16.9pp | -0.00 | -17.1% | ✓ PASS (+16.9pp vs SPY) |  |
| arm_d_sp100 | 2000_2002_stress | -11.5% | -37.0% | +25.5pp | -0.08 | -29.8% | ✓ PASS (+25.5pp vs SPY) |  |

---

## Arm A: QQQ Buy-and-Hold

**Description:** Nasdaq-100 ETF - citeable concentration baseline

### **VERDICT: BASELINE (not a KEEP candidate)**

This arm is a citeable baseline for comparison.

### Performance by Window

**2020_2024** (2020-01-01 to 2024-12-31) - primary window

- **Strategy Total Return:** 145.78% (ann. 19.76%)
- **SPY Total Return:** 95.30% (ann. 14.36%)
- **Excess Return:** +50.48pp (ann. +5.39pp)
- **Sharpe Ratio:** 0.83
- **Sortino Ratio:** 1.18
- **Max Drawdown:** -35.12% (vs SPY -33.72%)
- **Beta:** 1.14
- **Correlation:** 0.93
- **Annual Turnover:** 0.31x
- **Verdict:** ✓ KEEP (+50.5pp vs SPY)

**2010_2024** (2010-01-01 to 2024-12-31) - primary window

- **Strategy Total Return:** 1170.77% (ann. 18.51%)
- **SPY Total Return:** 583.77% (ann. 13.70%)
- **Excess Return:** +587.00pp (ann. +4.81pp)
- **Sharpe Ratio:** 0.93
- **Sortino Ratio:** 1.32
- **Max Drawdown:** -35.12% (vs SPY -33.72%)
- **Beta:** 1.11
- **Correlation:** 0.93
- **Annual Turnover:** 0.11x
- **Verdict:** ✓ KEEP (+587.0pp vs SPY)

**2022_stress** (2022-01-01 to 2022-12-31) - stress test

- **Strategy Total Return:** -33.27% (ann. -33.37%)
- **SPY Total Return:** -18.65% (ann. -18.71%)
- **Excess Return:** -14.62pp (ann. -14.66pp)
- **Sharpe Ratio:** -1.10
- **Sortino Ratio:** -1.50
- **Max Drawdown:** -34.87% (vs SPY -24.50%)
- **Beta:** 1.28
- **Correlation:** 0.97
- **Annual Turnover:** 0.65x
- **Verdict:** ✗ UNDER (-14.6pp vs SPY)

**2000_2002_stress** (2000-01-01 to 2002-12-31) - stress test

- **Strategy Total Return:** -74.02% (ann. -36.38%)
- **SPY Total Return:** -37.01% (ann. -14.37%)
- **Excess Return:** -37.01pp (ann. -22.02pp)
- **Sharpe Ratio:** -0.61
- **Sortino Ratio:** -0.88
- **Max Drawdown:** -82.96% (vs SPY -47.52%)
- **Beta:** 1.77
- **Correlation:** 0.82
- **Annual Turnover:** 0.87x
- **Verdict:** ✗ UNDER (-37.0pp vs SPY)

---

## Arm B: Hindsight Quality Basket ⚠️ LOOKAHEAD

**Description:** ⚠️ HINDSIGHT / LOOKAHEAD - NOT CITEABLE. Fixed 2024 winner list (upper bound demo only)

### **VERDICT: ⚠️ HINDSIGHT / LOOKAHEAD - NOT CITEABLE**

This arm uses 2024 hindsight winners and CANNOT be cited as tradeable edge.
It demonstrates an UPPER BOUND only. Do not recommend as flagship regardless of returns.

### Performance by Window

**2020_2024** (2020-01-01 to 2024-12-31) - primary window

- **Strategy Total Return:** 234.12% (ann. 27.36%)
- **SPY Total Return:** 95.30% (ann. 14.36%)
- **Excess Return:** +138.82pp (ann. +13.00pp)
- **Sharpe Ratio:** 1.17
- **Sortino Ratio:** 1.67
- **Max Drawdown:** -31.61% (vs SPY -33.72%)
- **Beta:** 1.04
- **Correlation:** 0.95
- **Annual Turnover:** 1.12x
- **Verdict:** ✓ KEEP (+138.8pp vs SPY)

**2010_2024** (2010-01-01 to 2024-12-31) - primary window

- **Strategy Total Return:** 3011.81% (ann. 25.81%)
- **SPY Total Return:** 583.77% (ann. 13.70%)
- **Excess Return:** +2428.05pp (ann. +12.11pp)
- **Sharpe Ratio:** 1.33
- **Sortino Ratio:** 1.90
- **Max Drawdown:** -31.59% (vs SPY -33.72%)
- **Beta:** 1.02
- **Correlation:** 0.93
- **Annual Turnover:** 2.57x
- **Verdict:** ✓ KEEP (+2428.0pp vs SPY)

**2022_stress** (2022-01-01 to 2022-12-31) - stress test

- **Strategy Total Return:** -24.83% (ann. -24.92%)
- **SPY Total Return:** -18.65% (ann. -18.71%)
- **Excess Return:** -6.19pp (ann. -6.20pp)
- **Sharpe Ratio:** -0.97
- **Sortino Ratio:** -1.33
- **Max Drawdown:** -28.42% (vs SPY -24.50%)
- **Beta:** 1.05
- **Correlation:** 0.98
- **Annual Turnover:** 0.73x
- **Verdict:** ✗ UNDER (-6.2pp vs SPY)

**2000_2002_stress** (2000-01-01 to 2002-12-31) - stress test

- **Strategy Total Return:** -0.40% (ann. -0.14%)
- **SPY Total Return:** -37.01% (ann. -14.37%)
- **Excess Return:** +36.61pp (ann. +14.23pp)
- **Sharpe Ratio:** 0.14
- **Sortino Ratio:** 0.20
- **Max Drawdown:** -30.09% (vs SPY -47.52%)
- **Beta:** 0.96
- **Correlation:** 0.82
- **Annual Turnover:** 1.41x
- **Verdict:** ✓ PASS (+36.6pp vs SPY)

---

## Arm C: Point-in-Time Quality

**Description:** Liquid large-cap quality screen using only past information (PRIMARY KEEP CANDIDATE)

### **VERDICT: ✓ KEEP**

This arm **meets the primary KEEP bar** (≥ SPY on both 2020-2024 and 2010-2024).

### Performance by Window

**2020_2024** (2020-01-01 to 2024-12-31) - primary window

- **Strategy Total Return:** 112.26% (ann. 16.29%)
- **SPY Total Return:** 95.30% (ann. 14.36%)
- **Excess Return:** +16.96pp (ann. +1.93pp)
- **Sharpe Ratio:** 0.82
- **Sortino Ratio:** 1.16
- **Max Drawdown:** -36.28% (vs SPY -33.72%)
- **Beta:** 0.96
- **Correlation:** 0.96
- **Annual Turnover:** 1.19x
- **Verdict:** ✓ KEEP (+17.0pp vs SPY)

**2010_2024** (2010-01-01 to 2024-12-31) - primary window

- **Strategy Total Return:** 872.35% (ann. 16.41%)
- **SPY Total Return:** 583.77% (ann. 13.70%)
- **Excess Return:** +288.58pp (ann. +2.71pp)
- **Sharpe Ratio:** 0.96
- **Sortino Ratio:** 1.36
- **Max Drawdown:** -36.26% (vs SPY -33.72%)
- **Beta:** 0.98
- **Correlation:** 0.97
- **Annual Turnover:** 2.41x
- **Verdict:** ✓ KEEP (+288.6pp vs SPY)

**2022_stress** (2022-01-01 to 2022-12-31) - stress test

- **Strategy Total Return:** -6.05% (ann. -6.07%)
- **SPY Total Return:** -18.65% (ann. -18.71%)
- **Excess Return:** +12.60pp (ann. +12.64pp)
- **Sharpe Ratio:** -0.19
- **Sortino Ratio:** -0.27
- **Max Drawdown:** -19.45% (vs SPY -24.50%)
- **Beta:** 0.84
- **Correlation:** 0.97
- **Annual Turnover:** 0.66x
- **Verdict:** ✓ PASS (+12.6pp vs SPY)

**2000_2002_stress** (2000-01-01 to 2002-12-31) - stress test

- **Strategy Total Return:** -14.02% (ann. -4.94%)
- **SPY Total Return:** -37.01% (ann. -14.37%)
- **Excess Return:** +23.00pp (ann. +9.43pp)
- **Sharpe Ratio:** -0.09
- **Sortino Ratio:** -0.14
- **Max Drawdown:** -31.08% (vs SPY -47.52%)
- **Beta:** 0.90
- **Correlation:** 0.92
- **Annual Turnover:** 1.24x
- **Verdict:** ✓ PASS (+23.0pp vs SPY)

---

## Arm D: Equal-Weight S&P 100

**Description:** Non-hindsight concentration control (rules-based diversified baseline)

### **VERDICT: ✗ ABANDON**

This arm **fails 2020-2024** (recent melt-up window).

### Performance by Window

**2020_2024** (2020-01-01 to 2024-12-31) - primary window

- **Strategy Total Return:** 84.15% (ann. 13.02%)
- **SPY Total Return:** 95.30% (ann. 14.36%)
- **Excess Return:** -11.15pp (ann. -1.34pp)
- **Sharpe Ratio:** 0.72
- **Sortino Ratio:** 1.02
- **Max Drawdown:** -33.39% (vs SPY -33.72%)
- **Beta:** 0.88
- **Correlation:** 0.93
- **Annual Turnover:** 1.19x
- **Verdict:** ✗ FAIL (-11.1pp vs SPY)

**2010_2024** (2010-01-01 to 2024-12-31) - primary window

- **Strategy Total Return:** 584.14% (ann. 13.71%)
- **SPY Total Return:** 583.77% (ann. 13.70%)
- **Excess Return:** +0.38pp (ann. +0.00pp)
- **Sharpe Ratio:** 0.87
- **Sortino Ratio:** 1.24
- **Max Drawdown:** -33.37% (vs SPY -33.72%)
- **Beta:** 0.91
- **Correlation:** 0.95
- **Annual Turnover:** 2.39x
- **Verdict:** ✓ KEEP (+0.4pp vs SPY)

**2022_stress** (2022-01-01 to 2022-12-31) - stress test

- **Strategy Total Return:** -1.78% (ann. -1.79%)
- **SPY Total Return:** -18.65% (ann. -18.71%)
- **Excess Return:** +16.86pp (ann. +16.92pp)
- **Sharpe Ratio:** -0.00
- **Sortino Ratio:** -0.00
- **Max Drawdown:** -17.06% (vs SPY -24.50%)
- **Beta:** 0.74
- **Correlation:** 0.94
- **Annual Turnover:** 0.64x
- **Verdict:** ✓ PASS (+16.9pp vs SPY)

**2000_2002_stress** (2000-01-01 to 2002-12-31) - stress test

- **Strategy Total Return:** -11.48% (ann. -4.01%)
- **SPY Total Return:** -37.01% (ann. -14.37%)
- **Excess Return:** +25.53pp (ann. +10.36pp)
- **Sharpe Ratio:** -0.08
- **Sortino Ratio:** -0.11
- **Max Drawdown:** -29.84% (vs SPY -47.52%)
- **Beta:** 0.84
- **Correlation:** 0.93
- **Annual Turnover:** 1.13x
- **Verdict:** ✓ PASS (+25.5pp vs SPY)

---

## Final Recommendation

**MIXED:** 1 of 2 citeable KEEP candidate arms meet the primary KEEP bar: arm_c_point_in_time

Recommendation: Proceed with passing arm(s); abandon failing arms.

---

## Important Notes on Methodology

### Arm B: Hindsight / Lookahead Warning

⚠️ **ARM B IS NOT CITEABLE**  
Arm B uses a fixed list of 2024 winners (AAPL, MSFT, GOOGL, AMZN, NVDA, etc.) selected with full hindsight.
This is SURVIVORSHIP BIAS and LOOK-AHEAD BIAS.

**Use only as UPPER BOUND demonstration.**  
Do NOT cite as tradeable edge. Do NOT recommend as flagship regardless of returns.

### Arm A: QQQ Baseline

Arm A (QQQ buy-and-hold) is a citeable concentration baseline.
If QQQ beats SPY, it supports the product direction but is 'buy QQQ,' not Aletheia alpha.

### Arms C & D: Citeable KEEP Candidates

Only Arms C (point-in-time quality) and D (S&P 100 equal-weight) are citeable KEEP candidates.
They use ONLY information available at each rebalance date (no hindsight).

---

## Data & Methodology

- **Free data:** yfinance for all price history
- **Benchmark:** ^SPXTR (SPY total return) where available, SPY price-only fallback
- **Trading costs:** 7 bps round-trip (conservative for paper brokerage)
- **Rebalance frequency:** Quarterly for Arms C & D; buy-and-hold for Arm A; quarterly for Arm B
- **No covered calls:** This is pure long equity
- **Initial NAV:** $10,000
- **Point-in-time selection (Arm C):** Uses only data available as of each rebalance date
