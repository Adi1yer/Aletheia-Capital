# Beat SPY Plan (risk-adjusted)

**Mandate:** Beat SPY with better risk-adjusted returns.  
**Design AUM:** ~$10,000.  
**Path:** Paper 6–12 months → owner live ~$1,000 (+ paper twin) 6 months → friends & family.  
**Agent thesis:** Use agents to scan/rank/veto faster than manual or pure rules; improve with data + cache. Agents are an **overlay on a measurable alpha engine**, not 22 equal votes.

## Locked decisions (from your answers + best judgment)

| Topic | Decision |
|-------|----------|
| Scorecard | Primary: Information Ratio of active return vs SPY. Secondary: fund Sharpe ≥ SPY Sharpe. Cumulative return ≥ SPY − 1pp over the gate window. Max DD ≤ SPY DD + 3pp. |
| Live gate (your $1k) | Meet scorecard over **6 months** paper; else **redesign** (not knob cosmetics). |
| Net beta | Target **0.9–1.05** (beat SPY as stock picker, not by under-betaing). Soften Phase 13 12–20% cash for this profile. |
| Universe | **Top ~400** liquid US names (mcap × liquidity). Better than 1000 at $10k. |
| Cadence | **Biweekly** rebalance + threshold; weekly risk-only. |
| Holdings | **10–15** names; max position **8–10%**. |
| Shorts / options / events | Allowed; shorts only if cleanly executable on paper; options selective; biotech ≤5% until proven. |
| LLM budget | Uncapped; spend on **top factor slice + holdings**, not all tickers equally. |
| Conflict rule | Factors propose; agents **veto** or mild **boost**. Agents cannot promote bottom-half factor names into top holdings. |

## Architecture

```
Universe (~400 liquid)
    → Cheap factor scores (mom / quality / value / revisions)
    → Top 80–120 candidates
    → Agents: screen + veto + conviction boost (cached)
    → Residual μ̂ + risk → size 10–15 over/underweights
    → Optional SPY/QQQ beta sleeve for exposure clarity
    → Attribution + IR scorecard every week
```

### Why this matches “agents get smarter over time”
- Factor layer is stable and cheap to cache.
- Agent calls concentrate where cache hits compound (same names revisited).
- Promotions use **residual IR contribution**, so as agents improve they actually get more capital weight.

## Waves

### Wave 0 — Measurement (1–2 weeks)
- Weekly attribution: beta vs SPY, residual, sector, costs.
- Official scorecard artifact + email section.
- Dual paper: **current Phase 13** vs **Beat-SPY** (`beat-spy-10k` profile).
- Month 3 / Month 6 calendar gates.

### Wave 1 — Alpha engine + agent overlay (2–4 weeks)
- Deterministic factor engine + residual μ̂.
- Wire agents to top slice only (your speed thesis).
- Replace hit-rate-heavy promotion with residual IR contribution.
- New profile: cash ~4%, fewer names, biweekly, book stops retained, hard risk-off softened.

### Wave 2 — $10k construction (weeks 4–8)
- Position/turnover/cost floors for tiny AUM.
- Optional beta ETF sleeve.
- Short sleeve if Alpaca paper supports; else long-only residual tilts.
- Freeze feature churn; only gated learning.

### Wave 3 — Prove (months 2–6+)
- Month 3 interim diagnosis if IR &lt; 0.
- Month 6: pass → $1k live + paper twin; fail → redesign sprint.
- After live confirms → F&F packet (IR, DD, attribution, process).

## Explicit non-goals
- Adding more analyst personas for their own sake.
- Optimizing for more weekly trades or bigger digests.
- Claiming raise-readiness before scorecard gates.

## Success = capital path
1. Paper Beat-SPY clears 6-month scorecard.  
2. $1k live matches paper within costs for 6 months.  
3. Then friends & family with evidence, not architecture slides.

When approved to implement: follow **[PHASE14_IMPLEMENTATION.md](PHASE14_IMPLEMENTATION.md)** (PR batches P14-A…G, dual-book ops, gates). Strategy intent stays in this file.
