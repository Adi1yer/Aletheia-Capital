"""
CLI to list, inspect, and prune cached scan runs (for TTM / historical analysis).
Usage:
  poetry run python -m src.scan_cache.cli list [--limit N] [--since YYYY-MM-DD]
  poetry run python -m src.scan_cache.cli show <run_id>
  poetry run python -m src.scan_cache.cli prune [--keep-weeks N]
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.scan_cache import ScanCache


def cmd_list(scan_cache: ScanCache, limit: int, since: str) -> None:
    runs = scan_cache.list_runs(limit=limit, since_date=since or None)
    if not runs:
        print("No cached runs found.")
        return
    print(f"Found {len(runs)} run(s) (newest first):\n")
    for r in runs:
        print(f"  {r['run_id']}")
        print(
            f"    run_date: {r['run_date']}  tickers: {r['ticker_count']}  saved_at: {r.get('saved_at', 'N/A')}"
        )
        print()


def cmd_show(scan_cache: ScanCache, run_id: str, raw: bool) -> None:
    try:
        data = scan_cache.load_run(run_id)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    if raw:
        print(json.dumps(data, indent=2))
        return
    meta = data.get("meta", {})
    print("Run:", meta.get("run_id"))
    print("Date:", meta.get("run_date"))
    print("Config:", json.dumps(meta.get("config", {}), indent=2))
    print("Tickers:", meta.get("ticker_count"), "total")
    print("Duration (s):", meta.get("duration_seconds"))
    if "decisions" in data:
        decisions = data["decisions"]
        non_hold = [
            t
            for t, d in decisions.items()
            if d.get("action") != "hold" and d.get("quantity", 0) > 0
        ]
        print("Decisions: non-hold count =", len(non_hold))
    if "signals" in data:
        print("Agents in signals:", list(data["signals"].keys()))
    print("\nUse --raw to dump full JSON.")


def cmd_signals(scan_cache: ScanCache, run_id: str | None) -> None:
    """Print per-agent signal distribution (bullish/bearish/neutral/other) for one run."""
    if run_id:
        data = scan_cache.load_run(run_id)
    else:
        runs = scan_cache.list_runs(limit=1, since_date=None)
        if not runs:
            print("No cached runs found.")
            return
        data = scan_cache.load_run(runs[0]["run_id"])

    signals = data.get("signals") or {}
    if not signals:
        print("No signals stored in this run.")
        return

    print("Signal distribution by agent (tickers per signal):\n")
    for agent_key in sorted(signals.keys()):
        per_ticker = signals.get(agent_key) or {}
        counts = {"bullish": 0, "bearish": 0, "neutral": 0, "other": 0}
        for _ticker, sig in per_ticker.items():
            s = (sig or {}).get("signal")
            if s in counts:
                counts[s] += 1
            else:
                counts["other"] += 1
        total = sum(counts.values())
        print(
            f"{agent_key}: total={total}  "
            f"bullish={counts['bullish']}  bearish={counts['bearish']}  "
            f"neutral={counts['neutral']}  other={counts['other']}"
        )


def cmd_prune(scan_cache: ScanCache, keep_weeks: int) -> None:
    """Remove run directories older than keep_weeks."""
    if keep_weeks <= 0:
        print(
            "keep-weeks must be > 0 to delete anything. With 0, all runs are kept (default policy)."
        )
        return
    removed = scan_cache.prune_old_runs(keep_weeks=keep_weeks)
    print(f"Pruned {removed} run(s) (kept last {keep_weeks} weeks).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan cache: list, inspect, and prune cached market scan runs"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List cached runs (newest first)")
    list_p = sub.add_parser("show", help="Show one run by run_id")
    list_p.add_argument("run_id", help="Run ID (e.g. from list)")
    list_p.add_argument("--raw", action="store_true", help="Print full JSON")
    sig_p = sub.add_parser(
        "signals", help="Show per-agent signal distribution for a run (default: latest)"
    )
    sig_p.add_argument("--run-id", help="Run ID (if omitted, use latest run)", dest="run_id")
    prune_p = sub.add_parser(
        "prune", help="Delete runs older than N weeks (destructive; default policy keeps all)"
    )
    prune_p.add_argument(
        "--keep-weeks",
        type=int,
        required=True,
        help="Keep only runs newer than this many weeks (must be > 0)",
    )
    parser.add_argument("--limit", type=int, default=50, help="Max runs to list (default 50)")
    parser.add_argument(
        "--since", type=str, default="", help="Only runs on or after date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--cache-dir", type=str, default="data/scan_cache", help="Scan cache directory"
    )
    args = parser.parse_args()
    cache = ScanCache(base_dir=args.cache_dir)
    if args.command == "list":
        cmd_list(cache, args.limit, args.since)
    elif args.command == "show":
        cmd_show(cache, args.run_id, getattr(args, "raw", False))
    elif args.command == "prune":
        cmd_prune(cache, getattr(args, "keep_weeks", 12))
    else:  # signals
        cmd_signals(cache, getattr(args, "run_id", None))


if __name__ == "__main__":
    main()
