# Growth-Income-Drip Paper Track

**Track ID:** `growth-income-drip-v1`  
**Status:** Active sibling to `wheel-10k-paper-v1`  
**Purpose:** Test 80/20 momentum+dividend strategy with quarterly rebalance on a **second** Alpaca paper account

---

## Strategy Overview

The growth-income-drip track implements a two-sleeve equity strategy:

### Growth Sleeve (80%)
- **Arm C style 12-1 momentum**: Total return over trailing 12 months, excluding most recent month
- **Top ~30 liquid names**: Equal-weighted within sleeve
- **Market cap filter**: ≥$5B
- **Liquidity filter**: Average daily volume ≥$10M USD
- **NO covered calls** in v1
- **NO vol-targeting**

### Ballast Sleeve (20%)
- **Dividend-paying stocks**: Minimum 2% yield
- **~15 high-quality names**: Equal-weighted within sleeve
- **Market cap filter**: ≥$10B (higher than growth for stability)
- **Liquidity filter**: Average daily volume ≥$20M USD

### Rebalance Rules
- **Quarterly rebalance**: Mid-month in March, June, September, December
- **Delta trading only**: No full liquidation; only trade position deltas
- **Dividend drip**: Accumulated dividend cash reinvests into growth sleeve at rebalance
- **Cost model**: ~7 bps assumed transaction costs

---

## Isolation from Wheel Track

This track is a **completely separate** paper portfolio from the wheel-10k track:

| Aspect | Wheel Track | Drip Track |
|--------|-------------|------------|
| **Track ID** | `wheel-10k-paper-v1` | `growth-income-drip-v1` |
| **Alpaca Secrets** | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL` | `ALPACA_DRIP_API_KEY`, `ALPACA_DRIP_SECRET_KEY`, `ALPACA_DRIP_BASE_URL` |
| **Performance Path** | `data/performance/official/` | `data/performance/growth_income_drip_v1/` |
| **Concurrency Group** | `aletheia-wheel-paper` | `aletheia-drip-paper` |
| **Workflows** | `daily-wheel-scan.yml`, `wheel-options-daily.yml`, etc. | `drip-daily-snapshot.yml`, `drip-quarterly-rebalance.yml`, etc. |
| **Strategy** | Wheel + CCs + CSPs + directional | Momentum + dividends, NO options |

**Wheel workflows and secrets are NEVER read by drip workflows.**

---

## Setup Instructions

### 1. Create Second Alpaca Paper Account

1. Log in to [Alpaca](https://alpaca.markets/)
2. Create a **new paper trading account** (separate from wheel account)
3. Fund it with virtual capital (e.g., $10,000 to match track start NAV)
4. Generate API keys for the new paper account:
   - API Key ID
   - Secret Key
   - Base URL: `https://paper-api.alpaca.markets`

### 2. Configure GitHub Secrets

Add the following secrets to your repository (Settings > Secrets and variables > Actions):

- `ALPACA_DRIP_API_KEY`: API key for the **drip paper account**
- `ALPACA_DRIP_SECRET_KEY`: Secret key for the **drip paper account**
- `ALPACA_DRIP_BASE_URL`: `https://paper-api.alpaca.markets` (or leave blank to use default)

**DO NOT overwrite or modify the existing `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` secrets!**  
Those belong to the wheel track and must remain unchanged.

SMTP secrets (`SMTP_SERVER`, `SENDER_EMAIL`, etc.) are shared across tracks.

### 3. Enable Workflows

The drip workflows are in `.github/workflows/`:
- `drip-daily-snapshot.yml`: Runs weekdays at 10 AM EST/EDT (after market open)
- `drip-quarterly-rebalance.yml`: Runs mid-month on quarter-end months (Mar/Jun/Sep/Dec)
- `drip-weekly-digest.yml`: Runs Fridays at 5 PM EDT (weekly summary email)

These workflows are automatically enabled when merged to `main`.  
To manually trigger: Go to Actions tab → select workflow → "Run workflow"

---

## Workflows

### Daily Snapshot
- **Trigger**: Weekdays at 10:00 AM EST/EDT
- **What it does**:
  - Connects to drip Alpaca account
  - Records NAV, cash, positions
  - Saves snapshot to `data/performance/growth_income_drip_v1/`
  - Sends daily email digest
  - **No rebalancing** (unless quarterly date)

### Quarterly Rebalance
- **Trigger**: Mid-month (15th) of March, June, September, December at 10:00 AM EST/EDT
- **What it does**:
  - Fetches liquid universe (~200 tickers)
  - Runs momentum selection (growth sleeve)
  - Runs dividend selection (ballast sleeve)
  - Calculates target 80/20 allocations
  - Executes **delta trades only** (buys/sells to reach targets)
  - Records rebalance date
  - Drips accumulated dividends into growth sleeve
  - Sends email notification

### Weekly Digest
- **Trigger**: Fridays at 5:00 PM EDT
- **What it does**:
  - Summarizes week's performance
  - Shows total return since track start
  - Reports growth/ballast split
  - Reports position count and dividend cash
  - Sends weekly email

---

## Run Profile

The `growth-income-drip-v1` profile in `config/run_profiles.json` contains strategy parameters:

```json
{
  "growth_weight": 0.80,
  "ballast_weight": 0.20,
  "rebalance_frequency": "quarterly",
  "momentum_lookback_months": 12,
  "momentum_skip_months": 1,
  "momentum_top_n": 30,
  "min_market_cap_b": 5.0,
  "min_adv_usd": 10000000,
  "enable_covered_calls": false,
  "enable_cash_secured_puts": false,
  "enable_vol_targeting": false,
  "dividend_drip_to_growth": true,
  "cost_bps": 7
}
```

---

## Performance Tracking

### Track Record Files
- **Snapshots**: `data/performance/growth_income_drip_v1/snapshot_YYYY-MM-DD.json`
- **Last Rebalance**: `data/performance/growth_income_drip_v1/last_rebalance.txt`

### Metrics Tracked
- Daily NAV (Alpaca account equity)
- Cash + stocks market value
- Growth sleeve NAV (80% target)
- Ballast sleeve NAV (20% target)
- Accumulated dividend cash
- Position count
- Total return since track start
- Sharpe ratio (annualized)

### Cache Keys
Performance data is cached in GitHub Actions with key prefix:
- `drip-perf-{repo}-v1-{run_id}`

This is **separate** from wheel cache (`perf-{repo}-wheel-v1-{run_id}`).

---

## Testing

Unit tests for the drip track are in `tests/test_growth_income_drip.py`:
- Momentum selector logic
- Dividend ballast selector logic
- Delta rebalance calculation
- Quarterly rebalance gating (date logic)
- Secret/env variable isolation (drip vs wheel)

Run tests:
```bash
poetry run pytest tests/test_growth_income_drip.py -v
```

---

## Code Modules

### Backtesting / Strategy
- `src/backtesting/growth_quality/momentum.py`: Arm C 12-1 momentum selector
- `src/backtesting/income_drip/ballast.py`: Dividend ballast selector
- `src/backtesting/income_drip/drip.py`: Dividend accumulation manager

### Performance
- `src/performance/drip_track.py`: Track record, snapshots, rebalance gating

### Scripts
- `scripts/growth_income_drip_rebalance.py`: Main rebalance runner (daily snapshot + quarterly rebalance)
- `scripts/send_drip_weekly_digest.py`: Weekly email digest generator

---

## Honest Framing

**Equity momentum drives the beat-SPY alpha.**  
Income is **ballast and drip** for stability, not the primary return driver.

The strategy hypothesis:
- Momentum captures upside in growth names
- Dividend ballast reduces drawdowns during corrections
- Quarterly rebalance avoids overtrading
- Drip reinvestment compounds without cash drag

v1 explicitly **does not** use covered calls on momentum names to preserve full upside capture.

---

## Differences from Wheel Track

| Feature | Wheel Track | Drip Track |
|---------|-------------|------------|
| **Options** | Covered calls + CSPs | None |
| **Rebalance** | Daily equity + options manage | Quarterly equity only |
| **Strategy** | Premium harvesting + directional | Pure equity momentum + dividends |
| **Sleeves** | 70% wheel + 30% directional | 80% growth + 20% ballast |
| **Position sizing** | 100-share lots (wheel), residual (directional) | Equal weight within sleeves |
| **Factor signal** | Agent confidence + wheel rules | 12-1 momentum + dividend yield |

---

## Future Enhancements (v2+)

Potential improvements for later iterations:
- **Live dividend tracking**: Integrate actual dividend payments from Alpaca
- **Factor diversification**: Add quality/value screens to momentum
- **Ballast evolution**: Test REITs, utilities, or sector rotation
- **Vol-targeting**: Add dynamic leverage/de-leverage based on realized vol
- **Covered calls on ballast**: Test CCs on dividend sleeve only (preserve growth upside)
- **Monthly rebalance option**: Compare quarterly vs monthly cadence

**v1 is deliberately simple to establish a clean baseline.**

---

## Troubleshooting

### Workflows Not Running
- Check that secrets `ALPACA_DRIP_API_KEY` and `ALPACA_DRIP_SECRET_KEY` are set
- Verify workflows are enabled in Actions tab
- Check holiday/market gate in `scripts/should_run_daily_scan.py`

### No Snapshots Generated
- Check workflow logs in Actions tab
- Verify Alpaca drip account is accessible
- Check performance cache restore/save steps

### Email Not Sending
- Verify shared SMTP secrets are set
- Check email notifier configuration in `src/utils/email.py`
- Review workflow logs for email errors

### Rebalance Not Executing
- Check `last_rebalance.txt` in performance directory
- Verify quarterly rebalance date logic in `src/performance/drip_track.py`
- Use `--force-rebalance` flag for manual override

---

## Support

For issues or questions:
- **Repository**: [github.com/Adi1yer/Aletheia-Capital](https://github.com/Adi1yer/Aletheia-Capital)
- **Maintainer**: [@Adi1yer](https://github.com/Adi1yer)
- **Workflow logs**: Actions tab in GitHub repository

**Remember: Wheel track and drip track are completely isolated.**  
Changes to one should never affect the other.
