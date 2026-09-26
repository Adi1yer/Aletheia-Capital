# Phase A: Covered Call Overwrite Intensity Bake-off
**Period:** 2020-01-02 to 2024-12-31
**Universe:** Bluechip 6-name (F, T, BAC, INTC, PFE, GE)
**Benchmark:** SPY Total Return = +95.30%

## Results Summary

| Arm | Overwrite % | OTM % | Total Return | vs SPY | Sharpe | Sortino | Max DD | Upside Cap | Downside Cap | CC Writes |
|-----|-------------|-------|--------------|--------|--------|---------|--------|------------|--------------|----------|
| A BASELINE 100PCT 5OTM | 100% | 5% | +75.27% | -20.03pp | 0.66 | 0.91 | -35.97% | 63.4% | 60.2% | 614 |
| B 75PCT 5OTM | 75% | 5% | +67.77% | -27.52pp | 0.60 | 0.83 | -35.97% | 68.0% | 66.3% | 489 |
| C 50PCT 5OTM | 50% | 5% | +73.47% | -21.83pp | 0.61 | 0.85 | -35.97% | 71.2% | 69.0% | 349 |
| D 50PCT 10OTM | 50% | 10% | +55.80% | -39.50pp | 0.52 | 0.72 | -37.40% | 73.9% | 74.4% | 243 |

## Key Findings

- **Baseline (100% overwrite):** +75.27% total return, -20.03pp vs SPY
- **75% overwrite, 5% OTM:** +67.77% total return (-7.50pp vs baseline), -27.52pp vs SPY (-7.49pp improvement)
- **50% overwrite, 5% OTM (BXMH-style):** +73.47% total return (-1.80pp vs baseline), -21.83pp vs SPY (-1.80pp improvement)
- **50% overwrite, 10% OTM (more upside retention):** +55.80% total return (-19.47pp vs baseline), -39.50pp vs SPY (-19.47pp improvement)

## Recommendation

**KEEP default (100% overwrite) for now.** Partial overwrite did not improve absolute excess vs SPY by meaningful margin.

## Notes

- Premium estimates: Synthetic Black-Scholes with 21-day realized vol (labeled honestly, not market IV)
- Regime/VRP gating: OFF (Phase A mechanics only)
- Partial overwrite = BXMH-style: write calls on only N% of eligible lots, rest stay uncovered long equity
- Citeable protocol: Bluechip liquid universe, frozen rules, no tuning on eval window

