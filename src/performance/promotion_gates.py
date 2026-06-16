"""Walk-forward promotion gates for weight and policy proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

HOLD_PATH = Path("data/performance/calibration_hold.json")


def calibration_hold_active(path: Optional[Path] = None) -> bool:
    path = path or HOLD_PATH
    if not path.is_file():
        return False
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("active"))
    except Exception:
        return False


def set_calibration_hold(active: bool, reason: str = "", path: Path = HOLD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"active": active, "reason": reason}, f, indent=2)


def _pairs_from_scan_cache(scan_cache: Any, limit: int = 12) -> List[Tuple[Dict, Dict]]:
    if scan_cache is None:
        return []
    try:
        runs = sorted(scan_cache.list_runs(limit=limit + 1), key=lambda r: r.get("run_date") or "")
        if len(runs) < 2:
            return []
        loaded = []
        for meta in runs[-(limit + 1) :]:
            try:
                loaded.append((meta, scan_cache.load_run(meta["run_id"])))
            except Exception:
                continue
        pairs = []
        for i in range(len(loaded) - 1):
            pairs.append((loaded[i][1], loaded[i + 1][1]))
        return pairs
    except Exception:
        return []


def _pair_accuracy(
    run_left: Dict,
    run_right: Dict,
    *,
    weights: Optional[Dict[str, float]] = None,
    min_confidence: int = 0,
) -> Tuple[float, float, int]:
    left_risk = run_left.get("risk") or {}
    right_risk = run_right.get("risk") or {}
    signals = run_left.get("signals") or {}
    hits = n = 0
    cw = 0.0
    for agent_key, tsigs in signals.items():
        if not isinstance(tsigs, dict):
            continue
        for ticker, sig in tsigs.items():
            if not isinstance(sig, dict):
                continue
            sig_val = sig.get("signal")
            conf = int(sig.get("confidence") or 50)
            conf = int(conf * float((weights or {}).get(agent_key, 1.0)))
            if sig_val not in ("bullish", "bearish"):
                continue
            if conf < int(min_confidence):
                continue
            p0 = float((left_risk.get(ticker) or {}).get("current_price") or 0)
            p1 = float((right_risk.get(ticker) or {}).get("current_price") or 0)
            if p0 <= 0:
                continue
            ret = (p1 - p0) / p0 * 100.0
            n += 1
            if sig_val == "bullish":
                hit = ret > 0
                cw += ret * (conf / 100.0)
            else:
                hit = ret < 0
                cw += (-ret) * (conf / 100.0)
            if hit:
                hits += 1
    acc = hits / n if n else 0.0
    return acc, cw, n


def evaluate_proposal(
    *,
    proposed_weights: Optional[Dict[str, float]] = None,
    proposed_policy: Optional[Dict[str, Any]] = None,
    scan_cache: Any = None,
    holdout_pairs: int = 2,
    total_pairs: int = 12,
    acc_tolerance: float = 0.01,
    cw_tolerance: float = 0.5,
    baseline_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Validate proposed learning changes on holdout run pairs (most recent pairs excluded from train).

    Returns {promote, reason, in_sample, holdout, baseline_holdout}.
    """
    proposed_weights = proposed_weights or {}
    proposed_policy = proposed_policy or {}

    if calibration_hold_active():
        return {
            "promote": False,
            "reason": "calibration_hold_active",
            "in_sample": {},
            "holdout": {},
            "baseline_holdout": {},
        }

    pairs = _pairs_from_scan_cache(scan_cache, limit=total_pairs)
    if len(pairs) < holdout_pairs + 1:
        return {
            "promote": False,
            "reason": "insufficient_pairs_for_holdout",
            "in_sample": {},
            "holdout": {},
            "baseline_holdout": {},
        }

    train_pairs = pairs[: -(holdout_pairs)]
    holdout = pairs[-holdout_pairs:]

    proposed_min_conf = int(proposed_policy.get("min_buy_confidence") or 0)
    baseline_min_conf = int((proposed_policy.get("baseline_min_buy_confidence") or 0))

    def _agg(
        ps: List[Tuple[Dict, Dict]],
        *,
        weights: Optional[Dict[str, float]] = None,
        min_conf: int = 0,
    ) -> Dict[str, Any]:
        accs, cws, ns = [], [], 0
        tickers: set[str] = set()
        for left, right in ps:
            a, c, n = _pair_accuracy(left, right, weights=weights, min_confidence=min_conf)
            if n:
                accs.append(a)
                cws.append(c)
                ns += n
            left_risk = left.get("risk") or {}
            right_risk = right.get("risk") or {}
            for tk in set(left_risk).intersection(set(right_risk)):
                tickers.add(str(tk))
        return {
            "directional_accuracy": round(sum(accs) / len(accs), 4) if accs else 0.0,
            "confidence_weighted_return": round(sum(cws), 4),
            "observations": ns,
            "unique_tickers": len(tickers),
        }

    in_sample = _agg(train_pairs, weights=proposed_weights, min_conf=proposed_min_conf)
    holdout_m = _agg(holdout, weights=proposed_weights, min_conf=proposed_min_conf)
    baseline_holdout = _agg(holdout, weights=baseline_weights, min_conf=baseline_min_conf)

    promote = True
    reason = "holdout_ok"
    min_obs = int(proposed_policy.get("min_holdout_observations") or 5)
    min_tickers = int(proposed_policy.get("min_holdout_tickers") or 3)
    if holdout_m.get("observations", 0) < min_obs:
        promote = False
        reason = "holdout_insufficient_observations"
    elif holdout_m.get("unique_tickers", 0) < min_tickers:
        promote = False
        reason = "holdout_insufficient_tickers"
    if holdout_m["observations"] >= 5 and baseline_holdout["observations"] >= 5:
        base_acc = baseline_holdout.get("directional_accuracy") or 0.0
        if holdout_m["directional_accuracy"] < base_acc - acc_tolerance:
            promote = False
            reason = "holdout_accuracy_regression"
        elif holdout_m["confidence_weighted_return"] < (baseline_holdout.get("confidence_weighted_return") or 0) - cw_tolerance:
            promote = False
            reason = "holdout_cw_return_regression"

    result = {
        "promote": promote,
        "reason": reason,
        "in_sample": in_sample,
        "holdout": holdout_m,
        "baseline_holdout": baseline_holdout,
        "proposed_weight_count": len(proposed_weights),
        "proposed_policy_keys": list((proposed_policy or {}).keys()),
    }
    logger.info("Promotion gate evaluation", **{k: result[k] for k in ("promote", "reason")})
    return result
