"""Append-only run log for later labeling and evaluation."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict

from src.biotech.models import BiotechRunRecord


def append_run(record: BiotechRunRecord, path: str = "data/biotech_runs/runs.jsonl") -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    line = json.dumps(
        {
            "ts": datetime.utcnow().isoformat() + "Z",
            "record": record.model_dump(),
        },
        default=str,
    )
    with open(path, "a") as f:
        f.write(line + "\n")
