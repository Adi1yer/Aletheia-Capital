"""Canary promotion evaluator for policy/weight candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

CANARY_LEDGER = Path("data/performance/canary_ledger.jsonl")


def append_canary_result(candidate_id: str, metrics: Dict[str, Any], *, path: Path = CANARY_LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"candidate_id": candidate_id, "metrics": metrics}) + "\n")


def evaluate_canary(candidate_id: str, *, min_consecutive: int = 3, path: Path = CANARY_LEDGER) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("candidate_id") == candidate_id:
                    rows.append(row)
    if len(rows) < min_consecutive:
        return {"promote": False, "reason": "insufficient_canary_runs", "count": len(rows)}
    tail = rows[-min_consecutive:]
    ok = all(float((r.get("metrics") or {}).get("delta_accuracy_pp") or 0.0) >= 0 for r in tail)
    if ok:
        return {"promote": True, "reason": "canary_non_regressing", "count": len(rows)}
    return {"promote": False, "reason": "canary_regression", "count": len(rows)}

