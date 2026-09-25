# VIX-Gated Wheel-Hybrid — Quick Start

## Overview

Test wheel-hybrid covered call strategies with **free VIX regime gating** (no API keys required).

Uses **real wheel-hybrid engine** with VIX (CBOE volatility index) as regime signal.

## Run Bake-Off

Compare always-on vs VIX-gated on 2020-2024 bluechip:

```bash
python3 scripts/run_vrp_bakeoff.py \
  --start 2020-01-02 \
  --end 2024-12-31 \
  --nav 10000 \
  --universe bluechip \
  --iv-source vix \
  --min-vrp 0.10 \
  --out docs/backtest_results/vix_gated
```

### IV Source Options

- `--iv-source vix` — FREE VIX-based regime signal (no API key)
- `--iv-source csv --iv-csv path/to/iv.csv` — Market IV from file
- `--iv-source synthetic` — Research-only (not implemented)

### Universe Options

- `bluechip` — Low-priced value stocks (F, T, BAC, INTC, PFE, GE)
- `expanded` — Larger set of wheel candidates
- `auto` — Dynamic selection

## Output

Results saved to `docs/backtest_results/vix_gated/`:

```
bakeoff_2020-01-02_2024-12-31.json
```

Sample output:

```
================================================================================
VRP BAKE-OFF RESULTS (2020-01-02 to 2024-12-31)
================================================================================
Universe: bluechip (6 tickers)
IV Source: vix_free_regime
ℹ️  Using FREE VIX (REGIME SIGNAL, index-level vol)
================================================================================

Metric                         Legacy (Off)         Gated (On)           Delta          
-------------------------------------------------------------------------------------
Absolute Return                +55.00%              +33.78%              -21.22%        
SPY Return                     +95.30%              +95.30%                             
Excess vs SPY                  -40.30%              -61.51%              -21.21%        
Premium Collected              $6,981.07            $1,491.14            $-5,489.93     

Gate Statistics:
  Writes allowed:      1472
  Blocked (low VRP):   8534
  Block rate:          85.3%
================================================================================

❌ Gated strategy underperforms legacy (no edge detected)
```

## Run Tests

```bash
python3 -m pytest tests/test_vix_iv_provider.py -v
```

All 8 tests should pass.

## Architecture

### VIX Provider

**`vix_iv_provider.py`** — FREE VIX data via yfinance

- Implements `IVProvider` protocol (get_atm_iv, get_iv_rank, get_iv_rv_spread)
- Caches VIX data locally (data/vix_cache/vix_daily.csv)
- Returns VIX level as IV proxy for all symbols (index-level signal)

### Integration

Uses **existing wheel-hybrid infrastructure**:

- `WheelHybridBacktest` — Real backtest engine
- `EdgeGate` — VRP-based write filtering
- `RegimeDetector` — Optional regime detection
- `WheelPortfolio` — Position tracking
- `PremiumModel` — Option premium estimation

### VRP Gating Logic

```python
VRP = (VIX - Realized Vol) / Realized Vol

if VRP >= min_vrp:
    allow_write()  # VIX is rich vs realized
else:
    block_write()  # VIX is cheap, hold delta
```

## Key Findings (2020-2024 Bluechip)

### Result: -21.22% underperformance vs always-on

**Why VIX-gating failed:**

1. **VIX ≠ name vol** — Index diversification reduces vol vs single stocks
2. **VRP inverted 85% of time** — VIX < name realized vol
3. **Blocked 8,534 writes** — Only 1,472 allowed (14.7%)
4. **Less premium collected** — $1,491 vs $6,981 always-on

### What VIX Actually Measures

- **VIX = SPX 30-day implied vol** (from SPX option prices)
- Represents **market-wide** vol expectations
- Does NOT capture **name-specific** factors:
  - Earnings risk
  - Sector rotation
  - Idiosyncratic shocks

## Use Cases

### ✅ Good Use: VIX for Macro Regime

Use VIX to detect **market stress**, not name-level writes:

```bash
# Enable regime detection
python3 scripts/run_vrp_bakeoff.py \
  --start 2020-01-02 \
  --end 2024-12-31 \
  --universe bluechip \
  --iv-source vix \
  --enable-regime \
  --out docs/backtest_results/vix_gated
```

Regime states:
- **VIX > 30** → DEFENSIVE (reduce risk, raise cash)
- **VIX 15-30** → HARVEST_VRP (normal wheel operation)
- **VIX < 15** → HOLD_DELTA (skip writes, hold shares for melt-up)

### ❌ Bad Use: VIX for Name-Level Writes

Do NOT use VIX to gate individual stock CC/CSP writes:
- Index vol ≠ stock vol
- Misses name-specific IV richness
- Results in VRP inversion (blocks profitable writes)

## Next Steps

### For Production Edge

1. **Get single-name IV data** — Polygon/Theta/OPRA APIs
2. **Use VIX for regime only** — Market stress filter, not write gate
3. **Test different universes** — May work better on SPY-correlated mega-caps

### For Research

1. **Test longer windows** — Include 2008, 2015-2016 high-VIX periods
2. **Adjust thresholds** — Lower min_vrp (0.05?) or use percentile
3. **Hybrid gating** — VIX regime + name IV spread

## Dependencies

Already in repo:
- yfinance (VIX download)
- pandas (data handling)
- structlog (logging)

No paid API keys required.

## Documentation

- `docs/VIX_REGIME_BAKEOFF.md` — Full results analysis
- `docs/EDGE_VRP_ROADMAP.md` — VRP project roadmap
- `docs/WHITEPAPER_WHEEL_HYBRID.md` — Strategy whitepaper
