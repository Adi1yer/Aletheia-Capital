#!/usr/bin/env bash
# Beat SPY weekly scan — local or cron wrapper
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/weekly_run_$(date +%Y%m%d_%H%M%S).log"
exec poetry run python weekly_scan_rebalancing.py \
  --run-profile beat-spy-10k \
  --agent-tier-mode tiered \
  --max-stocks 400 \
  --stop-loss-pct 0.08 \
  --execute \
  --enable-covered-calls \
  --enable-cash-rotation --cash-rotation-min-edge 12 \
  --max-cash-rotation-sells 1 \
  --max-position-pct 0.10 --max-sector-pct 0.30 \
  --min-buy-confidence 62 --min-sell-confidence 55 \
  --cash-buffer-pct 0.04 --max-buy-tickers 12 \
  --regime-mode auto \
  2>&1 | tee "$LOG"
