# Agent tiers (weekly production)

Production weekly scans use **tiered agents** by default (`--agent-tier-mode tiered`):

- **Core (8)** — run every Monday on the full universe
- **Extended (14)** — split across a 2-week rotation (~7 per week)

Config: [`config/agents_tiers.json`](../config/agents_tiers.json)

## Overrides

- `--agent-tier-mode full` — all 22 agents every run
- `--agent-tier-mode core` — core only (dev-smoke profile)
- `--agents warren_buffett,cathie_wood` — explicit list

Active agents are stored in scan cache `meta.json` as `active_agents`.

## Aggregation

Portfolio rebalance uses weights only for agents that ran this week. Inactive agents contribute no signals.

## Agent v2 hybrid

All tiered stock agents use the **hybrid** pipeline (deterministic lane score + bounded LLM explanation). Shared context comes from **ticker dossier v2** built once per ticker in the weekly pipeline.

See [AGENT_V2.md](AGENT_V2.md) for lanes, override rules, and how to add a persona.
