#!/usr/bin/env python3
"""Bundle incident artifacts for a given run ID."""

from __future__ import annotations

import argparse
import json
import tarfile
from datetime import datetime
from pathlib import Path

from src.scan_cache import ScanCache
from src.trading.replay import replay_run, decision_diff


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    args = p.parse_args()
    cache = ScanCache()
    run = cache.load_run(args.run_id)
    out_dir = Path("data/performance/incident_bundles")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    bundle_root = out_dir / f"{args.run_id}_{stamp}"
    bundle_root.mkdir(parents=True, exist_ok=True)
    with open(bundle_root / "run.json", "w", encoding="utf-8") as f:
        json.dump(run, f, indent=2, default=str)
    try:
        replayed = replay_run(args.run_id, scan_cache=cache)
        diff = decision_diff({"decisions": run.get("decisions") or {}}, {"decisions": replayed.get("decisions") or {}})
        with open(bundle_root / "replay_diff.json", "w", encoding="utf-8") as f:
            json.dump(diff, f, indent=2)
    except Exception:
        pass
    for rel in (
        Path("data/performance/policy_calibration.json"),
        Path("data/performance/policy_calibration.candidate.json"),
    ):
        if rel.is_file():
            (bundle_root / rel.name).write_text(rel.read_text(encoding="utf-8"), encoding="utf-8")
    tar_path = out_dir / f"{args.run_id}_{stamp}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(bundle_root, arcname=bundle_root.name)
    print(str(tar_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

