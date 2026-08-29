"""Horizon-aware agent signal ledger and scorecard (Beat SPY).

Scores each agent at its intended hold horizon instead of week-over-week.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import structlog

logger = structlog.get_logger()

HORIZONS_PATH = Path("config/agent_horizons.json")
LEDGER_PATH = Path("data/performance/agent_signal_ledger.jsonl")
SCORECARD_PATH = Path("data/performance/agent_horizon_scorecard.json")

DEFAULT_WEEKS = 4
DEFAULT_MIN_OBS = 8


def _load_horizons_config(path: Path = HORIZONS_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {"default_weeks": DEFAULT_WEEKS, "buckets": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"default_weeks": DEFAULT_WEEKS, "buckets": {}}


def _agent_index(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    cfg = cfg or _load_horizons_config()
    default_weeks = int(cfg.get("default_weeks") or DEFAULT_WEEKS)
    out: Dict[str, Dict[str, Any]] = {}
    for bucket_name, bucket in (cfg.get("buckets") or {}).items():
        if not isinstance(bucket, dict):
            continue
        weeks = int(bucket.get("eval_horizon_weeks") or default_weeks)
        min_obs = int(bucket.get("min_observations_for_move") or DEFAULT_MIN_OBS)
        for ak in bucket.get("agents") or []:
            key = str(ak).strip()
            if not key:
                continue
            out[key] = {
                "bucket": str(bucket_name),
                "eval_horizon_weeks": weeks,
                "min_observations_for_move": min_obs,
            }
    return out


def horizon_weeks_for_agent(agent_key: str, path: Path = HORIZONS_PATH) -> int:
    idx = _agent_index(_load_horizons_config(path))
    row = idx.get(str(agent_key))
    if row:
        return int(row["eval_horizon_weeks"])
    cfg = _load_horizons_config(path)
    return int(cfg.get("default_weeks") or DEFAULT_WEEKS)


def min_observations_for_agent(agent_key: str, path: Path = HORIZONS_PATH) -> int:
    idx = _agent_index(_load_horizons_config(path))
    row = idx.get(str(agent_key))
    if row:
        return int(row["min_observations_for_move"])
    return DEFAULT_MIN_OBS


def min_observations_by_agent(path: Path = HORIZONS_PATH) -> Dict[str, int]:
    idx = _agent_index(_load_horizons_config(path))
    return {ak: int(v["min_observations_for_move"]) for ak, v in idx.items()}


def horizon_buckets_summary(path: Path = HORIZONS_PATH) -> str:
    """Short note for email: Horizon: short=1w / med=4w / long=8–12w."""
    cfg = _load_horizons_config(path)
    weeks = []
    for name in ("short", "medium", "long", "very_long"):
        b = (cfg.get("buckets") or {}).get(name) or {}
        if "eval_horizon_weeks" in b:
            weeks.append((name, int(b["eval_horizon_weeks"])))
    if not weeks:
        return "Horizon: default=4w"
    short = next((w for n, w in weeks if n == "short"), None)
    med = next((w for n, w in weeks if n == "medium"), None)
    longs = [w for n, w in weeks if n in ("long", "very_long")]
    parts = []
    if short is not None:
        parts.append(f"short={short}w")
    if med is not None:
        parts.append(f"med={med}w")
    if longs:
        lo, hi = min(longs), max(longs)
        parts.append(f"long={lo}–{hi}w" if lo != hi else f"long={lo}w")
    return "Horizon: " + " / ".join(parts)


def _read_ledger(path: Path = LEDGER_PATH) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _write_ledger(rows: List[Dict[str, Any]], path: Path = LEDGER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")


def _append_ledger_rows(rows: List[Dict[str, Any]], path: Path = LEDGER_PATH) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")


def _parse_run_day(run_date: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(run_date)[:10])
    except Exception:
        return None


def append_signals_from_run(
    *,
    run_id: str,
    run_date: str,
    agent_signals: Dict[str, Dict[str, Any]],
    risk_analysis: Dict[str, Any],
    ticker_scope: Optional[Iterable[str]] = None,
    horizons_path: Path = HORIZONS_PATH,
    path: Path = LEDGER_PATH,
) -> int:
    """Append directional agent signals for tickers in scope (holdings + factor deep set)."""
    scope: Optional[Set[str]] = None
    if ticker_scope is not None:
        scope = {str(t) for t in ticker_scope if t}

    existing = _read_ledger(path)
    seen = {
        (str(r.get("run_id")), str(r.get("agent")), str(r.get("ticker")))
        for r in existing
    }

    run_day = _parse_run_day(run_date)
    if run_day is None:
        logger.warning("agent_horizon append skipped: bad run_date", run_date=run_date)
        return 0

    idx = _agent_index(_load_horizons_config(horizons_path))
    default_weeks = int(_load_horizons_config(horizons_path).get("default_weeks") or DEFAULT_WEEKS)
    now = datetime.utcnow().isoformat() + "Z"
    new_rows: List[Dict[str, Any]] = []

    for agent_key, ticker_signals in (agent_signals or {}).items():
        if not isinstance(ticker_signals, dict):
            continue
        meta = idx.get(str(agent_key)) or {}
        weeks = int(meta.get("eval_horizon_weeks") or default_weeks)
        resolve_after = (run_day + timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        for ticker, sig in ticker_signals.items():
            if scope is not None and ticker not in scope:
                continue
            if not isinstance(sig, dict):
                # AgentSignal model_dump or object
                if hasattr(sig, "model_dump"):
                    sig = sig.model_dump()
                elif hasattr(sig, "signal"):
                    sig = {
                        "signal": getattr(sig, "signal", None),
                        "confidence": getattr(sig, "confidence", 0),
                    }
                else:
                    continue
            sval = str(sig.get("signal") or "").lower()
            if sval not in ("bullish", "bearish"):
                continue
            key = (str(run_id), str(agent_key), str(ticker))
            if key in seen:
                continue
            risk = risk_analysis.get(ticker) or {}
            px = float(risk.get("current_price") or 0.0) if isinstance(risk, dict) else 0.0
            if px <= 0:
                continue
            conf = int(sig.get("confidence") or 0)
            new_rows.append(
                {
                    "run_id": run_id,
                    "run_date": str(run_date)[:10],
                    "agent": str(agent_key),
                    "ticker": str(ticker),
                    "signal": sval,
                    "confidence": conf,
                    "entry_price": round(px, 4),
                    "eval_horizon_weeks": weeks,
                    "resolve_after_date": resolve_after,
                    "bucket": meta.get("bucket") or "default",
                    "forward_return_pct": None,
                    "directionally_correct": None,
                    "resolved_at": None,
                    "saved_at": now,
                }
            )
            seen.add(key)

    _append_ledger_rows(new_rows, path)
    if new_rows:
        logger.info("Appended agent horizon signals", count=len(new_rows), run_id=run_id)
    return len(new_rows)


def resolve_horizon_outcomes(
    *,
    as_of_date: str,
    current_prices: Dict[str, float],
    path: Path = LEDGER_PATH,
) -> int:
    """Resolve ledger rows whose horizon has elapsed using current_prices."""
    rows = _read_ledger(path)
    if not rows:
        return 0
    as_of = str(as_of_date)[:10]
    now = datetime.utcnow().isoformat() + "Z"
    resolved = 0
    for row in rows:
        if row.get("forward_return_pct") is not None:
            continue
        resolve_after = str(row.get("resolve_after_date") or "")[:10]
        if not resolve_after or as_of < resolve_after:
            continue
        ticker = row.get("ticker")
        p0 = float(row.get("entry_price") or 0)
        p1 = float((current_prices or {}).get(str(ticker)) or 0)
        if p0 <= 0 or p1 <= 0:
            continue
        raw_ret = (p1 - p0) / p0 * 100.0
        sval = str(row.get("signal") or "").lower()
        if sval == "bearish":
            decision_ret = -raw_ret
            correct = raw_ret < 0
        else:
            decision_ret = raw_ret
            correct = raw_ret > 0
        row["forward_return_pct"] = round(decision_ret, 4)
        row["raw_price_return_pct"] = round(raw_ret, 4)
        row["directionally_correct"] = bool(correct)
        row["resolved_at"] = now
        row["resolved_on_run_date"] = as_of
        resolved += 1
    if resolved:
        _write_ledger(rows, path)
        logger.info("Resolved agent horizon outcomes", count=resolved, as_of=as_of)
    return resolved


def build_horizon_scorecard(
    *,
    path: Path = LEDGER_PATH,
    output_path: Path = SCORECARD_PATH,
    horizons_path: Path = HORIZONS_PATH,
) -> Dict[str, Any]:
    """Aggregate resolved ledger rows into scorecard shape for weight updates."""
    rows = _read_ledger(path)
    correct: Dict[str, int] = defaultdict(int)
    total: Dict[str, int] = defaultdict(int)
    cw_ret: Dict[str, float] = defaultdict(float)
    hyp_sum: Dict[str, float] = defaultdict(float)
    hyp_n: Dict[str, int] = defaultdict(int)
    pending: Dict[str, int] = defaultdict(int)

    for row in rows:
        ak = str(row.get("agent") or "")
        if not ak:
            continue
        if row.get("forward_return_pct") is None:
            pending[ak] += 1
            continue
        sval = str(row.get("signal") or "").lower()
        if sval not in ("bullish", "bearish"):
            continue
        conf = int(row.get("confidence") or 0) / 100.0
        ret = float(row.get("forward_return_pct") or 0.0)
        total[ak] += 1
        if row.get("directionally_correct"):
            correct[ak] += 1
        cw_ret[ak] += ret * conf
        hyp_sum[ak] += ret
        hyp_n[ak] += 1

    agents_out: Dict[str, Any] = {}
    idx = _agent_index(_load_horizons_config(horizons_path))
    for ak in set(total.keys()) | set(pending.keys()):
        td = total[ak]
        meta = idx.get(ak) or {}
        entry: Dict[str, Any] = {
            "directional_accuracy": round((correct[ak] / td) if td else 0.0, 4),
            "directional_observations": td,
            "confidence_weighted_return_pct": round(cw_ret[ak], 4),
            "hypothetical_avg_return_pct": round(
                (hyp_sum[ak] / hyp_n[ak]) if hyp_n[ak] else 0.0, 4
            ),
            "pending_observations": int(pending.get(ak) or 0),
            "eval_horizon_weeks": int(
                meta.get("eval_horizon_weeks")
                or _load_horizons_config(horizons_path).get("default_weeks")
                or DEFAULT_WEEKS
            ),
            "bucket": meta.get("bucket") or "default",
            "min_observations_for_move": int(
                meta.get("min_observations_for_move") or DEFAULT_MIN_OBS
            ),
        }
        agents_out[ak] = entry

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source": "agent_horizon_ledger",
        "horizon_note": horizon_buckets_summary(horizons_path),
        "agents": agents_out,
        "resolved_rows": sum(total.values()),
        "pending_rows": sum(pending.values()),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    logger.info(
        "Wrote horizon scorecard",
        path=str(output_path),
        agents=len(agents_out),
        resolved=out["resolved_rows"],
        pending=out["pending_rows"],
    )
    return out


def load_horizon_scorecard(path: Path = SCORECARD_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def refresh_horizon_learning(
    *,
    run_id: str,
    run_date: str,
    agent_signals: Dict[str, Dict[str, Any]],
    risk_analysis: Dict[str, Any],
    current_prices: Dict[str, float],
    ticker_scope: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Resolve due rows → append this run → scorecard. Returns meta for learning_context."""
    resolved = resolve_horizon_outcomes(as_of_date=run_date, current_prices=current_prices)
    appended = append_signals_from_run(
        run_id=run_id,
        run_date=run_date,
        agent_signals=agent_signals,
        risk_analysis=risk_analysis,
        ticker_scope=ticker_scope,
    )
    sc = build_horizon_scorecard()
    return {
        "horizon_signals_appended": appended,
        "horizon_outcomes_resolved": resolved,
        "horizon_scorecard_agents": len(sc.get("agents") or {}),
        "horizon_resolved_rows": int(sc.get("resolved_rows") or 0),
        "horizon_pending_rows": int(sc.get("pending_rows") or 0),
        "horizon_note": sc.get("horizon_note") or horizon_buckets_summary(),
        "scorecard_source": "agent_horizon",
    }
