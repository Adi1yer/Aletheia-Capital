# Phase A: Covered Call Overwrite Intensity Bake-off
**Period:** 2020-01-02 to 2024-12-31
**Universe:** Bluechip 6-name (F, T, BAC, INTC, PFE, GE)
**Benchmark:** SPY Total Return = +95.30%

## Results Summary

| Arm | Overwrite % | OTM % | Total Return | vs SPY | Sharpe | Sortino | Max DD | Upside Cap | Downside Cap | CC Writes |
|-----|-------------|-------|--------------|--------|--------|---------|--------|------------|--------------|----------|
| A BASELINE 100PCT 5OTM | 100% | 5% | +55.00% | -40.29pp | 0.50 | 0.69 | -37.67% | 75.0% | 75.4% | 195 |
| B 75PCT 5OTM | 75% | 5% | +55.00% | -40.29pp | 0.50 | 0.69 | -37.67% | 75.0% | 75.4% | 195 |
| C 50PCT 5OTM | 50% | 5% | +55.00% | -40.29pp | 0.50 | 0.69 | -37.67% | 75.0% | 75.4% | 195 |
| D 50PCT 10OTM | 50% | 10% | +55.64% | -39.65pp | 0.52 | 0.72 | -37.40% | 74.5% | 75.1% | 215 |

## Key Findings

- **Baseline (100% overwrite):** +55.00% total return, -40.29pp vs SPY
- **75% overwrite, 5% OTM:** +55.00% total return (+0.00pp vs baseline), -40.29pp vs SPY (+0.00pp improvement)
- **50% overwrite, 5% OTM (BXMH-style):** +55.00% total return (+0.00pp vs baseline), -40.29pp vs SPY (+0.00pp improvement)
- **50% overwrite, 10% OTM (more upside retention):** +55.64% total return (+0.64pp vs baseline), -39.65pp vs SPY (+0.64pp improvement)

## Recommendation

**BORDERLINE.** 50% overwrite, 10% OTM (more upside retention) marginally improved vs baseline (+0.64pp), but below 2pp threshold for production change. Keep code as research knob (default=1.0).

## Notes

- Premium estimates: Synthetic Black-Scholes with 21-day realized vol (labeled honestly, not market IV)
- Regime/VRP gating: OFF (Phase A mechanics only)
- Partial overwrite = BXMH-style: write calls on only N% of eligible lots, rest stay uncovered long equity
- Citeable protocol: Bluechip liquid universe, frozen rules, no tuning on eval window

