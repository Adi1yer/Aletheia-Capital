"""Load biotech ticker watchlist from file and/or environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from src.config.settings import settings


def load_biotech_tickers(watchlist_path: str | None = None) -> List[str]:
    """
    Merge tickers from:
    1. BIOTECH_TICKERS (comma-separated) if set
    2. Else lines from biotech_watchlist_path (one ticker per line, # comments)
    """
    env = (os.getenv("BIOTECH_TICKERS") or "").strip()
    if env:
        return [t.strip().upper() for t in env.split(",") if t.strip()]

    path = Path(watchlist_path or settings.biotech_watchlist_path)
    if not path.is_file():
        return []

    out: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sym = line.split()[0].strip().upper()
        if sym:
            out.append(sym)
    return list(dict.fromkeys(out))
