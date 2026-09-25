# VIX-Gated Wheel-Hybrid Backtest — Quick Start

## Overview

Test wheel-hybrid covered call strategies with **free VIX regime gating** (no API keys required).

Two modes:
- **Always-On**: Write CCs every day (baseline)
- **VIX-Gated**: Scale CC writes based on VIX percentile rank

## Installation

```bash
# Install dependencies (if not already done)
python3 -m pip install yfinance pandas structlog pytest
```

## Run a Bake-Off

Compare always-on vs VIX-gated strategies:

```bash
# Use predefined test window
python3 scripts/run_vrp_bakeoff.py --preset bluechip-2020-2024

# Custom date range
python3 scripts/run_vrp_bakeoff.py \
  --start-date 2020-01-01 \
  --end-date 2024-12-31 \
  --universe bluechip \
  --capital 10000
```

### Available Presets

- `bluechip-2020-2024`: Full 2020s, 10 large-cap stocks (AAPL, MSFT, etc.)
- `covid-recovery`: 2020-04-01 to 2021-12-31
- `full-2020s`: 2020-01-01 to 2024-12-31

### Available Universes

- `bluechip`: AAPL, MSFT, JPM, JNJ, PG, KO, DIS, BA, CAT, MMM
- `wheel_classic`: F, SOFI, NOK, ITUB, ABEV, GOLD, NIO, PLUG, LCID, RIVN

## Output

Results saved to `docs/backtest_results/vix_gated/`:
- `summary_<dates>.json`: Performance metrics
- `equity_curves_<dates>.csv`: Daily equity time series

Sample output:

```
================================================================================
VRP BAKE-OFF RESULTS
================================================================================

Window: 2020-01-01 to 2024-12-31
Universe: 10 tickers

SPY Benchmark:     +95.30%

Always-On:         +36.84%  (Sharpe: 1.172)
VIX-Gated:         +26.81%  (Sharpe: 1.214)

Alpha vs Always-On: -10.02%
Alpha vs SPY:       -68.48%

≥2% hurdle vs always-on: ✗ FAIL
================================================================================
```

## Run Tests

```bash
python3 -m pytest tests/test_vix_gated_wheel.py -v
```

All 12 tests should pass.

## Architecture

### Core Components

1. **VixDataProvider** (`vix_provider.py`)
   - Free VIX data via yfinance (^VIX)
   - Local cache for CI reproducibility
   - Percentile rank calculation

2. **EdgeGate** (`edge_gate.py`)
   - ALWAYS_ON: Write all lots every day
   - VIX_GATED: Scale by VIX percentile (30th/70th thresholds)
   - Returns "intensity" 0.0-1.0 controlling overwrite fraction

3. **WheelHybridSimulator** (`simulator.py`)
   - Simplified backtest engine
   - 70% wheel / 30% directional split
   - Monthly CC writes with premium estimation
   - No slippage, chain selection, or assignment modeling

4. **IVProvider** (`iv_provider.py`)
   - Interface for IV data sources
   - `NoOpIVProvider`: Always-on mode
   - `CsvIVProvider`: Phase 2 testing (not used in VIX path)

### Regime Logic

```python
from src.backtesting.wheel_hybrid.vix_provider import VixDataProvider
from src.backtesting.wheel_hybrid.edge_gate import EdgeGate, EdgeMode

# VIX-gated mode
vix_provider = VixDataProvider()
gate = EdgeGate(
    mode=EdgeMode.VIX_GATED,
    vix_provider=vix_provider,
    vix_percentile_threshold_low=30.0,
    vix_percentile_threshold_high=70.0,
)

# Get overwrite intensity for a date
intensity = gate.get_overwrite_intensity(date(2023, 6, 15))
# intensity ∈ [0.0, 1.0]

# Binary decision
should_write = gate.should_write_cc(date(2023, 6, 15))
```

## Customization

### Adjust VIX Thresholds

Edit `edge_gate.py` or pass custom thresholds:

```python
gate = EdgeGate(
    mode=EdgeMode.VIX_GATED,
    vix_provider=vix_provider,
    vix_percentile_threshold_low=20.0,   # More aggressive
    vix_percentile_threshold_high=80.0,  # Wider neutral zone
)
```

### Test Different Universes

Add to `UNIVERSES` dict in `scripts/run_vrp_bakeoff.py`:

```python
UNIVERSES = {
    "bluechip": ["AAPL", "MSFT", ...],
    "wheel_classic": ["F", "SOFI", ...],
    "tech_heavy": ["NVDA", "TSLA", "AMD", ...],  # New
}
```

Then run:

```bash
python3 scripts/run_vrp_bakeoff.py --universe tech_heavy --preset full-2020s
```

### Add Test Windows

Edit `WINDOWS` dict:

```python
WINDOWS = {
    "covid-recovery": (date(2020, 4, 1), date(2021, 12, 31)),
    "2015-crisis": (date(2015, 1, 1), date(2016, 12, 31)),  # New
}
```

## Known Limitations

1. **Simplified execution** — No slippage, partial fills, or chain selection
2. **Fixed premium estimate** — Assumes ~1% monthly CC premium regardless of market
3. **No assignment handling** — Assumes all positions always roll successfully
4. **Monthly CC writes only** — Doesn't model weekly or dynamic rewrite logic
5. **No transaction costs** — Zero commissions/fees

## Next Steps

1. **Review results** — See `docs/VIX_REGIME_BAKEOFF.md` for analysis
2. **Test longer windows** — Include 2008, 2015-2016 high-VIX periods
3. **Refine intensity mapping** — Current percentile thresholds may be too conservative
4. **Compare to realized vol** — VIX vs SPY realized vol ratio (not just percentile)

## Support

This is a **research/simulation tool**, not a live trading system. Results are:
- ✓ Reproducible via committed code + cached VIX data
- ✓ Honestly labeled as simulation
- ✗ Not representative of live execution
- ✗ Not a recommendation to trade
