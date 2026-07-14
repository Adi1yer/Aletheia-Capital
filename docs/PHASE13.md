# Phase 13 — Profitability Hardening

Paper-trading controls to stop structural underperformance vs SPY. **Stay paper** until the engine shows sustained profitable (not necessarily SPY-beating) performance.

## Policy defaults

| Control | Value |
|---------|-------|
| Operating cash buffer | 12% |
| Risk-off (harvest) cash | 20% |
| Absolute cash floor | 5% |
| Special opportunity | conf ≥ 85 + top-tier net-edge; max 1–2 names; spend into floor band only |
| Max new equity buys / week | 8 |
| Max position / sector | 7% / 25% |
| Buy / sell confidence | ≥65 / ≤55 |
| Universe | Top **1000** US names by market cap (liquidity filtered) |
| Auto-throttle | 8 consecutive weeks of negative active vs SPY → defensive mode |
| Cash/concentration SLO | warn 14 days, then hard |

## Biotech

- Mechanical arm **off** until ≥6 closed trades (and while auto-throttle is on)
- LLM-gated arm only during freeze
- Ghost catalysts (past primary completion, no results posted) excluded
- Max 5 open straddles; no dual live fill of the same structure
- Open ghost lots pruned at scan start (legs closed when possible)

## Timeout mitigations (1000 names)

1. Market-cap cache under `data/cache/` (CI restore/save)
2. Progressive MC fetch (not full tape every week)
3. Universe triage: **core** agents on full 1000; **extended** on top ~500 + holdings
4. Workflow timeout 600 minutes; LLM cache + budget

## Sleeve targets

See [`config/sleeve_budgets.json`](../config/sleeve_budgets.json). Digests print target budgets; `workflow_risk_budget_pct` reads them.

## Artifacts

- `data/performance/benchmark_latest.json` — book Δ, SPY Δ, do-nothing Δ, active α
- `data/performance/auto_throttle_state.json`
- `data/performance/phase13_slo_warmup.json`
- Weekly email sections: **Benchmark (active return)** and **Phase 13 controls**

## Related modules

- `src/portfolio/phase13_policy.py`
- `src/portfolio/net_edge.py`
- `src/performance/benchmark_report.py`, `prior_run.py`, `auto_throttle.py`
- `src/biotech/ghost_prune.py`, ghost filter in `readout_window.py`
- `src/data/market_cap_cache.py`
