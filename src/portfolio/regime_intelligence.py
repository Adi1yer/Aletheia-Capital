"""Regime state persistence with hysteresis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

STATE_PATH = Path("data/performance/regime_state.json")


def _load(path: Path = STATE_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(payload: Dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def apply_hysteresis(
    detected: Dict[str, Any],
    *,
    min_confidence: float = 0.6,
    flip_margin: float = 0.03,
    path: Path = STATE_PATH,
) -> Dict[str, Any]:
    """Reduce regime flip-flop by requiring confidence and margin."""
    prev = _load(path)
    mode = str(detected.get("mode") or "neutral")
    last = float(detected.get("last_close") or 0.0)
    sma = float(detected.get("sma_200") or 0.0)
    if last <= 0 or sma <= 0:
        detected["confidence"] = 0.0
        detected["stable_mode"] = mode
        return detected

    distance = abs(last - sma) / sma
    confidence = min(1.0, distance / max(flip_margin, 1e-6))
    detected["confidence"] = round(confidence, 4)

    prev_mode = str(prev.get("stable_mode") or mode)
    if confidence < min_confidence:
        detected["stable_mode"] = prev_mode
        detected["hysteresis"] = "held_previous_low_confidence"
    elif prev_mode == mode:
        detected["stable_mode"] = mode
        detected["hysteresis"] = "unchanged"
    elif distance >= flip_margin:
        detected["stable_mode"] = mode
        detected["hysteresis"] = "flipped"
    else:
        detected["stable_mode"] = prev_mode
        detected["hysteresis"] = "held_previous_margin"

    _save({"stable_mode": detected["stable_mode"], "confidence": detected["confidence"]}, path)
    return detected


def confidence_band(confidence: float) -> str:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def route_policy_by_regime(regime: Dict[str, Any], run_config: Dict[str, Any]) -> Dict[str, Any]:
    """Adjust policy/budget knobs by regime confidence band."""
    band = confidence_band(float(regime.get("confidence") or 0.0))
    out = dict(run_config)
    out["regime_confidence_band"] = band
    llm_budget = dict(out.get("lane_llm_budget") or {})
    if band == "high":
        out["max_llm_calls"] = int(out.get("max_llm_calls", 20)) + 2
    elif band == "low":
        out["max_llm_calls"] = max(1, int(out.get("max_llm_calls", 20)) - 3)
        for lane in llm_budget:
            llm_budget[lane] = max(1, int(llm_budget[lane]) - 1)
    out["lane_llm_budget"] = llm_budget
    return out
