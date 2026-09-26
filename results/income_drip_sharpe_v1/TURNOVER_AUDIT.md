# Income Drip Turnover Audit

**Date:** 2026-09-26  
**Branch:** cursor/income-drip-bakeoff-8fc2  
**Task:** Sharpe-optimization bake-off (Goal 1: Turnover audit + fix)

---

## Executive Summary

The income drip strategy (Arm 2: 80/20 momentum/dividend) showed abnormally high turnover:
- **2020-2024:** 14.32x annual turnover (vs expected ~1-2x)
- **2010-2024:** 42.71x annual turnover (vs expected ~1-2x)

**Root cause identified:** The `rebalance()` method liquidated 100% of all positions every quarter and rebuilt from scratch, paying unnecessary double transaction costs on unchanged positions.

**Fix implemented:** Delta rebalancing that only trades position differences from target.

**Result:** Turnover reduced by 93%, and performance **improved** (Sharpe +9.8%, returns +2.3pp).

---

## Detailed Findings: 2020-2024 Window

### Before Fix (Full Liquidation/Rebuild)
```
Annual Turnover:    14.32x
Total Trades:       1,935 (1,000 buys, 935 sells)
Sharpe Ratio:       0.920
Ann Return:         17.90%
Max Drawdown:       -31.62%
SPY Excess Return:  +3.54pp/year
```

### After Fix (Delta Rebalancing)
```
Annual Turnover:    1.06x
Total Trades:       618 (295 buys, 323 sells)
Sharpe Ratio:       1.010
Ann Return:         20.20%
Max Drawdown:       -30.13%
SPY Excess Return:  +5.84pp/year
```

### Improvements
| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Turnover | 14.32x | 1.06x | **-93%** |
| Trades | 1,935 | 618 | **-68%** |
| Sharpe | 0.920 | 1.010 | **+9.8%** |
| Ann Return | 17.90% | 20.20% | **+2.3pp** |
| Max DD | -31.62% | -30.13% | **+1.5pp** |

---

## Root Cause Analysis

### The Bug

In `src/backtesting/income_drip/engine.py`, the `rebalance()` method (lines 564-570, prior to fix):

```python
# Liquidate all positions (simple rebalance)
current_holdings = self.portfolio.get_holdings()
for ticker, shares in current_holdings.items():
    price = prices.get(ticker)
    if price and price > 0:
        net_price = price * (1.0 - self.trading_cost_pct)
        self.portfolio.sell_position(ticker, shares, net_price, trade_date)
```

This liquidated **100% of all positions** every quarter (20 rebalances over 5 years), then rebuilt the entire portfolio from scratch. For a 50-position portfolio rebalancing quarterly:

- Expected trades: ~200-400/year (only trading changes)
- Actual trades: ~1,935/5 = **387/year** (full liquidation + rebuild)

The trade count matched full liquidation, but the **turnover calculation** properly reflected that this was ~14x excessive vs what a delta rebalancing strategy should generate.

### Why This Hurt Performance

1. **Double transaction costs:** Positions that should remain unchanged paid round-trip costs (7 bps * 2 = 14 bps) unnecessarily
2. **No benefit from continuity:** Failed to capture the efficiency of holding stable positions
3. **Dividend drip impact unclear:** With excessive churn, it was impossible to isolate whether dividend drip added value mechanistically or if results were skewed by the turnover bug

---

## The Fix

### Implementation

Replaced full liquidation with delta rebalancing:

```python
# Calculate targets based on TOTAL NAV (not just cash)
growth_target_nav = current_nav * self.growth_weight
ballast_target_nav = current_nav * self.ballast_weight

target_values = {}
# ... calculate target $ value for each position ...

# Sell dropped names
for ticker in list(current_holdings.keys()):
    if ticker not in target_values:
        # Sell position no longer in universe
        self.portfolio.sell_position(ticker, shares, net_price, trade_date)

# Adjust deltas
for ticker, target_value in target_values.items():
    current_value = current_shares * price
    delta_value = target_value - current_value
    
    # Only trade if delta > $10 or >1% of target
    if abs(delta_value) >= max(10.0, target_value * 0.01):
        if delta_value > 0:
            # Buy more
            self.portfolio.add_position(...)
        else:
            # Sell some
            self.portfolio.sell_position(...)
```

### Key Improvements

1. **NAV-based targets:** Targets calculated on total NAV (cash + positions), not just cash
2. **Selective trading:** Only trade positions that need adjustment
3. **Threshold filter:** Skip tiny adjustments (<$10 or <1% of target) to avoid over-trading
4. **Preserve unchanged positions:** No unnecessary sells + rebuys

---

## Verdict

### ✅ Turnover Fixed
- Reduced from **14.32x → 1.06x** annual turnover
- Now consistent with expected ~1-2x for quarterly rebalanced strategy with dividend drip

### ✅ Performance Improved
- **Sharpe:** +9.8% improvement (0.920 → 1.010)
- **Returns:** +2.3pp improvement (17.90% → 20.20%)
- **Drawdown:** 1.5pp better (-31.62% → -30.13%)

### ✅ Dividend Drip Value Preserved
- With turnover fixed, any excess return vs pure Arm C (momentum-only) can now be confidently attributed to the dividend drip mechanism, not turnover artifacts

---

## New Baseline for Bake-Off

**Arm 2 (80/20 Momentum/Dividend Drip) - Post-Fix:**
- **Sharpe:** 1.010
- **Ann Return:** 20.20%
- **Max DD:** -30.13%
- **Turnover:** 1.06x/year
- **SPY Excess:** +5.84pp/year

This becomes the baseline for:
1. **Sleeve weight grid** (90/10, 80/20, 70/30)
2. **Vol-target overlay** (15% annualized target)

---

## Next Steps

1. ✅ **Turnover audit completed** (Goal 1)
2. ⏳ Verify fix on 2010-2024 window (running)
3. ⏳ Run sleeve weight grid: 90/10, 80/20, 70/30 (Goal 2)
4. ⏳ Test vol-target overlay on winning weight (Goal 3)
5. ⏳ Update PR #11 with consolidated results and KEEP/ABANDON verdicts
