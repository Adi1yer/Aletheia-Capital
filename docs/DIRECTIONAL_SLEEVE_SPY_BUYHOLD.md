# Directional Sleeve Mode: SPY Buy-and-Hold Research

**Status**: ❌ **ABANDONED** (negative result, −27pp vs baseline)

**Date**: 2026-09-26

---

## Hypothesis

Most of the SPY lag in the wheel-hybrid strategy (−40pp in 2020–2024 bluechip baseline) may be due to **underweight mega-cap beta** in the ~30% directional sleeve, which uses equal-weight bluechips. Replacing the directional sleeve with **static buy-and-hold SPY** (no timing signals, minimal rebalance) should:

1. Increase beta correlation with SPY
2. Capture mega-cap growth (AAPL, MSFT, NVDA, etc.)
3. Reduce churn in the directional sleeve
4. Improve absolute return without complex timing logic

---

## Implementation

### Engine Changes

**File**: `src/backtesting/wheel_hybrid/engine.py`

**New parameter**: `directional_sleeve_mode`
- `bluechip_ew` (default): Original equal-weight behavior from universe
- `spy_buyhold`: Static SPY/benchmark buy-and-hold

**Configuration**:
```python
WheelHybridBacktest(
    directional_sleeve_mode="spy_buyhold",  # or "bluechip_ew"
    directional_rebalance_band_pct=0.05,    # 5% drift triggers rebalance
)
```

### Behavior: `spy_buyhold` Mode

1. **Initial buy**: On first allocation, buy SPY (or benchmark ticker) at ~30% NAV
2. **Rebalance trigger**: Only if drift exceeds ±5% of target NAV (wide band)
3. **No monthly churn**: Positions held statically between rebalances
4. **No timing gates**: No SMA200, momentum, or regime overlays

Compare to `bluechip_ew`:
- Adds directional positions from universe tickers as capital available
- Equal-weight allocation across multiple names
- Gradual capital deployment

---

## Test Design

**Bake-off script**: `scripts/run_directional_sleeve_bakeoff.py`

**Arms**:
- **Arm A** (baseline): `directional_sleeve_mode=bluechip_ew`
- **Arm B** (test): `directional_sleeve_mode=spy_buyhold`

**Universe**: Bluechip (6 names: F, T, BAC, INTC, PFE, GE) for **both arms** to isolate directional sleeve effect

**Period**: 2020-01-01 → 2024-12-31 (matches citeable baseline)

**Validation**: Arm A must match the citeable +55.0% bluechip baseline within a few pp

---

## Results: 2020–2024 Bluechip Universe

| Metric | Arm A (bluechip_ew) | Arm B (spy_buyhold) | Delta (B - A) | Keep Threshold |
|--------|---------------------|---------------------|---------------|----------------|
| **Absolute Return** | **+55.0%** | +27.87% | **−27.13pp** | ≥ +2pp |
| **Excess vs SPY** | −40.3% | −67.43% | **−27.13pp** | — |
| **Sharpe** | 0.50 | 0.37 | −0.13 | — |
| **Sortino** | 0.69 | 0.51 | −0.18 | — |
| **Max DD** | −37.67% | −31.33% | **+6.34pp** | — |
| **Beta** | 0.77 | 0.50 | −0.27 | — |
| **Alpha (annual)** | −0.63% | −1.37% | −0.74pp | — |
| **Turnover** | 1.56x | 1.82x | +0.26x | — |
| **Premium Collected** | $6,981 | $7,453 | +$472 | — |
| **CC Writes** | 195 | 211 | +16 | — |

### Validation

✅ **Arm A matches citeable baseline**: +55.0% (within 0.01pp of docs/backtest_results/wheel_hybrid/2020_2024_10k_bluechip)

---

## Recommendation: ABANDON

**Verdict**: ❌ **spy_buyhold underperforms by 27pp** (nearly halves return)

### Why It Failed

1. **Lower absolute return**: +27.87% vs +55.0% (−27pp is a massive gap)
2. **Worse SPY lag**: −67pp vs −40pp (directional sleeve wasn't the problem)
3. **Beta reduction didn't help**: Lower beta (0.50 vs 0.77) but negative alpha (−1.37%)
4. **Premium not enough**: Collected $472 more premium, but equity gains down $3,713
5. **Hypothesis falsified**: Mega-cap beta ≠ better returns in this strategy

### Likely Explanation

The **wheel sleeve (70%) dominates** PnL. The directional sleeve's ~30% allocation matters, but:
- Equal-weight bluechips provide better **diversification** vs wheel positions
- Gradual capital deployment may capture **better entry timing**
- Single SPY holding reduces diversification and lowers correlation with wheel names

**Conclusion**: The SPY lag is not primarily due to directional sleeve composition. Other factors (wheel premium capture, universe selection, etc.) matter more.

---

## Reproduce

```bash
# Run bake-off
python3 scripts/run_directional_sleeve_bakeoff.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --universe bluechip \
  --out docs/backtest_results/directional_spy_buyhold/2020_2024_bluechip

# Or run individual arms
python3 scripts/run_wheel_hybrid_backtest.py \
  --start 2020-01-01 --end 2024-12-31 \
  --universe bluechip \
  --directional-sleeve-mode bluechip_ew \
  --out data/backtests/arm_a

python3 scripts/run_wheel_hybrid_backtest.py \
  --start 2020-01-01 --end 2024-12-31 \
  --universe bluechip \
  --directional-sleeve-mode spy_buyhold \
  --out data/backtests/arm_b
```

---

## Artifacts

**Committed** (citeable):
- `docs/backtest_results/directional_spy_buyhold/2020_2024_bluechip/summary.json`
- `docs/backtest_results/directional_spy_buyhold/2020_2024_bluechip/README.md`

**Generated** (reproducible, gitignored):
- `arm_a_equity_curve.csv`
- `arm_b_equity_curve.csv`

---

## Code Changes

**Modified**:
- `src/backtesting/wheel_hybrid/engine.py`: Added `directional_sleeve_mode` parameter and `_buy_directional_spy_buyhold()` method
- `scripts/run_wheel_hybrid_backtest.py`: Added `--directional-sleeve-mode` and `--directional-rebalance-band` flags

**Added**:
- `scripts/run_directional_sleeve_bakeoff.py`: Automated bake-off runner

---

## Lessons Learned

1. **Validate assumptions with data**: The "underweight beta" hypothesis seemed plausible but failed empirically
2. **Wheel sleeve dominates**: 70% allocation means directional sleeve changes have limited impact
3. **Diversification matters**: Equal-weight across multiple names > single SPY holding for this strategy
4. **Negative results are valuable**: Documenting what doesn't work prevents future wheel-spinning

---

## Next Steps

**Do NOT**:
- Merge spy_buyhold mode into production config (abandoned)
- Revive this approach without major strategy redesign

**Consider instead**:
1. **Expand universe** (expanded universe already shows +338% vs +55% bluechip in docs/WHITEPAPER_WHEEL_HYBRID.md)
2. **Improve wheel sleeve**: Better strike selection, dynamic OTM %, regime-aware CC writing
3. **Validate IV edge**: Real market IV data (OPRA/Polygon) vs current realized vol proxy

---

## References

- **Citeable baseline**: docs/backtest_results/wheel_hybrid/2020_2024_10k_bluechip (+ 55.0%, −40.3% vs SPY)
- **Whitepaper**: docs/WHITEPAPER_WHEEL_HYBRID.md (expanded universe shows 6x better returns)
- **Bake-off results**: docs/backtest_results/directional_spy_buyhold/2020_2024_bluechip/
