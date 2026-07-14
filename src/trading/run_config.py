"""Shared weekly run_config builder for entrypoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import json

PROFILES_PATH = Path("config/run_profiles.json")


def load_run_profile(name: str) -> Dict[str, Any]:
    if not PROFILES_PATH.is_file():
        return {}
    with open(PROFILES_PATH, encoding="utf-8") as f:
        profiles = json.load(f) or {}
    return dict(profiles.get(name) or {})


def merge_run_profile(run_config: Dict[str, Any], profile_name: Optional[str]) -> Dict[str, Any]:
    if not profile_name:
        return run_config
    profile = load_run_profile(profile_name)
    merged = {**profile, **run_config}
    return merged


def apply_experiment_flags(run_config: Dict[str, Any], flags: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    flags = flags or {}
    if not flags:
        return run_config
    out = dict(run_config)
    out["experiment"] = {
        "name": str(flags.get("name") or "unnamed"),
        "variant": str(flags.get("variant") or "A"),
    }
    for k, v in flags.items():
        if k not in ("name", "variant"):
            out[k] = v
    return out


def apply_shadow_variants(run_config: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(run_config)
    variants = out.get("shadow_variants") or []
    norm = []
    for v in variants:
        if not isinstance(v, dict):
            continue
        norm.append(
            {
                "name": str(v.get("name") or "candidate"),
                "overrides": dict(v.get("overrides") or {}),
            }
        )
    out["shadow_variants"] = norm
    return out


def apply_phase12_defaults(run_config: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(run_config)
    out.setdefault("use_portfolio_optimizer", False)
    out.setdefault("use_adaptive_execution_tactics", True)
    out.setdefault("reconcile_polls", 3)
    out.setdefault("canary_min_consecutive", 3)
    return out


def apply_phase13_defaults(run_config: Dict[str, Any]) -> Dict[str, Any]:
    from src.portfolio.phase13_policy import apply_phase13_defaults as _p13

    return _p13(run_config)


def apply_beat_spy_defaults(run_config: Dict[str, Any]) -> Dict[str, Any]:
    from src.portfolio.beat_spy_policy import apply_beat_spy_defaults as _bs

    return _bs(run_config)

