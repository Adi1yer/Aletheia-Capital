# Workflow → paper account mapping

Alpaca allows **3 paper accounts per email**. This repo uses:

| # | Physical account | Env secrets | Sleeves |
|---|------------------|-------------|---------|
| 1 | Main equity | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | `weekly-scan` |
| 2 | Biotech | `BIOTECH_ALPACA_API_KEY`, `BIOTECH_ALPACA_SECRET_KEY` | `biotech-catalyst` |
| 3 | **Multi-sleeve satellite** | `MULTI_SLEEVE_ALPACA_API_KEY`, `MULTI_SLEEVE_ALPACA_API_SECRET_KEY` | hedge, options-income, congressional, macro-etf, crypto-weekly |

Five workflows share account **#3**. They still write **separate ledgers** under `data/hedge/`, `data/options_income/`, etc., so you can see what each strategy did. Alpaca dashboard PnL is **one combined book** for all five.

IBKR sleeves (forex, futures, commodities) remain separate paper account IDs when you add them.

## Workflow table

| Workflow | Script | Broker | Secrets | Snapshot dir |
|----------|--------|--------|---------|--------------|
| `weekly-scan.yml` | `weekly_scan_rebalancing.py` | Alpaca | `ALPACA_*` | `stock` |
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

## Setup (3 Alpaca accounts)

1. **Equity** — keys → `ALPACA_*`
2. **Biotech** — keys → `BIOTECH_ALPACA_*`
3. **Satellite** — keys → `MULTI_SLEEVE_ALPACA_*` in GitHub (or keep `HEDGE_ALPACA_*` if you already created the beta-hedge account; code accepts either)

Only **one** secret pair needed for all five satellite workflows in CI.

## Daily health

```bash
poetry run python daily_health_check.py --account all
```

Snapshots once per physical account (`stock`, `biotech`, `multi_sleeve`, …).

## Attribution without separate accounts

- Per-sleeve ledgers: `data/<sleeve>/trades_ledger.jsonl`
- Fund metrics: `data/fund/weekly_metrics.json` (logical workflow weights)
- Kill one sleeve: `config/fund_allocation.json` → `kill_switches.<workflow_id>`
