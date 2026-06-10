"""Learn biotech catalyst policy knobs from resolved thesis_ledger trades."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.biotech.thesis_ledger import recent_entries
from src.config.settings import settings

logger = structlog.get_logger()

POLICY_PATH = Path(
    getattr(settings, "biotech_policy_path", "config/biotech_policy.json")
)
LEARNING_BLOCKLIST_PATH = Path(
    getattr(settings, "biotech_learning_blocklist_path", "config/biotech_learning_blocklist.txt")
)

DISCOVERY_POLICY_KEYS = frozenset(
    {
        "discovery_min_phase",
        "readout_max_forward_days",
        "min_days_to_readout",
    }
)

EXECUTION_POLICY_KEYS = frozenset(
    {
        "min_llm_prob_mid",
        "min_prob_range_width",
        "max_premium_pct_equity",
        "max_premium_to_expected_move_ratio",
        "mechanical_arm_enabled",
        "llm_gated_arm_enabled",
    }
)

DISCOVERY_MIN_CLOSED_TRADES = 6
DISCOVERY_MIN_PHASE_FLOOR = 1
DISCOVERY_READOUT_MAX_FORWARD_FLOOR = 90

DEFAULT_POLICY: Dict[str, Any] = {
    "min_llm_prob_mid": 0.45,
    "min_prob_range_width": 0.10,
    "max_premium_pct_equity": 0.02,
    "discovery_min_phase": 2,
    "readout_max_forward_days": 90,
    "min_days_to_readout": 0,
    "max_premium_to_expected_move_ratio": 8.0,
    "mechanical_arm_enabled": True,
    "llm_gated_arm_enabled": True,
}

BOUNDS: Dict[str, Tuple[float, float]] = {
    "min_llm_prob_mid": (0.30, 0.70),
    "min_prob_range_width": (0.05, 0.35),
    "max_premium_pct_equity": (0.005, 0.04),
    "discovery_min_phase": (0, 4),
    "readout_max_forward_days": (30, 180),
    "min_days_to_readout": (0, 30),
    "max_premium_to_expected_move_ratio": (3.0, 20.0),
}


def _clamp(knob: str, value: float) -> float:
    lo, hi = BOUNDS.get(knob, (value, value))
    return max(lo, min(hi, value))


def _avg(vals: List[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _policy_fresh(saved: Dict[str, Any], max_age_weeks: int = 12) -> bool:
    ts = saved.get("generated_at")
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "").split("+")[0])
        return datetime.utcnow() - dt <= timedelta(weeks=max_age_weeks)
    except Exception:
        return False


def load_biotech_policy(path: Path = POLICY_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_biotech_policy(policy: Dict[str, Any], path: Path = POLICY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = dict(policy)
    out["generated_at"] = datetime.utcnow().isoformat() + "Z"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    logger.info("Saved biotech policy", path=str(path))


def default_policy_from_settings() -> Dict[str, Any]:
    return {
        "min_llm_prob_mid": 0.45,
        "min_prob_range_width": 0.10,
        "max_premium_pct_equity": float(
            getattr(settings, "biotech_default_max_premium_pct", 0.02) or 0.02
        ),
        "discovery_min_phase": int(settings.biotech_discovery_min_phase),
        "readout_max_forward_days": int(settings.biotech_discovery_readout_max_forward_days),
        "min_days_to_readout": 0,
        "max_premium_to_expected_move_ratio": 8.0,
        "mechanical_arm_enabled": bool(settings.biotech_mechanical_arm_enabled),
        "llm_gated_arm_enabled": bool(settings.biotech_llm_gated_arm_enabled),
    }


def load_baseline(saved: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    defaults = default_policy_from_settings()
    saved = saved if saved is not None else load_biotech_policy()
    if saved and _policy_fresh(saved):
        base = {k: saved.get(k, defaults[k]) for k in DEFAULT_POLICY}
        base["_baseline_source"] = "saved"
        return base
    out = dict(defaults)
    out["_baseline_source"] = "defaults"
    return out


def closed_rows(weeks: int = 24) -> List[Dict[str, Any]]:
    return [
        r
        for r in recent_entries(weeks=weeks)
        if str(r.get("status") or "") in ("closed", "expired")
        and r.get("pnl_pct_of_premium") is not None
    ]


def _phase_number(phase: str) -> int:
    nums = [int(m) for m in re.findall(r"(\d+)", phase or "")]
    return max(nums) if nums else 0


def _days_to_readout(row: Dict[str, Any]) -> Optional[int]:
    try:
        entry = date.fromisoformat(str(row.get("entry_date") or row.get("run_date") or "")[:10])
        rd = date.fromisoformat(str(row.get("readout_date_expected") or "")[:10])
        return (rd - entry).days
    except ValueError:
        return None


def historical_avg_5d_move_pct(weeks: int = 24) -> float:
    """Average absolute 5d underlying move % for closed trades (premium efficiency)."""
    moves = []
    for r in closed_rows(weeks=weeks):
        e = float(r.get("underlying_px_entry") or 0)
        d5 = float(r.get("underlying_px_5d") or 0)
        if e > 0 and d5 > 0:
            moves.append(abs((d5 - e) / e * 100.0))
    return _avg(moves) if moves else 5.0


def phase_pnl_stats(weeks: int = 24) -> Dict[str, Dict[str, Any]]:
    by_ph: Dict[str, List[float]] = {}
    for r in closed_rows(weeks=weeks):
        ph = str(r.get("phase") or "unknown")
        by_ph.setdefault(ph, []).append(float(r.get("pnl_pct_of_premium") or 0))
    out: Dict[str, Dict[str, Any]] = {}
    for ph, pnls in by_ph.items():
        wins = sum(1 for x in pnls if x > 0)
        out[ph] = {
            "count": len(pnls),
            "avg_pnl_pct": round(_avg(pnls), 2),
            "win_rate_pct": round(100.0 * wins / len(pnls), 1) if pnls else 0,
            "phase_num": _phase_number(ph),
        }
    return out


def ticker_pnl_stats(weeks: int = 24) -> Dict[str, Dict[str, Any]]:
    by_t: Dict[str, List[float]] = {}
    for r in closed_rows(weeks=weeks):
        t = str(r.get("ticker") or "").upper()
        if t:
            by_t.setdefault(t, []).append(float(r.get("pnl_pct_of_premium") or 0))
    out: Dict[str, Dict[str, Any]] = {}
    for t, pnls in by_t.items():
        wins = sum(1 for x in pnls if x > 0)
        out[t] = {
            "count": len(pnls),
            "win_rate_pct": round(100.0 * wins / len(pnls), 1) if pnls else 0,
            "avg_pnl_pct": round(_avg(pnls), 2),
        }
    return out


def compute_biotech_policy(
    weeks: int = 24,
    saved_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Propose policy adjustments from closed thesis ledger rows."""
    saved_policy = saved_policy if saved_policy is not None else load_biotech_policy()
    base = load_baseline(saved_policy)
    baseline_source = base.pop("_baseline_source", "defaults")
    adjustments: List[Dict[str, Any]] = []
    closed = closed_rows(weeks=weeks)
    ph_stats = phase_pnl_stats(weeks=weeks)
    avg_move = historical_avg_5d_move_pct(weeks=weeks)

    llm_closed = [r for r in closed if r.get("arm") == "llm_gated"]
    mech_closed = [r for r in closed if r.get("arm") == "mechanical"]

    # min_llm_prob_mid: losing trades with low prob mid
    low_mid_losses = []
    for r in llm_closed:
        lo = float(r.get("llm_prob_low") or 0)
        hi = float(r.get("llm_prob_high") or 1)
        mid = (lo + hi) / 2.0
        pnl = float(r.get("pnl_pct_of_premium") or 0)
        if pnl < 0:
            low_mid_losses.append(mid)
    if len(low_mid_losses) >= 4 and _avg(low_mid_losses) < float(base["min_llm_prob_mid"]):
        delta = 0.03
        base["min_llm_prob_mid"] = _clamp(
            "min_llm_prob_mid", float(base["min_llm_prob_mid"]) + delta
        )
        adjustments.append(
            {
                "knob": "min_llm_prob_mid",
                "delta": delta,
                "reason": f"llm_gated losers avg prob mid {_avg(low_mid_losses):.2f}",
                "sample_n": len(low_mid_losses),
            }
        )

    # min_prob_range_width: narrow range losses
    narrow_losses = [
        r
        for r in llm_closed
        if float(r.get("pnl_pct_of_premium") or 0) < 0
        and (float(r.get("llm_prob_high") or 1) - float(r.get("llm_prob_low") or 0))
        < float(base["min_prob_range_width"])
    ]
    if len(narrow_losses) >= 3:
        delta = 0.02
        base["min_prob_range_width"] = _clamp(
            "min_prob_range_width", float(base["min_prob_range_width"]) + delta
        )
        adjustments.append(
            {
                "knob": "min_prob_range_width",
                "delta": delta,
                "reason": f"{len(narrow_losses)} llm_gated losses with narrow prob range",
                "sample_n": len(narrow_losses),
            }
        )

    # max_premium_pct_equity
    all_pnls = [float(r.get("pnl_pct_of_premium") or 0) for r in closed]
    if len(all_pnls) >= 6 and _avg(all_pnls) < -5.0:
        delta = -0.002
        base["max_premium_pct_equity"] = _clamp(
            "max_premium_pct_equity", float(base["max_premium_pct_equity"]) + delta
        )
        adjustments.append(
            {
                "knob": "max_premium_pct_equity",
                "delta": delta,
                "reason": f"all arms avg pnl pct {_avg(all_pnls):.1f}%",
                "sample_n": len(all_pnls),
            }
        )

    discovery_skips: List[Dict[str, Any]] = []
    allow_discovery_tune = len(closed) >= DISCOVERY_MIN_CLOSED_TRADES

    def _apply_discovery_floor() -> None:
        base["discovery_min_phase"] = max(
            DISCOVERY_MIN_PHASE_FLOOR,
            int(_clamp("discovery_min_phase", float(base["discovery_min_phase"]))),
        )
        base["readout_max_forward_days"] = max(
            DISCOVERY_READOUT_MAX_FORWARD_FLOOR,
            int(_clamp("readout_max_forward_days", float(base["readout_max_forward_days"]))),
        )

    # discovery_min_phase from phase stats (requires minimum closed-trade sample)
    if allow_discovery_tune:
        for ph, st in ph_stats.items():
            if (
                st["count"] >= 3
                and st["avg_pnl_pct"] < -15.0
                and st["phase_num"] >= int(base["discovery_min_phase"])
            ):
                new_ph = min(4, st["phase_num"] + 1)
                if new_ph > int(base["discovery_min_phase"]):
                    base["discovery_min_phase"] = int(_clamp("discovery_min_phase", new_ph))
                    adjustments.append(
                        {
                            "knob": "discovery_min_phase",
                            "delta": 1,
                            "reason": f"{ph} avg pnl {st['avg_pnl_pct']}%",
                            "sample_n": st["count"],
                        }
                    )
                    break
    else:
        discovery_skips.append(
            {
                "knob": "discovery_min_phase",
                "reason": f"insufficient_closed_trades (n={len(closed)}/{DISCOVERY_MIN_CLOSED_TRADES})",
            }
        )

    # readout_max_forward_days: late readouts lose
    if allow_discovery_tune:
        late_losses = []
        for r in closed:
            dtr = _days_to_readout(r)
            if dtr is not None and dtr > 60 and float(r.get("pnl_pct_of_premium") or 0) < 0:
                late_losses.append(dtr)
        if len(late_losses) >= 3:
            delta = -10
            base["readout_max_forward_days"] = int(
                _clamp("readout_max_forward_days", float(base["readout_max_forward_days"]) + delta)
            )
            adjustments.append(
                {
                    "knob": "readout_max_forward_days",
                    "delta": delta,
                    "reason": f"{len(late_losses)} losses with readout >60d out",
                    "sample_n": len(late_losses),
                }
            )

    # min_days_to_readout
    if allow_discovery_tune:
        short_losses = [
            r
            for r in closed
            if (_days_to_readout(r) or 999) < 7 and float(r.get("pnl_pct_of_premium") or 0) < 0
        ]
        if len(short_losses) >= 3:
            delta = 3
            base["min_days_to_readout"] = int(
                _clamp("min_days_to_readout", float(base["min_days_to_readout"]) + delta)
            )
            adjustments.append(
                {
                    "knob": "min_days_to_readout",
                    "delta": delta,
                    "reason": f"{len(short_losses)} losses with readout <7d away",
                    "sample_n": len(short_losses),
                }
            )

    _apply_discovery_floor()

    # premium efficiency ratio
    if avg_move > 0:
        high_ratio_losses = [
            r
            for r in closed
            if float(r.get("premium_filled_usd") or r.get("premium_est_usd") or 0) > 0
            and float(r.get("pnl_pct_of_premium") or 0) < 0
        ]
        if len(high_ratio_losses) >= 4:
            delta = -0.5
            base["max_premium_to_expected_move_ratio"] = _clamp(
                "max_premium_to_expected_move_ratio",
                float(base["max_premium_to_expected_move_ratio"]) + delta,
            )
            adjustments.append(
                {
                    "knob": "max_premium_to_expected_move_ratio",
                    "delta": delta,
                    "reason": "premium efficiency losses",
                    "sample_n": len(high_ratio_losses),
                }
            )

    # arm enablement
    if len(mech_closed) >= 8:
        mech_wr = sum(1 for r in mech_closed if float(r.get("pnl_pct_of_premium") or 0) > 0) / len(
            mech_closed
        )
        if mech_wr < 0.25:
            base["mechanical_arm_enabled"] = False
            adjustments.append(
                {
                    "knob": "mechanical_arm_enabled",
                    "delta": False,
                    "reason": f"mechanical win rate {mech_wr:.0%} over {len(mech_closed)}",
                    "sample_n": len(mech_closed),
                }
            )
    if len(llm_closed) >= 6 and len(mech_closed) >= 6:
        llm_avg = _avg([float(r.get("pnl_pct_of_premium") or 0) for r in llm_closed])
        mech_avg = _avg([float(r.get("pnl_pct_of_premium") or 0) for r in mech_closed])
        if llm_avg < mech_avg - 10.0:
            base["llm_gated_arm_enabled"] = False
            adjustments.append(
                {
                    "knob": "llm_gated_arm_enabled",
                    "delta": False,
                    "reason": f"llm_gated avg {llm_avg:.1f}% vs mechanical {mech_avg:.1f}%",
                    "sample_n": len(llm_closed),
                }
            )

    update_learning_blocklist(weeks=weeks)

    return {
        "policy": {k: base[k] for k in DEFAULT_POLICY},
        "adjustments": adjustments,
        "discovery_skips": discovery_skips,
        "baseline_source": baseline_source,
        "closed_count": len(closed),
        "phase_stats": ph_stats,
        "historical_avg_5d_move_pct": round(avg_move, 2),
    }


def policy_summary_for_prompt(policy_result: Dict[str, Any]) -> str:
    pol = policy_result.get("policy") if "policy" in policy_result else policy_result
    ph = policy_result.get("phase_stats") or {}
    lines = [
        f"min_llm_prob_mid={pol.get('min_llm_prob_mid', 0.45)}",
        f"min_prob_range_width={pol.get('min_prob_range_width', 0.1)}",
        f"readout_max_forward_days={pol.get('readout_max_forward_days', 90)}",
        f"historical_avg_5d_move_pct={policy_result.get('historical_avg_5d_move_pct', 'n/a')}",
    ]
    for p, st in list(ph.items())[:5]:
        lines.append(f"  {p}: n={st.get('count')} win={st.get('win_rate_pct')}% avg_pnl={st.get('avg_pnl_pct')}%")
    return "\n".join(lines)


def update_learning_blocklist(weeks: int = 24, min_trades: int = 3, max_win_rate: float = 25.0) -> List[str]:
    """Append tickers with poor history to learning blocklist file."""
    stats = ticker_pnl_stats(weeks=weeks)
    existing: Set[str] = set()
    if LEARNING_BLOCKLIST_PATH.is_file():
        for line in LEARNING_BLOCKLIST_PATH.read_text(encoding="utf-8").splitlines():
            s = line.split("#")[0].strip().upper()
            if s:
                existing.add(s)
    added: List[str] = []
    for t, st in stats.items():
        if st["count"] >= min_trades and st["win_rate_pct"] < max_win_rate and t not in existing:
            existing.add(t)
            added.append(t)
    if added:
        LEARNING_BLOCKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LEARNING_BLOCKLIST_PATH, "a", encoding="utf-8") as f:
            for t in sorted(added):
                f.write(f"{t}  # auto: win_rate below {max_win_rate}% over {min_trades}+ trades\n")
        logger.info("Updated biotech learning blocklist", added=added)
    return added


def load_learning_blocklist() -> Set[str]:
    out: Set[str] = set()
    if LEARNING_BLOCKLIST_PATH.is_file():
        for line in LEARNING_BLOCKLIST_PATH.read_text(encoding="utf-8").splitlines():
            s = line.split("#")[0].strip().upper()
            if s:
                out.add(s)
    return out


def get_active_policy() -> Dict[str, Any]:
    """Merged policy for runtime (saved if fresh else defaults)."""
    saved = load_biotech_policy()
    base = load_baseline(saved)
    base.pop("_baseline_source", None)
    return base
