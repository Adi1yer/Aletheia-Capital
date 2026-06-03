"""Learned rebalance policy knobs from decision + options ledgers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.performance.decision_ledger import recent_entries as recent_decisions
from src.performance.options_ledger import recent_entries as recent_options

logger = structlog.get_logger()

POLICY_PATH = Path("data/performance/policy_calibration.json")

BASELINE_KEYS = (
    "min_buy_confidence",
    "min_sell_confidence",
    "cash_rotation_min_edge",
    "min_csp_premium_usd",
)

BOUNDS = {
    "min_buy_confidence": (50, 85),
    "min_sell_confidence": (50, 90),
    "cash_rotation_min_edge": (8, 20),
    "min_csp_premium_usd": (50, 150),
}


def _clamp(knob: str, value: float) -> float:
    lo, hi = BOUNDS.get(knob, (0, 999))
    return max(lo, min(hi, value))


def _avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _saved_policy_fresh(saved: Dict[str, Any], max_age_weeks: int = 12) -> bool:
    ts = saved.get("generated_at")
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00").replace("+00:00", ""))
        age = datetime.utcnow() - dt
        return age <= timedelta(weeks=max_age_weeks)
    except Exception:
        return False


def load_baseline(run_config: Dict[str, Any], saved: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Start from saved policy if fresh, else current run_config knobs."""
    saved = saved or {}
    cli_defaults = {
        "min_buy_confidence": int(run_config.get("min_buy_confidence", 60)),
        "min_sell_confidence": int(run_config.get("min_sell_confidence", 60)),
        "cash_rotation_min_edge": int(run_config.get("cash_rotation_min_edge", 12)),
        "min_csp_premium_usd": float(run_config.get("min_csp_premium_usd", 75.0)),
    }
    if saved and _saved_policy_fresh(saved):
        base = {}
        for k in BASELINE_KEYS:
            if k in saved:
                base[k] = saved[k]
            else:
                base[k] = cli_defaults[k]
        base["_baseline_source"] = "saved"
        return base
    out = dict(cli_defaults)
    out["_baseline_source"] = "cli"
    return out


def compute_policy(
    run_config: Dict[str, Any],
    weeks: int = 12,
    saved_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute policy adjustments from recent ledgers."""
    saved_policy = saved_policy if saved_policy is not None else load_policy()
    base = load_baseline(run_config, saved_policy)
    baseline_source = base.pop("_baseline_source", "cli")
    adjustments: List[Dict[str, Any]] = []
    decisions = [
        d
        for d in recent_decisions(weeks=weeks)
        if d.get("forward_return_pct") is not None and d.get("executed")
    ]

    buy_70_79 = [
        float(d["forward_return_pct"])
        for d in decisions
        if d.get("action") == "buy" and 70 <= int(d.get("confidence") or 0) < 80
    ]
    buy_80_plus = [
        float(d["forward_return_pct"])
        for d in decisions
        if d.get("action") == "buy" and int(d.get("confidence") or 0) >= 80
    ]
    rotation_sells = [
        float(d["forward_return_pct"])
        for d in decisions
        if d.get("action") == "sell" and d.get("reason_class") == "cash_rotation"
    ]
    sells = [
        float(d["forward_return_pct"])
        for d in decisions
        if d.get("action") == "sell"
        and int(d.get("confidence") or 0) >= int(base.get("min_sell_confidence", 60))
    ]

    if len(buy_70_79) >= 8 and _avg(buy_70_79) < -1.0:
        delta = 2
        base["min_buy_confidence"] = int(_clamp("min_buy_confidence", base["min_buy_confidence"] + delta))
        adjustments.append(
            {
                "knob": "min_buy_confidence",
                "delta": delta,
                "reason": f"70-79% buys avg return {_avg(buy_70_79):.2f}%",
                "sample_n": len(buy_70_79),
            }
        )
    elif len(buy_80_plus) >= 8 and _avg(buy_80_plus) > 2.0:
        delta = -1
        base["min_buy_confidence"] = int(_clamp("min_buy_confidence", base["min_buy_confidence"] + delta))
        adjustments.append(
            {
                "knob": "min_buy_confidence",
                "delta": delta,
                "reason": f"80%+ buys avg return {_avg(buy_80_plus):+.2f}%",
                "sample_n": len(buy_80_plus),
            }
        )

    if len(sells) >= 6 and _avg(sells) < -1.5:
        delta = -2
        base["min_sell_confidence"] = int(_clamp("min_sell_confidence", base["min_sell_confidence"] + delta))
        adjustments.append(
            {
                "knob": "min_sell_confidence",
                "delta": delta,
                "reason": f"sells avg decision return {_avg(sells):.2f}%",
                "sample_n": len(sells),
            }
        )
    elif len(sells) >= 6 and _avg(sells) > 2.0:
        delta = 1
        base["min_sell_confidence"] = int(_clamp("min_sell_confidence", base["min_sell_confidence"] + delta))
        adjustments.append(
            {
                "knob": "min_sell_confidence",
                "delta": delta,
                "reason": f"sells avg decision return {_avg(sells):+.2f}%",
                "sample_n": len(sells),
            }
        )

    if len(rotation_sells) >= 5 and _avg(rotation_sells) < -2.0:
        delta = 2
        base["cash_rotation_min_edge"] = int(
            _clamp("cash_rotation_min_edge", base["cash_rotation_min_edge"] + delta)
        )
        adjustments.append(
            {
                "knob": "cash_rotation_min_edge",
                "delta": delta,
                "reason": f"rotation sells avg decision return {_avg(rotation_sells):.2f}%",
                "sample_n": len(rotation_sells),
            }
        )

    opts = recent_options(weeks=weeks)
    csp_exec = [o for o in opts if o.get("strategy") == "csp" and o.get("status") == "executed"]
    floor = base["min_csp_premium_usd"]
    low_premium = [o for o in csp_exec if float(o.get("premium_usd") or 0) < floor]
    if len(low_premium) >= 2:
        delta = 5
        base["min_csp_premium_usd"] = _clamp("min_csp_premium_usd", floor + delta)
        adjustments.append(
            {
                "knob": "min_csp_premium_usd",
                "delta": delta,
                "reason": f"{len(low_premium)} CSP fills below floor ${floor:.0f}",
                "sample_n": len(low_premium),
            }
        )

    resolved_opts = [o for o in opts if o.get("outcome")]
    assigned = [o for o in resolved_opts if o.get("outcome") == "assigned" and o.get("strategy") == "csp"]
    called = [o for o in resolved_opts if o.get("outcome") == "called_away"]
    if len(assigned) >= 2:
        delta = 5
        base["min_csp_premium_usd"] = _clamp("min_csp_premium_usd", base["min_csp_premium_usd"] + delta)
        adjustments.append(
            {
                "knob": "min_csp_premium_usd",
                "delta": delta,
                "reason": f"{len(assigned)} CSP assignments resolved",
                "sample_n": len(assigned),
            }
        )
    if len(called) >= 2:
        run_config.setdefault("min_cc_score", 40)
        run_config["min_cc_score"] = int(min(80, int(run_config.get("min_cc_score", 40)) + 2))
        adjustments.append(
            {
                "knob": "min_cc_score",
                "delta": 2,
                "reason": f"{len(called)} CC called-away outcomes",
                "sample_n": len(called),
            }
        )

    try:
        from src.performance.fill_ledger import slippage_by_reason_class

        slip = slippage_by_reason_class(weeks=weeks)
        rot_slip = slip.get("cash_rotation")
        if rot_slip is not None and rot_slip > 25:
            delta = 1
            base["cash_rotation_min_edge"] = int(
                _clamp("cash_rotation_min_edge", base["cash_rotation_min_edge"] + delta)
            )
            adjustments.append(
                {
                    "knob": "cash_rotation_min_edge",
                    "delta": delta,
                    "reason": f"rotation slippage avg {rot_slip:.0f} bps",
                    "sample_n": 5,
                }
            )
    except Exception:
        pass

    try:
        from src.performance.counterfactual_ledger import recent_resolved

        cf_rows = [
            r
            for r in recent_resolved(weeks=weeks)
            if r.get("would_be_action") == "buy"
        ]
        missed = [float(r["forward_return_pct"]) for r in cf_rows if float(r["forward_return_pct"]) > 2.0]
        if len(missed) >= 6:
            delta = -1
            base["min_buy_confidence"] = int(_clamp("min_buy_confidence", base["min_buy_confidence"] + delta))
            adjustments.append(
                {
                    "knob": "min_buy_confidence",
                    "delta": delta,
                    "reason": f"missed buy opportunities avg +{_avg(missed):.2f}%",
                    "sample_n": len(missed),
                }
            )
    except Exception:
        pass

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "weeks_window": weeks,
        "baseline_source": baseline_source,
        "min_buy_confidence": int(base["min_buy_confidence"]),
        "min_sell_confidence": int(base["min_sell_confidence"]),
        "cash_rotation_min_edge": int(base["cash_rotation_min_edge"]),
        "min_csp_premium_usd": float(base["min_csp_premium_usd"]),
        "adjustments": adjustments,
    }
    return payload


def save_policy(payload: Dict[str, Any], path: Path = POLICY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_policy(path: Path = POLICY_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def apply_learned_policy(
    run_config: Dict[str, Any],
    policy_path: Path = POLICY_PATH,
    recompute: bool = True,
    save: bool = True,
) -> Dict[str, Any]:
    """Merge learned knobs into run_config within bounds. Returns policy summary."""
    saved = load_policy(policy_path)
    if recompute:
        payload = compute_policy(run_config, saved_policy=saved)
        if save:
            save_policy(payload, policy_path)
    else:
        payload = saved
        if not payload:
            payload = compute_policy(run_config, saved_policy={})
            if save:
                save_policy(payload, policy_path)

    for knob in ("min_buy_confidence", "min_sell_confidence", "cash_rotation_min_edge"):
        if knob in payload:
            run_config[knob] = int(_clamp(knob, float(payload[knob])))
    if "min_csp_premium_usd" in payload:
        run_config["min_csp_premium_usd"] = float(
            _clamp("min_csp_premium_usd", float(payload["min_csp_premium_usd"]))
        )
    run_config["policy_calibration"] = payload
    return payload
