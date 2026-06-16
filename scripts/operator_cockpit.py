#!/usr/bin/env python3
"""Generate weekly operator cockpit summary from latest run artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from src.scan_cache import ScanCache

OUT = Path("data/performance/operator_cockpit_latest.json")


def main() -> int:
    cache = ScanCache()
    runs = cache.list_runs(limit=1)
    if not runs:
        payload = {"error": "no_runs"}
    else:
        run = cache.load_run(runs[0]["run_id"])
        meta = run.get("meta") or {}
        payload = {
            "run_id": meta.get("run_id") or runs[0]["run_id"],
            "run_date": meta.get("run_date"),
            "ticker_count": meta.get("ticker_count", 0),
            "active_agents": len(meta.get("active_agents") or []),
            "decision_count": len(run.get("decisions") or {}),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

