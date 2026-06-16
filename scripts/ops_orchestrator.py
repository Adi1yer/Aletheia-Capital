#!/usr/bin/env python3
"""Unified ops orchestrator composing existing actions into one entry point."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from src.ops.go_no_go import build_go_no_go_report
from src.ops.slo import evaluate_slos
from src.scan_cache import ScanCache


DEFAULT_STAGES = [
    "preflight",
    "cockpit",
    "slo",
    "gonogo",
    "incident_bundle",
]


def _run(cmd: List[str]) -> Dict[str, Any]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "cmd": cmd,
        "ok": proc.returncode == 0,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
        "exit_code": proc.returncode,
    }


def run_stage(stage: str, *, run_id: str | None = None, strict: bool = False) -> Dict[str, Any]:
    if stage == "preflight":
        return _run([sys.executable, "preflight.py"])
    if stage == "cockpit":
        return _run([sys.executable, "scripts/operator_cockpit.py"])
    if stage == "smoke":
        return _run([sys.executable, "scripts/pipeline_smoke_check.py"])
    if stage == "calibration":
        return _run([sys.executable, "scripts/calibration_eval.py"])
    if stage == "incident_bundle":
        if not run_id:
            return {"ok": False, "reason": "run_id_required"}
        return _run([sys.executable, "scripts/incident_bundle.py", "--run-id", run_id])
    if stage == "slo":
        cache = ScanCache()
        runs = cache.list_runs(limit=1)
        if not runs:
            return {"ok": True, "skipped": True, "reason": "no_runs"}
        run = cache.load_run(runs[0]["run_id"])
        results = {
            "decisions": run.get("decisions") or {},
            "agent_errors": {},
            "data_quality": {"score": 100},
        }
        diag = (run.get("meta") or {}).get("config") or {}
        if isinstance(diag, dict) and diag.get("agent_errors"):
            results["agent_errors"] = diag.get("agent_errors")
        slo = evaluate_slos(results)
        if strict and not slo.get("ok"):
            return {"ok": False, "slo": slo}
        return {"ok": True, "slo": slo}
    if stage == "gonogo":
        cache = ScanCache()
        runs = cache.list_runs(limit=1)
        if not runs:
            return {"ok": True, "skipped": True, "reason": "no_runs"}
        run = cache.load_run(runs[0]["run_id"])
        results = {
            "decisions": run.get("decisions") or {},
            "slo": evaluate_slos({"decisions": run.get("decisions") or {}, "agent_errors": {}, "data_quality": {"score": 100}}),
            "pretrade_simulation": {},
            "execution_status": {},
            "learning_context": {},
            "data_quality": {"score": 100},
        }
        gate = build_go_no_go_report(results)
        if strict and not gate.get("go"):
            return {"ok": False, "go_no_go": gate}
        return {"ok": True, "go_no_go": gate}
    return {"ok": False, "reason": f"unknown_stage:{stage}"}


def main() -> int:
    p = argparse.ArgumentParser(description="Unified ops orchestrator")
    p.add_argument("--stage", default=",".join(DEFAULT_STAGES))
    p.add_argument("--run-id", default="")
    p.add_argument("--strict", action="store_true", help="Fail on SLO/go-no-go breaches")
    args = p.parse_args()

    stages = [s.strip() for s in args.stage.split(",") if s.strip()]
    out: Dict[str, Any] = {"stages": {}, "ok": True}
    for stage in stages:
        result = run_stage(stage, run_id=(args.run_id or None), strict=bool(args.strict))
        out["stages"][stage] = result
        if not result.get("ok", True):
            out["ok"] = False

    out_path = Path("data/performance/ops_orchestrator_latest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
