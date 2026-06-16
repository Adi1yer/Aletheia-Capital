"""Artifact integrity helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict


def checksum_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(65536)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def write_checksums(root: Path, out_path: Path) -> Dict[str, str]:
    checks: Dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            checks[str(p.relative_to(root))] = checksum_file(p)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(checks, f, indent=2)
    return checks


def verify_run_integrity(run_path: Path) -> Dict[str, object]:
    checksum_path = run_path / "artifacts" / "diagnostics" / "checksums.json"
    if not checksum_path.is_file():
        return {"ok": False, "reason": "missing_checksums"}
    with open(checksum_path, encoding="utf-8") as f:
        expected = json.load(f)
    mismatches = []
    for rel, digest in expected.items():
        p = run_path / rel
        if not p.is_file():
            mismatches.append({"path": rel, "reason": "missing"})
            continue
        if checksum_file(p) != digest:
            mismatches.append({"path": rel, "reason": "hash_mismatch"})
    return {"ok": len(mismatches) == 0, "mismatches": mismatches}

