# Phase 14 — Implementation Plan: Beat SPY

This is the **engineering execution plan** for [`BEAT_SPY_PLAN.md`](BEAT_SPY_PLAN.md).  
Do not push until reviewed. Implement on branch `phase14-beat-spy`.

## Outcomes

| Artifact | Purpose |
|----------|---------|
| Profile `beat-spy-10k` | Parallel paper book vs Phase 13 `ci-full` |
| Weekly Beat-SPY scorecard | IR / Sharpe / DD / return vs SPY |
| Factor residual engine | Deterministic μ̂ before agents |
| Agent triage overlay | Agents only on top factor slice + holdings |
| Attribution report | Beta vs residual vs costs |
| Month-3 / Month-6 gates | Pass → owner $1k live; fail → redesign |

---

## PR / commit batches

### P14-A — Scorecard & attribution (Wave 0)
**Goal:** Know if we are beating SPY on the right metric.

| Work item | Files (create / change) | Acceptance |
|-----------|-------------------------|------------|
| Rolling IR, Sharpe, DD vs SPY | `src/performance/beat_spy_scorecard.py` | Writes `data/performance/beat_spy_scorecard_latest.json` + `.md` |
| Portfolio attribution (β, residual, sector) | `src/performance/attribution.py` | β_SPY, residual return, top sector contribution |
| Persist weekly series | `data/performance/beat_spy_history.jsonl` | One row per run_date |
| Wire into pipeline results | `src/trading/pipeline.py` | `results["beat_spy"]`, `results["attribution"]` |
| Email section | `src/utils/email.py` | “Beat SPY scorecard” block |
| Gate calendar stub | `src/performance/beat_spy_gates.py` | Reports `month3` / `month6` status from history |
| Tests | `tests/test_beat_spy_scorecard.py` | Synthetic equity paths → known IR |

**CI:** Optional workflow `beat-spy-scorecard.yml` on schedule (reads latest paper cache) — can wait until P14-C.

---

### P14-B — Factor residual engine (Wave 1a)
**Goal:** Expected residual return without LLMs.

| Work item | Files | Acceptance |
|-----------|-------|------------|
| Factor score aggregator | `src/alpha/factors.py` | Per ticker: mom, quality, value (reuse `src/agents/scoring/*` where possible) |
| Composite residual μ̂ | `src/alpha/residual_mu.py` | Cross-sectional z-score average → μ̂ |
| Factor cache | `data/cache/factor_scores.json` (+ helper) | Fresh ≤7d; speeds weekly |
| Rank + candidate cut | `src/alpha/candidate_set.py` | Top N=100 from universe≤400 |
| Unit tests | `tests/test_alpha_factors.py` | Ordering + missing-data resilience |

**Reuse:** `value_checklist`, `growth_trends`, `technicals_signals`, dossier metrics — wrap into numeric factors, do not rewrite agents.

---

### P14-C — Agent overlay + conflict rule (Wave 1b)
**Goal:** Agents accelerate judgment on the short list only.

| Work item | Files | Acceptance |
|-----------|-------|------------|
| Triage mode | `src/trading/pipeline.py` | `beat_spy_agent_triage: true` → full agents on holdings ∪ factor top-100; neutral/skip rest for extended |
| Veto / boost API | `src/alpha/agent_overlay.py` | Input: μ̂ + agent aggregate → output adjusted μ̂ or `veto=True` |
| Conflict rule | same | If factor rank percentile &lt; 50 → cannot enter top holdings even if agents bullish |
| Wire sizing | `src/portfolio/manager.py` or new `src/portfolio/beat_spy_allocator.py` | Size by μ̂/risk, max 12–15 names, max 10% |
| Tests | `tests/test_agent_overlay.py` | Veto kills; bottom-half cannot boost into book |

---

### P14-D — Profile `beat-spy-10k` + Phase 13 soften (Wave 1c / 2a)
**Goal:** Run a dedicated book sized for ~$10k.

| Work item | Files | Acceptance |
|-----------|-------|------------|
| Run profile | `config/run_profiles.json` → `beat-spy-10k` | `max_stocks: 400`, `max_buy_tickers: 12`, `cash_buffer_pct: 0.04`, `max_position_pct: 0.10`, `phase13_enabled: true` but `phase13_hard_risk_off: false` / cash overrides, `beat_spy_mode: true`, biweekly flag |
| CLI / workflow | `weekly_scan_rebalancing.py`, new `.github/workflows/beat-spy-scan.yml` | Scheduled **biweekly** Monday; paper `--execute` on main Alpaca **or** isolated paper keys if available |
| Dual-book note | docs | Phase 13 `weekly-scan.yml` stays as control; Beat-SPY is challenger |
| Soft risk-off | `src/portfolio/phase13_policy.py` / `regime.py` | When `beat_spy_mode`: cash floor 3–5%; harvest trims residual risk, does not force 20% cash / SH as primary defense |
| Book stops | keep | −8% / dead-money still on |

**Important:** Prefer **second Alpaca paper account** for Beat-SPY if keys exist; else shadow mode (decisions + scorecard without displace Phase 13 fills). Shadow documented in profile `broker_required: false` + `shadow_only: true` until second account.

---

### P14-E — $10k construction polish (Wave 2)
**Goal:** Friction-aware trading at tiny AUM.

| Work item | Files | Acceptance |
|-----------|-------|------------|
| Min notional / skip dust | allocator | No trade &lt; $250 |
| Cost penalty in μ̂ | `residual_mu.py` | Liquidity tier haircut |
| Optional SPY core sleeve | `src/portfolio/beta_sleeve.py` | Target 0–40% SPY for beta clarity (configurable); rest active |
| Shorts optional | manager + profile flag | `enable_short_selling` only if paper supports; else long-only |
| Freeze churn | CODEOWNER-style note in docs | No feature work outside gates after P14-E ships |

---

### P14-F — Learning objective fix (Wave 1–2)
**Goal:** Promote what helps beat SPY.

| Work item | Files | Acceptance |
|-----------|-------|------------|
| Residual IR contribution per agent/lane | `src/performance/promotion_gates.py` (+ helper) | Promote when holdout residual IR improves |
| Weight update blend | `pipeline._update_agent_weights` | Cap updates using residual utility, not hit-rate alone |
| Auto-throttle for Beat-SPY | `auto_throttle.py` | Use IR &lt; 0 for 8 weeks → defensive; don’t use raw active lag from cash-heavy Phase 13 book |

---

### P14-G — Ops & capital path (Wave 3)
**Goal:** Human process, not just code.

| Work item | Deliverable |
|-----------|-------------|
| Month 3 checklist | `docs/BEAT_SPY_GATES.md` — diagnosis tree if IR &lt; 0 |
| Month 6 go-live checklist | Same — pass → fund $1k; fail → redesign sprint |
| F&F one-pager template | IR, DD, attribution, process after live twin |
| Monthly broker export habit | Manual until admin; store under `data/live_statements/` |

---

## Week-by-week schedule

| Week | Batch | Focus |
|------|-------|-------|
| 1 | P14-A | Scorecard + attribution + email |
| 2 | P14-B | Factor engine + cache |
| 3 | P14-C | Agent overlay + allocator |
| 4 | P14-D | Profile + biweekly workflow + soften risk-off |
| 5–6 | P14-E + P14-F | Costs, beta sleeve, learning objective |
| 7 | Stabilize | Bugs only; both books running |
| 8–24 | P14-G | Observe; Month 3 / Month 6 gates |

---

## Dual-book operating model

```
Monday schedule:
  weekly-scan.yml          → Phase 13 control (existing)
  beat-spy-scan.yml        → every other Monday (or weekly decisions, biweekly execute)
  
Artifacts compared in email/digest:
  Phase13 active vs SPY
  BeatSPY IR / residual vs SPY
```

Until a second paper account exists: Beat-SPY runs **shadow** (full decide + scorecard + cache, no execute) so we don’t thrash the live Phase 13 paper book mid-experiment.

---

## Definition of Done (engineering)

- [ ] `poetry run pytest` green including new Beat-SPY tests  
- [ ] `beat-spy-10k` profile documented and runnable locally  
- [ ] Scorecard appears in results + email  
- [ ] Agents do not run full roster on all 400 (triage verified in logs)  
- [ ] Conflict rule unit-tested  
- [ ] Month-3/6 gate functions report status from history  
- [ ] `docs/BEAT_SPY_PLAN.md` + this file linked from README  

## Definition of Done (investment — not code)

- [ ] 6 months: IR / Sharpe / return / DD gates met  
- [ ] Then ~$1k live + paper twin 6 months  
- [ ] Then F&F materials  

---

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Beat-SPY executes on same account as Phase 13 | Shadow until 2nd paper account |
| Factors are just LLM checklists renamed | Use price/fundamental numerics; agents secondary |
| Week-1 overfit to recent regime | Freeze until Month 3; one patch only |
| $10k cannot short/options well | Long-only residual first; add later |
| Scope creep (more agents/sleeves) | Batch list above is the backlog; park rest |

---

## Ask before coding

Confirm two execution choices:

1. **Shadow Beat-SPY (no execute) until second Alpaca paper account?** Recommended: **yes**.  
2. **Beta sleeve:** start with **0% dedicated SPY ETF** (all capital in 10–15 actives with β≈1 target via construction) **or** **30% SPY + 70% active**? Recommended: **0% ETF first** (simpler at $10k), attribute β statistically.

Once you confirm (or say “take recommendations”), implement P14-A → P14-D first on branch `phase14-beat-spy`, leave unpushed for review.
