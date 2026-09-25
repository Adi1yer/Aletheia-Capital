# Documentation Index

**New to the project?** Start with **[GETTING_STARTED.md](GETTING_STARTED.md)** for environment setup and first run.

**Cloning for development?** Configure git identity for [@Adi1yer](https://github.com/Adi1yer) — see [SETUP.md](../SETUP.md#git-commit-identity).

| Document | Purpose |
|----------|---------|
| [WHITEPAPER_WHEEL_HYBRID.md](WHITEPAPER_WHEEL_HYBRID.md) | **Wheel-hybrid strategy thesis**: mandate, mechanics, risk framework, backtest design, falsifiers, roadmap |
| [EDGE_VRP_ROADMAP.md](EDGE_VRP_ROADMAP.md) | **VRP Edge roadmap**: Phase 2 IV drop-in, market IV requirements, bake-off methodology, kill criteria |
| [OFFICIAL_TRACK_RECORD.md](OFFICIAL_TRACK_RECORD.md) | Frozen wheel-10k paper track: start NAV, official vs cash+stocks, no silent resets |
| [WHEEL_BACKTEST_DESIGN.md](WHEEL_BACKTEST_DESIGN.md) | Wheel backtest design: synthetic option pricing, fixed universe, validation vs approximations |
| [GETTING_STARTED.md](GETTING_STARTED.md) | One-place setup: Python, Poetry, .env, Ollama/API, run commands |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, components, data flow |
| [API.md](API.md) | API reference and usage |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment (local, cloud, Docker, Redis) |
| [ENHANCEMENTS.md](ENHANCEMENTS.md) | Recent improvements and features |
| [DATA_SOURCES.md](DATA_SOURCES.md) | Data providers, insider trading gap, and workarounds |
| [AGENT_DATA_GAPS.md](AGENT_DATA_GAPS.md) | Per-agent data gaps and steps to give each agent the inputs they need |
| [FULL_UNIVERSE_DATA_COST.md](FULL_UNIVERSE_DATA_COST.md) | Do you need to pay for API keys for full-universe scans? Free vs paid options. |
| [SCAN_CACHE.md](SCAN_CACHE.md) | Persist full scan results locally; list/load runs; TTM and historical analysis. |
| [API_KEYS.md](API_KEYS.md) | API keys for agent data (e.g. Finnhub for insider + analyst). |

Root-level docs (project root):

- **BROKERAGE_ANALYSIS.md** – Broker choice, trade volume, rate limits
- **CLOUD_SCALING_ANALYSIS.md** – Local vs cloud LLM, full-market scaling
- **EMAIL_SETUP.md** – Email notifications
- **QUICK_START_OLLAMA.md** – Ollama-only quick start
- **UNIVERSE_TRADING.md** – Stock universe and liquidity filters
- **BACKTESTING_AND_WEIGHTS.md** – Backtesting and dynamic agent weights
