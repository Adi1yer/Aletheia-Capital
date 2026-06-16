#!/usr/bin/env python3
"""Generate backtest-vs-live discrepancy report for recent experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.scan_cache import ScanCache
from src.trading.replay import decision_diff


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default="")
    args = p.parse_args()
    cache = ScanCache()
    runs = cache.list_runs(limit=2)
    if not runs:
        print(json.dumps({"error": "no_runs"}))
        return 1
    baseline_id = args.run_id or runs[0]["run_id"]
    baseline = cache.load_run(baseline_id)
    replay_id = runs[1]["run_id"] if len(runs) > 1 and runs[1]["run_id"] != baseline_id else baseline_id
    replayed = cache.load_run(replay_id)
    diff = decision_diff(
        {"decisions": baseline.get("decisions") or {}},
        {"decisions": replayed.get("decisions") or {}},
    )
    payload = {
        "baseline_run_id": baseline_id,
        "comparison_run_id": replay_id,
        "changed_count": len(diff.get("changed") or []),
        "missing_count": len(diff.get("missing") or []),
        "new_count": len(diff.get("new") or []),
        "top_changes": (diff.get("changed") or [])[:20],
        "hypothesis_failures": [
            c for c in (diff.get("changed") or [])
            if abs(int(c.get("baseline_conf") or 0) - int(c.get("replay_conf") or 0)) >= 15
        ],
    }
    out = Path("data/performance/research_discrepancy_latest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
