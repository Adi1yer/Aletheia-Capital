#!/usr/bin/env bash
# Weekly trading scan wrapper script
# Usage: ./scripts/run_weekly_scan.sh [ARGS...]
#
# Pass any args to main.py. Examples:
#   ./scripts/run_weekly_scan.sh --tickers AAPL,MSFT,GOOGL
#   ./scripts/run_weekly_scan.sh --tickers AAPL,MSFT --execute
#   ./scripts/run_weekly_scan.sh --universe --max-stocks 100 --execute --email-to aditya.iyer@gmail.com
#
# Default (no args): --tickers AAPL,MSFT,GOOGL (dry run)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -f .env ]]; then
    echo "Error: .env not found. Copy from .env.example and add your API keys."
    exit 1
fi

mkdir -p logs
LOG_FILE="logs/weekly_scan_$(date +%Y%m%d_%H%M%S).log"

# Default to dry run with a few tickers if no args
if [[ $# -eq 0 ]]; then
    ARGS=(--tickers AAPL,MSFT,GOOGL)
else
    ARGS=("$@")
fi

echo "Starting weekly scan at $(date)"
echo "Log: $LOG_FILE"
poetry run python src/main.py "${ARGS[@]}" 2>&1 | tee "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

if [[ $EXIT_CODE -ne 0 ]]; then
    echo "Scan failed with exit code $EXIT_CODE"
    exit $EXIT_CODE
fi
echo "Scan completed at $(date)"
