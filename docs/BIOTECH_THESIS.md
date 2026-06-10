# Biotech Catalyst Thesis Validation

## Thesis

Near-term clinical readout windows (ClinicalTrials.gov primary/completion dates) create tradable volatility. The paper strategy expresses this as a **defined-risk long straddle** (or strangle fallback): max loss = premiums paid; profit if the underlying move exceeds combined premium.

## Dual arms (A/B)

| Arm | When it trades | Purpose |
|-----|----------------|---------|
| `mechanical` | Discovery/readout pass + risk budget + contracts | Baseline sample; proves/disproves catalyst timing + vol payoff |
| `llm_gated` | Same, but only if `apply_gates()` passes (not `no_trade`, has trials/filings, price OK) | Tests whether LLM filtering adds value |

Each arm uses **50% of the per-run premium cap** (`BiotechRiskBudget.per_arm_budget`).

## Ledger

Append-only: `data/biotech/thesis_ledger.jsonl`

Key fields: `trade_id`, `arm`, `ticker`, `nct_id`, `readout_date_expected`, `premium_filled_usd`, `status`, `straddle_pnl_usd`, `pnl_pct_of_premium`, `clinical_outcome`, `underlying_px_*`.

Resolution runs at the start of each weekly scan and on daily biotech health checks.

## Pass / fail criteria

- **Thesis supported (mechanical):** avg `pnl_pct_of_premium` > 0 over ≥10 closed trades.
- **LLM adds value:** `llm_gated` win rate or avg PnL beats `mechanical` on the same calendar window.
- **Calibration:** post-readout 5d move should correlate with LLM probability buckets (reported in weekly scorecard).

## Operations

1. **Secrets:** `BIOTECH_ALPACA_API_KEY`, `BIOTECH_ALPACA_SECRET_KEY`, `DEEPSEEK_API_KEY`, SMTP vars.
2. **Weekly:** GitHub workflow `biotech-catalyst.yml` or `poetry run python biotech_catalyst_scan.py --discover-candidates`.
3. **Daily:** `daily-health-check.yml` with `--account both` (biotech snapshots + thesis resolve).
4. **Analysis only:** `--no-paper-execute`
5. **Disable an arm:** `--no-mechanical-arm` / `--no-llm-gated-arm`

## Learning loop (closed loop)

Resolved trades in `thesis_ledger.jsonl` feed a bounded policy learner—not only the weekly email.

| Artifact | Path |
|----------|------|
| Learned policy | `config/biotech_policy.json` |
| Weekly changelog | `data/biotech/learning_changelog.jsonl` |
| Promotion hold flag | `data/biotech/calibration_hold.json` |
| Learning blocklist | `config/biotech_learning_blocklist.txt` |
| Counterfactual misses | `data/biotech/counterfactual_ledger.jsonl` |

**Weekly scan order:** resolve open thesis → exit policy (daily) → resolve counterfactuals → `compute_biotech_policy` → holdout `evaluate_biotech_proposal` → save policy if promoted → changelog → discovery (policy knobs + history rank) → analyze (past-trade LLM context) → `apply_gates` (learned prob mid/range) → dual-arm execute → counterfactual on `no_trade`/gate fail → email (scorecard + learning + missed catalysts).

**Learnable knobs** (smooth ~20% steps, holdout-gated): `min_llm_prob_mid`, `min_prob_range_width`, `max_premium_pct_equity`, `discovery_min_phase`, `readout_max_forward_days`, `min_days_to_readout`, `max_premium_to_expected_move_ratio`, `mechanical_arm_enabled`, `llm_gated_arm_enabled`.

**Promotion:** last 2 `run_date` buckets = holdout; promote only if holdout `llm_gated` avg `pnl_pct_of_premium` is not worse than train by more than 2 pts.

**Monthly eval (CI):** workflow `biotech-calibration-eval.yml` or `poetry run python scripts/biotech_policy_eval.py`.

## CLI

```bash
poetry run python biotech_catalyst_scan.py --discover-candidates
poetry run python daily_health_check.py --account biotech
poetry run python scripts/biotech_policy_eval.py
```
