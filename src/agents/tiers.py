"""Agent tier resolution for weekly production runs."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

DEFAULT_TIERS_PATH = Path("config/agents_tiers.json")


def load_tier_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    path = Path(config_path or DEFAULT_TIERS_PATH)
    if not path.is_file():
        raise FileNotFoundError(f"Agent tiers config not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_active_agent_keys(
    *,
    tier_mode: str = "tiered",
    config_path: Optional[str] = None,
    reference_date: Optional[date] = None,
    override: Optional[List[str]] = None,
    core_only: bool = False,
    registered_keys: Optional[List[str]] = None,
) -> List[str]:
    """
    Resolve which agent keys run this cycle.

    tier_mode:
      - full: all registered agents
      - tiered: core + rotating slice of extended
      - core: core agents only (dev-smoke profile)
    override: explicit list wins when non-empty
    """
    if override:
        keys = [k.strip().lower().replace(" ", "_") for k in override if k.strip()]
        if registered_keys:
            reg = set(registered_keys)
            keys = [k for k in keys if k in reg]
        return keys

    if tier_mode == "full":
        return list(registered_keys or [])

    cfg = load_tier_config(config_path)
    core = [k.strip().lower().replace(" ", "_") for k in cfg.get("core") or []]

    if core_only or tier_mode == "core":
        return core

    extended = [k.strip().lower().replace(" ", "_") for k in cfg.get("extended") or []]
    rotation_weeks = max(1, int(cfg.get("extended_rotation_weeks", 2)))

    ref = reference_date or datetime.now().date()
    iso_week = ref.isocalendar()[1]
    week_slot = iso_week % rotation_weeks

    n_ext = len(extended)
    if n_ext == 0:
        active = core
    else:
        per_week = (n_ext + rotation_weeks - 1) // rotation_weeks
        start = week_slot * per_week
        active_extended = extended[start : start + per_week]
        active = core + active_extended

    if registered_keys:
        reg = set(registered_keys)
        active = [k for k in active if k in reg]

    return active


def skipped_agent_keys(
    registered_keys: List[str],
    active_keys: List[str],
) -> List[str]:
    active = set(active_keys)
    return [k for k in registered_keys if k not in active]
