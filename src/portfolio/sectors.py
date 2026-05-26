"""Ticker sector lookup for concentration caps."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SECTORS_PATH = Path("config/ticker_sectors.json")


@lru_cache(maxsize=1)
def _load_sectors() -> dict:
    if not SECTORS_PATH.is_file():
        return {}
    with open(SECTORS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_sector(ticker: str) -> str:
    return (_load_sectors().get(ticker.upper()) or "Unknown").strip() or "Unknown"
