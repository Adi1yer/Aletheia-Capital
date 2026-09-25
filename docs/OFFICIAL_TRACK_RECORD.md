# Official track record — wheel-10k-paper-v1

This is the frozen paper track for Aletheia Capital’s $10k Alpaca wheel-hybrid book.

| Field | Value |
|---|---|
| **Name** | `wheel-10k-paper-v1` |
| **Start date** | 2026-09-21 |
| **Start NAV** | $10,000 USD |
| **Broker** | Alpaca paper |
| **Benchmark** | SPY total-return *price* series from the same `data_provider.get_prices("SPY", …)` close used in the daily scan (last available close on the snapshot day) |
| **Profile** | `wheel-10k` |

Do **not** reset the paper account, change start NAV, or rewrite history without an explicit archived experiment (new `track_id` + new `start_date` + new email label).

## Official scoreboard NAV

Two numbers appear on every digest:

1. **Alpaca equity / NAV (official)** — broker `account.equity`. This is the scoreboard for vs-SPY, drawdown, Sharpe/Sortino, excess return, and the subject line.
2. **Cash + stocks (supplemental)** — raw cash + long stock marks. Collected premium sits in cash; open short options are **not** subtracted. Use this to see the book if shorts expire OTM. Do **not** add the premium ledger on top of this number.

`Alpaca equity ≈ cash + stocks + open option marks` (timing and spendable-vs-raw cash can leave a small residual).

## Reset policy

- **Never reset** this track.
- A new experiment gets a new `track_id`, new `start_date`, new start NAV, and a different email prefix.
- Config fingerprint (hash of profile knobs + start invariants) is written on every email footer. If the fingerprint changes, that is a parameter change — not a silent NAV reset.

## Daily snapshots

Each successful morning run writes:

`data/performance/official/YYYY-MM-DD.json`

Emails read TRACK RECORD metrics from this series (not ad-hoc recomputes from a single run). The Actions `perf-…-wheel-v1-` cache must keep this directory.

## Risk-free rate

Sharpe and Sortino use **0% risk-free** (no 3m T-bill subtract), annualized with 252 sessions. Documented in the TRACK RECORD line as `rf=0%`.

## Missed runs

If an NYSE open weekday has no successful morning email after the watchdog window, a distinct mail is sent:

`Aletheia daily wheel — MISSED RUN — YYYY-MM-DD`

Paper state is left untouched.
