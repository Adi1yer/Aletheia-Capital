# Directional Sleeve Bake-Off: Bluechip Equal-Weight vs SPY Buy-and-Hold

## Test Period: 2020-01-01 → 2024-12-31

This bake-off compares two directional sleeve implementations on the **same bluechip universe** (6 names: F, T, BAC, INTC, PFE, GE) to isolate the effect of the directional sleeve strategy without confounding from universe size.

## Hypothesis

Most of the SPY lag may be underweight mega-cap beta in the ~30% directional sleeve (equal-weight bluechips), not a missing timing signal. Replacing that sleeve with **static buy-and-hold SPY** (no SMA gate, no momentum, no monthly churn beyond initial funding / rare rebalance to target weight) should improve absolute return vs baseline without the churn tax.

## Arms

### Arm A: Bluechip Equal-Weight (Baseline)
- **Directional sleeve**: Equal-weight from the bluechip universe
- **Behavior**: Buys directional positions in available tickers, spreads capital equally
- **Turnover**: Moderate (adds positions as capital available)

### Arm B: SPY Buy-and-Hold
- **Directional sleeve**: Static SPY (^SPXTR total return index) position
- **Behavior**: Initial buy at ~30% NAV, rebalance only if drift > 5%
- **Turnover**: Minimal in directional sleeve (buy-and-hold)

## Results

| Metric | Arm A (bluechip_ew) | Arm B (spy_buyhold) | Delta (B - A) |
|--------|---------------------|---------------------|---------------|
| **Absolute Return** | +55.0% | +27.87% | **-27.13pp** |
| **Excess vs SPY** | -40.3% | -67.43% | **-27.13pp** |
| **Sharpe** | 0.50 | 0.37 | -0.13 |
| **Sortino** | 0.69 | 0.51 | -0.18 |
| **Max DD** | -37.67% | -31.33% | +6.34pp (better) |
| **Beta** | 0.77 | 0.50 | -0.27 |
| **Alpha (annual)** | -0.63% | -1.37% | -0.74pp |
| **Turnover** | 1.56x | 1.82x | +0.26x |
| **Premium Collected** | $6,981 | $7,453 | +$472 |
| **CC Writes** | 195 | 211 | +16 |

## Interpretation

### ❌ ABANDON: Arm B underperforms Arm A by 27.13pp

**Key findings**:

1. **Large absolute return gap**: Arm B (+27.87%) trails Arm A (+55.0%) by 27pp, nearly **halving** the return
2. **Worse excess vs SPY**: Arm B's SPY lag (-67.43%) is 27pp worse than Arm A (-40.3%)
3. **Lower beta but worse outcome**: Arm B has lower beta (0.50 vs 0.77), but negative alpha (-1.37% vs -0.63%)
4. **Similar premium collection**: Arm B collected slightly more premium ($7,453 vs $6,981), but this didn't compensate for lower equity gains
5. **Slightly better max DD**: Arm B had a 6pp shallower max drawdown (-31% vs -38%), but at the cost of much lower returns

### Why SPY Buy-and-Hold Underperformed

The hypothesis that mega-cap beta would improve returns was **falsified**. Possible explanations:

1. **Wheel sleeve dominance**: With 70% allocation to the wheel, the directional sleeve's composition matters less than expected
2. **Bluechip diversification value**: Equal-weight across 6 bluechips may provide better diversification vs wheel positions than a single SPY holding
3. **Capital allocation timing**: The equal-weight approach adds directional positions gradually as capital becomes available, potentially capturing better entry points
4. **Beta reduction hurts**: Lower beta (0.50 vs 0.77) reduced correlation with SPY, but also reduced absolute gains in a rising market

### Comparison to Citeable Baseline

- **Citeable baseline** (docs/backtest_results/wheel_hybrid/2020_2024_10k_bluechip): +55.0% (matches Arm A)
- **Arm A validation**: ✅ Arm A matches the citeable baseline within 0.01pp, confirming correct wiring
- **Arm B vs citeable**: -27.13pp underperformance

## Recommendation

**ABANDON**: The spy_buyhold directional sleeve mode does NOT improve returns vs the bluechip_ew baseline. The -27pp underperformance vastly exceeds the ≥2pp hurdle for adoption.

## Reproduce

```bash
python3 scripts/run_directional_sleeve_bakeoff.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --universe bluechip \
  --out docs/backtest_results/directional_spy_buyhold/2020_2024_bluechip
```

## Artifacts

- `summary.json`: Full metrics comparison
- `arm_a_equity_curve.csv`: Arm A (bluechip_ew) daily NAV
- `arm_b_equity_curve.csv`: Arm B (spy_buyhold) daily NAV

## Notes

- **Universe**: Bluechip (F, T, BAC, INTC, PFE, GE) for both arms
- **Wheel parameters**: Same for both arms (70% allocation, 21-45 DTE CCs, 14-45 DTE CSPs)
- **Benchmark**: ^SPXTR (SPY total return)
- **Initial NAV**: $10,000
- **No timing overlays**: Pure structural bake-off, no SMA gates or momentum filters
