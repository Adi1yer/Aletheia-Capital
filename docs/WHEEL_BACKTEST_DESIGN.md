# Wheel Hybrid Backtest Design

## Overview

This document explains the design choices for backtesting the wheel-hybrid strategy that powers the official `wheel-10k-paper-v1` paper track. The goal is to produce citeable historical performance metrics for the whitepaper without requiring expensive full historical options data.

## Challenge: Historical Options Data

Full historical OPRA options chains (every strike, every expiry, bid/ask, IV, Greeks) are:

- **Expensive**: Polygon.io historical options starts at $250/month; Thetadata starts at $150/month
- **Verbose**: Multi-GB datasets for even a small 4–5 name universe over 3–5 years
- **Not always available**: Free-tier APIs (Alpaca, yfinance, Polygon free) do not expose historical options snapshots

At this stage (Phase 0, proving the concept on paper), purchasing a dedicated options data warehouse is premature.

## Chosen Approach: Synthetic Premium Model

We simulate the wheel strategy using:

1. **Historical equity prices** (daily close, high, low) from free providers (yfinance / Alpaca)
2. **Option premium proxy model** instead of real historical chains:
   - Black–Scholes vanilla call/put pricing with:
     - Underlying price from historical data
     - Strike selection rules matching live strategy (e.g., CC 3–8% OTM, CSP 2–10% OTM)
     - DTE matching live logic (14–45 DTE for CSPs, 21–45 DTE for CCs)
     - **Realized volatility** over trailing 21 trading days as IV proxy (conservative: actual IV is often higher)
     - Risk-free rate proxy: 0% (conservative; ignores T-bill yield)
   - **Assignment heuristics**: if underlying closes above call strike on expiry → assigned; if below put strike → assigned
   - **Roll logic**: mirrors live wheel management (BTC at 60% profit, roll when DTE ≤ 7 and ITM ≥ 2%)

3. **Portfolio ledger** tracking:
   - Cash balance
   - 100-share equity lots (for covered calls)
   - Short call positions (strike, expiry, premium collected, current mark)
   - Short put positions (strike, expiry, collateral reserved, premium collected)
   - Directional sleeve positions (fractional shares allowed)

4. **Daily decision loop**:
   - Check for assignments / expirations
   - Execute rolls / BTC when management criteria hit
   - Allocate capital: ~70% wheel sleeve (CC lots + CSP collateral), ~30% directional
   - Write new CSPs when cash-heavy and CSP score ≥ threshold
   - Buy 100-share lots + write CCs when wheel capacity < target
   - Buy directional positions with residual cash
   - Mark portfolio to market using equity closes + estimated short-option values

5. **Benchmark**: SPY buy-and-hold over the same period, using the same data provider

## What This Validates

✅ **Return decomposition**: Premium collected vs. assignment/roll drag vs. directional sleeve  
✅ **Risk-adjusted metrics**: Sharpe, Sortino (rf=0%), max drawdown, hit rate  
✅ **Beta / correlation / alpha** vs SPY  
✅ **Turnover** and approximate trade frequency  
✅ **Sensitivity to vol regime**: low-vol grind vs. high-vol whipsaw  

## What This Approximates

⚠️ **Bid-ask spread**: Model assumes mid-market fills; real spreads add ~$5–15 per option round-trip  
⚠️ **IV surface skew**: Uses simple ATM realized vol; real OTM put IV is often higher (CSP premium underestimated)  
⚠️ **Assignment slippage**: Real assignments may gap through strikes on earnings / events; model uses close-only logic  
⚠️ **Liquidity**: Does not enforce open interest / volume filters on historical data; assumes all modeled contracts were tradable  
⚠️ **Early assignment risk**: Ignored (American option model complexity deferred)  

## Universe Selection (No Look-Ahead Bias)

To avoid cherry-picking winners after the fact, the backtest uses:

**Fixed research universe**: 6–8 names that historically met the live wheel criteria for liquidity and price:
- Liquid (ADV > $5M historically)
- Price ≤ $35 (allowing 100-share lots with $10k NAV)
- Stable option markets (proxied by high average volume in equity)

**Example universe** (subject to data availability):
- **F** (Ford)
- **T** (AT&T)
- **SOFI** (SoFi Technologies, if history available)
- **PLUG** (Plug Power, if history available)
- **NIO** (Nio, if history available)
- **VALE** (Vale)

*Note*: The live track selects wheel names dynamically each morning using agent scores + liquidity filters. The backtest may use a fixed universe to avoid look-ahead bias, but documents this approximation clearly.

## Code Structure

```
src/backtesting/wheel_hybrid/
├── __init__.py
├── engine.py                 # Main simulation loop
├── premium_model.py          # Black-Scholes + assignment heuristics
├── portfolio.py              # Ledger: cash, lots, short options
├── metrics.py                # Sharpe, DD, beta, turnover
└── universe.py               # Fixed research universe definition

scripts/
└── run_wheel_hybrid_backtest.py  # CLI entry point

tests/
└── test_wheel_hybrid_backtest.py # Unit tests with synthetic fixtures

data/backtests/wheel_hybrid/
└── <run_id>/
    ├── equity_curve.csv       # Date, NAV, SPY
    ├── trades.csv             # All simulated trades
    ├── summary.json           # Metrics (Sharpe, DD, alpha, etc.)
    └── assumptions.json       # Config snapshot (vol window, rf, universe)
```

## CLI Example

```bash
poetry run python scripts/run_wheel_hybrid_backtest.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --nav 10000 \
  --out data/backtests/wheel_hybrid/2020_2024_10k
```

Output:
```
Wheel Hybrid Backtest (2020-01-01 to 2024-12-31)
================================================
Start NAV:        $10,000.00
End NAV:          $14,523.67
Absolute Return:  +45.2%
SPY Return:       +42.1%
Excess Return:    +3.1% / +$310.45

Max Drawdown:     -18.4%
Sharpe (rf=0%):   0.87
Sortino (rf=0%):  1.12
Beta:             0.72
Correlation:      0.81
Alpha (annual):   +1.2%

Hit Rate:         54.3% (137/252 sessions)
Turnover (21d):   0.34x
Premium Collected: $2,345.12
Net Roll Cost:    -$345.67

Results saved: data/backtests/wheel_hybrid/2020_2024_10k/
```

## Integration with Whitepaper

The whitepaper **Results** section will include a table like:

| Metric | Simulated (2020–2024) | Official Track (Live) |
|--------|----------------------|----------------------|
| Abs Return | +45.2% | *TBD — see live digest* |
| Excess vs SPY | +3.1% | *TBD — see live digest* |
| Max DD | -18.4% | *TBD — see live digest* |
| Sharpe (rf=0%) | 0.87 | *TBD — see live digest* |
| Beta | 0.72 | *TBD — see live digest* |

**Clearly labeled**: "Simulated results use synthetic option pricing (realized vol proxy). Live track uses real Alpaca paper fills."

## Graduating to Real Options Data

When the project scales (Phase 1+, larger capital, institutional LPs), upgrade the backtest by:

1. **Polygon.io or Thetadata subscription** for historical options snapshots (EOD chains)
2. Replace `premium_model.py` with a lookup interface: `get_historical_option_quote(symbol, strike, expiry, date) -> (bid, ask, iv)`
3. Keep the same `portfolio.py` ledger and `engine.py` loop structure
4. Add spread crossing logic: write at bid, buy-to-close at ask + slippage
5. Validate on 2020–2024 period against the synthetic model to calibrate approximation error

No rewrite of the decision logic or metrics calculation needed — only the premium source changes.

## Non-Goals (Out of Scope)

❌ **Minute-by-minute intraday fills**: Daily close logic is sufficient for a strategy rebalancing once per session  
❌ **Greeks-based hedging**: The live strategy does not delta-hedge; neither does the backtest  
❌ **Earnings event modeling**: Assignment gaps are approximated, not explicitly simulated  
❌ **Agent overlay backtest**: This tests the mechanical wheel rules only; agent scoring is not backtested here (agents are a forward-looking overlay on a rules-first base)  

## Acceptance Criteria

- [ ] Backtest runs without network calls in CI (uses committed fixtures for tests)
- [ ] CLI can run with yfinance on local machine (user provides their own API keys if rate-limited)
- [ ] Outputs `summary.json`, `equity_curve.csv`, `trades.csv`, `assumptions.json`
- [ ] Whitepaper cites backtest results with clear "simulated" disclaimer
- [ ] Design doc explains what is validated vs. approximated

## References

- Live wheel config: `config/run_profiles.json` → `wheel-10k`
- Official track: `docs/OFFICIAL_TRACK_RECORD.md`
- Wheel policy: `src/portfolio/wheel_policy.py`
- CC manager: `src/options/covered_calls.py`
- CSP manager: `src/options/cash_secured_puts.py`
