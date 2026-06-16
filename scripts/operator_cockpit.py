#!/usr/bin/env python3
"""Generate weekly operator cockpit summary from latest run artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from src.performance.fill_ledger import implementation_shortfall_summary, slippage_by_reason_class
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
        diag_dir = Path(cache.base_dir) / runs[0]["run_id"] / "artifacts" / "diagnostics"
        reconciliation = {}
        pretrade = {}
        for name, key in (("reconciliation.json", "reconciliation"), ("pretrade_simulation.json", "pretrade")):
            p = diag_dir / name
            if p.is_file():
                try:
                    blob = json.loads(p.read_text(encoding="utf-8"))
                    if key == "reconciliation":
                        reconciliation = blob
                    else:
                        pretrade = blob
                except Exception:
                    pass
        payload = {
            "run_id": meta.get("run_id") or runs[0]["run_id"],
            "run_date": meta.get("run_date"),
            "ticker_count": meta.get("ticker_count", 0),
            "active_agents": len(meta.get("active_agents") or []),
            "decision_count": len(run.get("decisions") or {}),
            "regime": (meta.get("config") or {}).get("regime") or {},
            "reconciliation": reconciliation,
            "pretrade_simulation": pretrade,
            "implementation_shortfall": implementation_shortfall_summary(),
            "slippage_by_reason_class": slippage_by_reason_class(),
            "lane_budget_recommendation": (meta.get("config") or {}).get("lane_llm_budget") or {},
        }
        fund_metrics = Path("data/fund/weekly_metrics.json")
        if fund_metrics.is_file():
            try:
                payload["fund_metrics"] = json.loads(fund_metrics.read_text(encoding="utf-8"))
            except Exception:
                pass
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
