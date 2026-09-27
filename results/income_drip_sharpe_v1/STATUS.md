# Income Drip Sharpe-Optimization Bake-Off

**Status:** In Progress  
**Branch:** cursor/income-drip-bakeoff-8fc2  
**PR:** #11  
**Date:** 2026-09-26

---

## Executive Summary

This bake-off tests three improvements to the income drip strategy (80/20 momentum/dividend):

1. **✅ COMPLETE: Turnover Audit & Fix** - KEEP (Goal 1)
2. **🔄 IN PROGRESS: Sleeve Weight Grid** - Testing 90/10, 80/20, 70/30 (Goal 2)
3. **⏳ PENDING: Vol-Target Overlay** - 15% vol targeting (Goal 3)

---

## Goal 1: Turnover Audit & Fix ✅ COMPLETE

### Problem Identified
The rebalance method liquidated 100% of positions every quarter and rebuilt from scratch, causing excessive turnover and wasteful transaction costs.

### Root Cause
```python
# Bug: Full liquidation every quarter (lines 564-570, pre-fix)
for ticker, shares in current_holdings.items():
    self.portfolio.sell_position(ticker, shares, net_price, trade_date)
```

### Fix Implemented
Delta rebalancing: Only trade position deltas, keep unchanged positions.

### Results: 2020-2024

| Metric | Before Fix | After Fix | Improvement |
|--------|------------|-----------|-------------|
| Annual Turnover | 14.32x | 1.06x | **-93%** |
| Total Trades | 1,935 | 618 | **-68%** |
| Sharpe Ratio | 0.920 | 1.010 | **+9.8%** |
| Ann Return | 17.90% | 20.20% | **+2.3pp** |
| Max DD | -31.62% | -30.13% | **+1.5pp** |

### Results: 2010-2024

| Metric | Before Fix | After Fix | Improvement |
|--------|------------|-----------|-------------|
| Annual Turnover | 42.71x | 2.29x | **-95%** |
| Sharpe Ratio | 1.080 | 1.080 | **0%** (preserved) |
| Ann Return | 17.72% | 18.79% | **+1.1pp** |
| Max DD | -32.96% | -33.51% | -0.6pp |

### Verdict: ✓ KEEP FIX

The turnover bug was hurting performance by paying unnecessary transaction costs. The fix:
- Reduces turnover by 93-95% to realistic levels (1-2x/year)
- Improves Sharpe on 2020-2024 (+9.8%)
- Preserves Sharpe on 2010-2024 (flat)
- Improves returns on both windows

**New Baseline (80/20 Post-Fix):**
- **2020-2024:** Sharpe 1.010, Return 20.20%, DD -30.13%, Turnover 1.06x
- **2010-2024:** Sharpe 1.080, Return 18.79%, DD -33.51%, Turnover 2.29x

---

## Goal 2: Sleeve Weight Grid 🔄 IN PROGRESS

### Test Configuration
- **Weights tested:** 90/10, 80/20, 70/30 (growth momentum / dividend ballast)
- **Windows:** 2020-2024 ✅, 2010-2024 🔄 (running)
- **Mechanics:** Fixed post-turnover-fix delta rebalancing
- **KEEP Bar:** Sharpe improves on BOTH windows vs 80/20 baseline

### Results: 2020-2024 ✅ COMPLETE

| Split | Sharpe | Ann Return | Max DD | vs Baseline Sharpe |
|-------|--------|------------|--------|-------------------|
| 90/10 | 0.990 | 20.56% | -30.02% | **-0.020** ❌ |
| 80/20 | 1.010 | 20.20% | -30.13% | **BASELINE** |
| 70/30 | 0.990 | 19.18% | -30.24% | **-0.020** ❌ |

**Winner (2020-2024):** 80/20 has best Sharpe

### Results: 2010-2024 🔄 RUNNING

Currently processing 90/10 sleeve weight backtest (~40% complete as of last check).  
Estimated completion: 3-4 hours from start.

### Interim Verdict

Based on 2020-2024 alone:
- ✗ ABANDON 90/10 - Sharpe worse than baseline
- ✓ BASELINE 80/20 - Best on 2020-2024
- ✗ ABANDON 70/30 - Sharpe worse than baseline

**Final verdict pending 2010-2024 completion to satisfy KEEP bar (both windows).**

---

## Goal 3: Vol-Target Overlay ⏳ PENDING

### Configuration (Pre-Registered)
- **Target:** 15% annualized volatility
- **Lookback:** 63 trading days (3 months)
- **Method:** Exposure = min(1.0, target_vol / realized_vol)
- **Remainder:** Cash (uninvested)
- **Rebalance:** Quarterly (aligned with strategy)
- **No lookahead:** Point-in-time only

### Status
- Script created: `scripts/run_vol_target_overlay.py`
- **Pending:** Run on 80/20 baseline (post-fix) for both windows
- **Pending after:** Sleeve grid 2010-2024 completes to confirm 80/20 winner

---

## Deliverables Status

### ✅ Completed
- [x] Turnover audit + fix implementation
- [x] Turnover audit results (2020-2024, 2010-2024)
- [x] Sleeve grid 2020-2024 results
- [x] Code pushed to branch cursor/income-drip-bakeoff-8fc2
- [x] Scripts: `run_sleeve_weight_grid.py`, `run_vol_target_overlay.py`
- [x] Documentation: `TURNOVER_AUDIT.md`, `SLEEVE_WEIGHT_GRID.md` (partial)

### 🔄 In Progress
- [ ] Sleeve grid 2010-2024 (running, ~40% complete as of 18:32 UTC)

### ⏳ Remaining
- [ ] Vol-target overlay (both windows)
- [ ] Consolidated `SUMMARY.md` + `consolidated_results.json`
- [ ] Update PR #11 body with final KEEP/ABANDON verdicts
- [ ] Final git push

---

## KEEP / ABANDON Summary (Interim)

### Goal 1: Turnover Fix
**✓ KEEP** - Improves performance on both windows by eliminating wasteful transaction costs.

### Goal 2: Sleeve Weights
**2020-2024 only (interim):**
- ✗ ABANDON 90/10
- ✓ KEEP 80/20 (baseline)
- ✗ ABANDON 70/30

**Awaiting 2010-2024 results to finalize verdict per KEEP bar (must improve on BOTH windows).**

### Goal 3: Vol-Target
**⏳ PENDING** - Run after sleeve grid confirms 80/20 winner

---

## Next Steps

1. **Monitor 2010-2024 sleeve grid completion** (~3-4 hours remaining)
2. **Finalize sleeve weight verdict** (check if 90/10 or 70/30 beat 80/20 on BOTH windows)
3. **Run vol-target overlay** on winning sleeve weight (default 80/20)
4. **Consolidate results** into final SUMMARY.md + JSON
5. **Update PR #11** with complete KEEP/ABANDON per knob
6. **Push final commit**

---

## Files

### Results
```
results/income_drip_sharpe_v1/
├── TURNOVER_AUDIT.md
├── audit_before_after/
│   ├── 2020_2024/
│   │   ├── summary_arm_2_momentum_div_drip.json
│   │   └── trades_arm_2_momentum_div_drip.json
│   ├── 2010_2024/
│   │   ├── summary_arm_2_momentum_div_drip.json
│   │   └── trades_arm_2_momentum_div_drip.json
│   └── consolidated_results.json
├── sleeve_grid/
│   ├── SLEEVE_WEIGHT_GRID.md
│   ├── 2020_2024/
│   │   ├── summary_sleeve_90_10.json
│   │   ├── summary_sleeve_80_20.json
│   │   └── summary_sleeve_70_30.json
│   ├── 2010_2024/ (🔄 in progress)
│   └── consolidated_sleeve_grid.json
└── vol_target/ (⏳ pending)
```

### Scripts
```
scripts/
├── run_income_drip_bakeoff.py (baseline runner)
├── run_sleeve_weight_grid.py (Goal 2)
└── run_vol_target_overlay.py (Goal 3)
```

### Code Changes
```
src/backtesting/income_drip/engine.py
  - Fixed: rebalance() method (delta rebalancing)
```

---

## Technical Notes

### Data Caching
- Reusing `.data_cache/` from audit run to avoid re-fetching
- yfinance free tier with 2s rate limiting
- Price data cached, dividend data partially cached (pickle issues with local classes)

### Performance
- 2020-2024 window: ~20 minutes per sleeve weight
- 2010-2024 window: ~75 minutes per sleeve weight
- Full 2010-2024 grid (3 sleeve weights): ~3.75 hours

### Environment
- Free data only (yfinance)
- No live wheel-10k-paper-v1 impact
- All results in `results/income_drip_sharpe_v1/`
