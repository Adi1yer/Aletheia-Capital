# Directional Crisis Overlay Bake-Off Results

**Universe**: BLUECHIP  
**Period**: 2020-01-01 to 2024-12-31  
**Initial NAV**: $10,000  
**Benchmark**: ^SPXTR

## Summary

| Metric | Baseline | Crisis (SPY/BIL) | Delta |
|--------|----------|------------------|-------|
| Absolute Return | +56.2% | +48.1% | -8.0pp |
| SPY Return | +95.3% | +95.3% | — |
| Excess vs SPY | -39.1pp | -47.2pp | -8.0pp |
| Max Drawdown | -35.4% | -35.4% | +0.0pp |
| Sharpe | 0.55 | 0.49 | -0.06 |
| Turnover | 2.34x | 27.92x | +25.58x |

## Recommendation

❌ **ABANDON**: Crisis overlay underperforms or does not meet +2pp hurdle (-8.0pp)

## Reproduce

```bash
python3 scripts/run_directional_crisis_bakeoff.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --universe bluechip \
  --nav 10000 \
  --out docs/backtest_results/directional_crisis_overlay/2020_2024_bluechip
```
