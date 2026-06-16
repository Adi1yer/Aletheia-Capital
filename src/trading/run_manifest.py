"""Run manifest schema and persistence helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

MANIFEST_VERSION = "1.0"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_run_manifest(
    *,
    run_id: str,
    run_date: str,
    config: Dict[str, Any],
    active_agents: list[str],
    skipped_agents: list[str],
    artifact_dir: str,
    data_snapshot_path: str,
) -> Dict[str, Any]:
    p = Path(data_snapshot_path)
    return {
        "manifest_version": MANIFEST_VERSION,
        "run_id": run_id,
        "run_date": run_date,
        "config": config,
        "active_agents": list(active_agents),
        "skipped_agents": list(skipped_agents),
        "artifact_dir": artifact_dir,
        "data_snapshot_path": data_snapshot_path,
        "data_snapshot_sha256": file_sha256(p) if p.is_file() else "",
    }


def write_run_manifest(path: Path, manifest: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def build_deployment_attestation(
    *,
    run_id: str,
    promoted: bool,
    promotion_reason: str,
    rollback_trigger: str,
    manifest_sha256: str,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "promoted": bool(promoted),
        "promotion_reason": promotion_reason,
        "rollback_trigger": rollback_trigger,
        "manifest_sha256": manifest_sha256,
        "attestation_version": "1.0",
    }

