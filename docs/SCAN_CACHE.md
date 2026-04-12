# Scan Cache: Persist Full Market Scan Results

Every run of the weekly trading pipeline is written to local storage so you can:

- Replay or inspect past runs
- Run TTM (trailing twelve months) or historical analysis on cached data without re-scanning
- Compare signals and decisions across runs

## What Gets Cached

Each run is stored under `data/scan_cache/<run_id>/` with:

| File | Contents |
|------|----------|
| `meta.json` | run_id, run_date, config (execute, universe, max_stocks), tickers, start_date, end_date, duration_seconds |
| `signals.json` | All agent signals (agent → ticker → { signal, confidence, reasoning }) |
| `decisions.json` | Portfolio decisions (ticker → { action, quantity, confidence, reasoning }) |
| `risk.json` | Risk analysis (ticker → position limits, volatility, etc.) |
| `data_snapshot.json` | Per-ticker data used: last_price, metrics, line_items, news_count, news_titles |
| `portfolio_before.json` | Portfolio state at start of run |
| `portfolio_after.json` | Portfolio state after run (after execution if execute=True) |
| `execution_results.json` | Broker execution results (if execute=True) |

`run_id` format: `YYYY-MM-DD_<short-uuid>` (e.g. `2025-01-30_a1b2c3d4`).

## Enabling the Cache

The cache is **on by default** when you run the main pipeline:

```bash
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL
# or
poetry run python src/main.py --universe --max-stocks 500
```

No flags needed; each run is appended under `data/scan_cache/`.

## Listing and Inspecting Runs

```bash
# List cached runs (newest first)
poetry run python -m src.scan_cache.cli list --limit 20

# Only runs on or after a date
poetry run python -m src.scan_cache.cli list --since 2025-01-01

# Show one run (summary)
poetry run python -m src.scan_cache.cli show <run_id>

# Show full JSON for one run
poetry run python -m src.scan_cache.cli show <run_id> --raw
```

## Loading a Run in Code

```python
from src.scan_cache import ScanCache

cache = ScanCache()  # default: data/scan_cache
data = cache.load_run("2025-01-30_a1b2c3d4")
# data["meta"], data["signals"], data["decisions"], data["risk"], data["data_snapshot"], ...
runs = cache.list_runs(limit=10, since_date="2025-01-01")
```

## TTM / Historical Analysis

Use the cached runs to analyze without re-running the pipeline:

- **Signal consistency:** For a ticker, how often did each agent say bullish/bearish over the last N runs?
- **Decision backtest:** For decisions from 4 weeks ago, what would the return have been using current prices?
- **Data over time:** Compare `data_snapshot` across runs (e.g. how metrics changed).

Storage is local only (`data/scan_cache/` is under `data/` and ignored by git). Clear old runs by deleting subdirectories under `data/scan_cache/` if you need to free space.

---

## Storage per scan (estimate)

Rough size of one cached run:

| File | ~100 tickers | ~3,500 tickers (full universe) |
|------|----------------|--------------------------------|
| meta.json | ~5 KB | ~25 KB |
| signals.json | ~0.5 MB | ~18–25 MB |
| decisions.json | ~30 KB | ~1 MB |
| risk.json | ~30 KB | ~1 MB |
| data_snapshot.json | ~120 KB | ~4–6 MB |
| portfolio_* / execution_results | ~20 KB | ~0.2 MB |
| **Total per run** | **~0.7–1 MB** | **~45–55 MB** |

Most of the size is **signals.json** (21 agents × N tickers × signal + confidence + reasoning text). Reasoning strings dominate.

**Rule of thumb:** ~1 MB per 100 tickers per run, ~50 MB per full-universe run. For 52 weekly runs on the full universe: ~2.5 GB/year. For 100-ticker scans: ~50 MB/year.
