# Workflow → paper account mapping

**GitHub repository:** [Adi1yer/Aletheia-Capital](https://github.com/Adi1yer/Aletheia-Capital) — commits should use the **Adi1yer** noreply email (`201507252+Adi1yer@users.noreply.github.com`). See [SETUP.md](../SETUP.md#git-commit-identity).

Alpaca allows **3 paper accounts per email**. This repo originally used:

| # | Physical account | Env secrets | Sleeves |
|---|------------------|-------------|---------|
| 1 | Main equity / wheel | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | `weekly-scan` (daily-wheel-scan) |
| 2 | Biotech | `BIOTECH_ALPACA_API_KEY`, `BIOTECH_ALPACA_SECRET_KEY` | `biotech-catalyst` |
| 3 | **Multi-sleeve satellite** | `MULTI_SLEEVE_ALPACA_API_KEY`, `MULTI_SLEEVE_ALPACA_API_SECRET_KEY` | hedge, options-income, congressional, macro-etf, crypto-weekly |

**NEW:** Growth-income-drip track requires a **4th physical account** (separate Alpaca login/email or free a paper slot):

| # | Physical account | Env secrets | Sleeves |
|---|------------------|-------------|---------|
| 4 | **Growth-income-drip** | `DRIP_ALPACA_API_KEY`, `DRIP_ALPACA_SECRET_KEY` | `growth-income-drip` (drip-daily-snapshot, drip-quarterly-rebalance) |

**Important:** Since Alpaca limits 3 paper accounts per email, you must either:
- Create a **second Alpaca login** (new email) for the drip account, OR
- Disable and free up one of the existing satellite accounts (#2 or #3)

Five workflows share account **#3**. They still write **separate ledgers** under `data/hedge/`, `data/options_income/`, etc., so you can see what each strategy did. Alpaca dashboard PnL is **one combined book** for all five.

IBKR sleeves (forex, futures, commodities) remain separate paper account IDs when you add them.

## Workflow table

| Workflow | Script | Broker | Secrets | Snapshot dir |
|----------|--------|--------|---------|--------------|
| `daily-wheel-scan.yml` | `weekly_scan_rebalancing.py` | Alpaca | `ALPACA_*` | `stock` |
| `drip-daily-snapshot.yml` | `growth_income_drip_rebalance.py` | Alpaca | `DRIP_ALPACA_*` | `drip` |
| `biotech-catalyst.yml` | `biotech_catalyst_scan.py` | Alpaca | `BIOTECH_ALPACA_*` | `biotech` |
| `hedge-weekly.yml` | `hedge_scan.py` | Alpaca | `MULTI_SLEEVE_ALPACA_*` | `multi_sleeve` |
| `options-income.yml` | `options_income_scan.py` | Alpaca | (same) | `multi_sleeve` |
| `congressional.yml` | `congressional_scan.py` | Alpaca | (same) | `multi_sleeve` |
| `macro-etf.yml` | `macro_etf_scan.py` | Alpaca | (same) | `multi_sleeve` |
| `crypto-weekly.yml` | `crypto_weekly_scan.py` | Alpaca | (same) | `multi_sleeve` |
| `forex-weekly.yml` | `forex_scan.py` | IBKR | `FOREX_IBKR_ACCOUNT_ID` + gateway | `forex` |
| `futures-trend.yml` | `futures_scan.py` | IBKR | `FUTURES_IBKR_ACCOUNT_ID` | `futures` |
| `commodities.yml` | `commodities_scan.py` | IBKR | `COMMODITIES_IBKR_ACCOUNT_ID` | `commodities` |

Registry: [`config/workflow_accounts.yaml`](../config/workflow_accounts.yaml)

## Setup (Alpaca accounts)

**Original 3 accounts (same email):**
1. **Equity / Wheel** — keys → `ALPACA_*`
2. **Biotech** — keys → `BIOTECH_ALPACA_*`
3. **Satellite** — keys → `MULTI_SLEEVE_ALPACA_*` in GitHub (or keep `HEDGE_ALPACA_*` if you already created the beta-hedge account; code accepts either)

**Growth-income-drip (requires 4th account — separate email or free a slot):**
4. **Drip** — keys → `DRIP_ALPACA_*`

Create a **second Alpaca login** (new email address) to get 3 more paper account slots, then allocate one to drip.

Only **one** secret pair needed for all five satellite workflows in CI.

GitHub secret name for the satellite secret is `MULTI_SLEEVE_ALPACA_API_SECRET_KEY` (not `..._SECRET_KEY` alone). Legacy `HEDGE_ALPACA_*` is still accepted.

## Satellite weekly digest

`fund-weekly-digest.yml` runs **Monday 18:00 UTC** and emails a consolidated summary (`fund_weekly_digest.py`) after the satellite scans. Each sleeve workflow also runs preflight and shares a GitHub Actions cache for `data/hedge`, `data/options_income`, etc.

## Daily health

```bash
poetry run python daily_health_check.py --account all
```

Snapshots once per physical account (`stock`, `biotech`, `multi_sleeve`, …).

## Attribution without separate accounts

- Per-sleeve ledgers: `data/<sleeve>/trades_ledger.jsonl`
- Fund metrics: `data/fund/weekly_metrics.json` (logical workflow weights)
- Kill one sleeve: `config/fund_allocation.json` → `kill_switches.<workflow_id>`
