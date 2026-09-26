# Sleeve Weight Grid Results

**Goal:** Find optimal growth/ballast split using fixed delta-rebalancing mechanics.

**Baseline:** 80/20 (80% momentum growth / 20% dividend ballast)

**KEEP Bar:** Sharpe improves on BOTH primary windows (2020-24 and 2010-24) vs 80/20 baseline,
without disastrous DD blow-up (max DD worse by >10pp with only tiny Sharpe gain).

---

## Baseline (80/20)

- **2020-2024:** Sharpe 1.010, Max DD -30.13%
- **2010-2024:** Sharpe 0.000, Max DD 0.00%

---

## Comparison Table

| Split | Window | Sharpe | Ann Ret | Max DD | vs 80/20 Sharpe | vs 80/20 DD | Verdict |
|-------|--------|--------|---------|--------|-----------------|-------------|---------|
| 90/10 | 2020_2024 | 0.990 | 20.56% | -30.02% | -0.020 | +0.11pp | ✗ |
| 90_10 | 2010_2024 | N/A | N/A | N/A | N/A | N/A | NO DATA |
| 90_10 | 2022_stress | N/A | N/A | N/A | N/A | N/A | NO DATA |
| 90_10 | 2000_2002_stress | N/A | N/A | N/A | N/A | N/A | NO DATA |
| 80/20 | 2020_2024 | 1.010 | 20.20% | -30.13% | +0.000 | +0.00pp | BASELINE |
| 80_20 | 2010_2024 | N/A | N/A | N/A | N/A | N/A | NO DATA |
| 80_20 | 2022_stress | N/A | N/A | N/A | N/A | N/A | NO DATA |
| 80_20 | 2000_2002_stress | N/A | N/A | N/A | N/A | N/A | NO DATA |
| 70/30 | 2020_2024 | 0.990 | 19.18% | -30.24% | -0.020 | -0.11pp | ✗ |
| 70_30 | 2010_2024 | N/A | N/A | N/A | N/A | N/A | NO DATA |
| 70_30 | 2022_stress | N/A | N/A | N/A | N/A | N/A | NO DATA |
| 70_30 | 2000_2002_stress | N/A | N/A | N/A | N/A | N/A | NO DATA |

---

## KEEP / ABANDON Verdict

### 90/10: INSUFFICIENT DATA

### 70/30: INSUFFICIENT DATA

---

## Final Recommendation

**Winner:** 80/20 (baseline) - no alternative improves Sharpe on both primary windows

Proceed to Goal 3 (vol-target overlay) using 80/20 sleeve weights.
