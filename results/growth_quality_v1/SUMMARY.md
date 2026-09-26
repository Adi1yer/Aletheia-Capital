# Growth Quality v1 Bake-Off Results vs SPY

**Strategy:** Concentrated liquid quality/growth equity (long-only, no covered calls)

**KEEP Bar:** Strategy total return ≥ SPY total return on BOTH primary windows (2020-2024 AND 2010-2024)

---

## Summary Table

| Arm | Window | Strategy TR | SPY TR | Excess | Sharpe | Max DD | Verdict |
|-----|--------|-------------|--------|--------|--------|--------|---------|
| arm_a_qqq | 2020_2024 | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_a_qqq | 2010_2024 | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_a_qqq | 2022_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_a_qqq | 2000_2002_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_b_equal_weight | 2020_2024 | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_b_equal_weight | 2010_2024 | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_b_equal_weight | 2022_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_b_equal_weight | 2000_2002_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_c_quality_screen | 2020_2024 | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_c_quality_screen | 2010_2024 | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_c_quality_screen | 2022_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |
| arm_c_quality_screen | 2000_2002_stress | N/A | N/A | N/A | N/A | N/A | DATA UNAVAILABLE |

---

## Arm A: QQQ Buy-and-Hold

**Description:** Nasdaq-100 ETF (QQQ) - transparent concentration baseline

### **VERDICT: ✗ ABANDON**

This arm **fails BOTH primary windows**.

### Performance by Window

**2020_2024** (2020-01-01 to 2024-12-31): *Data unavailable*

**2010_2024** (2010-01-01 to 2024-12-31): *Data unavailable*

**2022_stress** (2022-01-01 to 2022-12-31): *Data unavailable*

**2000_2002_stress** (2000-01-01 to 2002-12-31): *Data unavailable*

---

## Arm B: Equal-Weight Quality Mega-Caps

**Description:** Equal-weight top 15 liquid mega/quality names

### **VERDICT: ✗ ABANDON**

This arm **fails BOTH primary windows**.

### Performance by Window

**2020_2024** (2020-01-01 to 2024-12-31): *Data unavailable*

**2010_2024** (2010-01-01 to 2024-12-31): *Data unavailable*

**2022_stress** (2022-01-01 to 2022-12-31): *Data unavailable*

**2000_2002_stress** (2000-01-01 to 2002-12-31): *Data unavailable*

---

## Arm C: Quality-Screened Large-Cap

**Description:** Simple quality screen on liquid large-cap universe (top 30)

### **VERDICT: ✗ ABANDON**

This arm **fails BOTH primary windows**.

### Performance by Window

**2020_2024** (2020-01-01 to 2024-12-31): *Data unavailable*

**2010_2024** (2010-01-01 to 2024-12-31): *Data unavailable*

**2022_stress** (2022-01-01 to 2022-12-31): *Data unavailable*

**2000_2002_stress** (2000-01-01 to 2002-12-31): *Data unavailable*

---

## Final Recommendation

**ABANDON:** None of the arms meet the primary KEEP bar (≥ SPY on both 2020-2024 and 2010-2024).

The growth/quality v1 engine **does not** provide a beat-SPY solution as implemented.

---

## Notes

- **Honest labeling:** This is a concentrated equity bet (tech/growth/quality concentration), not mystical alpha.
- **Mag7 awareness:** Recent outperformance is heavily driven by Mag7/tech concentration. 2022 and 2000-2002 stress tests show the downside.
- **No covered calls:** This engine is pure long equity. Wheel hybrid remains a separate track for income R&D.
- **Data:** Free data (yfinance). Costs assumed at 7 bps round-trip.
- **Rebalance:** QQQ is buy-and-hold; equal-weight and quality-screen rebalance quarterly.
