"""Append-only biotech thesis validation ledger (dual-arm A/B)."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config.settings import settings

DEFAULT_PATH = Path(getattr(settings, "biotech_thesis_ledger_path", "data/biotech/thesis_ledger.jsonl"))


def _ledger_path(path: Optional[Path] = None) -> Path:
    return path or DEFAULT_PATH


def _read_lines(path: Path) -> List[Dict[str, Any]]:
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


def _write_lines(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")


def _dedupe_key(row: Dict[str, Any]) -> tuple:
    return (
        str(row.get("ticker") or "").upper(),
        str(row.get("run_date") or "")[:10],
        str(row.get("arm") or ""),
        str(row.get("nct_id") or ""),
    )


def append_thesis_entry(entry: Dict[str, Any], path: Optional[Path] = None) -> str:
    """Append one thesis row; skip duplicate (ticker, run_date, arm, nct_id). Returns trade_id."""
    p = _ledger_path(path)
    rows = _read_lines(p)
    entry = dict(entry)
    trade_id = str(entry.get("trade_id") or uuid.uuid4().hex[:12])
    entry["trade_id"] = trade_id
    entry.setdefault("recorded_at", datetime.utcnow().isoformat() + "Z")
    key = _dedupe_key(entry)
    for r in rows:
        if _dedupe_key(r) == key and str(r.get("status") or "") not in ("closed", "expired"):
            return str(r.get("trade_id") or trade_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return trade_id


def open_entries(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    return [
        r
        for r in _read_lines(_ledger_path(path))
        if str(r.get("status") or "") in ("filled", "open", "submitted", "partial")
    ]


def update_entry(trade_id: str, updates: Dict[str, Any], path: Optional[Path] = None) -> bool:
    p = _ledger_path(path)
    rows = _read_lines(p)
    found = False
    for i, r in enumerate(rows):
        if str(r.get("trade_id")) == str(trade_id):
            rows[i] = {**r, **updates}
            found = True
            break
    if found:
        _write_lines(rows, p)
    return found


def closed_entries(weeks: int = 12, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    return [
        r
        for r in recent_entries(weeks=weeks, path=path)
        if str(r.get("status") or "") in ("closed", "expired")
    ]


def format_past_trades_context(
    weeks: int = 12,
    *,
    ticker: Optional[str] = None,
    phase: Optional[str] = None,
    limit: int = 15,
    path: Optional[Path] = None,
) -> str:
    """Compact resolved-trade history for LLM prompt (avoid overfitting)."""
    rows = closed_entries(weeks=weeks, path=path)
    if ticker:
        tu = ticker.strip().upper()
        same_t = [r for r in rows if str(r.get("ticker") or "").upper() == tu]
        if same_t:
            rows = same_t[-3:] + [r for r in rows if r not in same_t]
    if phase:
        ph = phase.strip().lower()
        phase_rows = [r for r in rows if ph in str(r.get("phase") or "").lower()]
        if phase_rows:
            rows = phase_rows[-3:] + [r for r in rows if r not in phase_rows]
    rows = sorted(
        rows,
        key=lambda r: str(r.get("resolved_at") or r.get("recorded_at") or ""),
        reverse=True,
    )[:limit]
    if not rows:
        return ""
    lines = [
        "PAST_RESOLVED_TRADES (paper book outcomes; use as calibration, do not overfit):",
    ]
    for r in rows:
        e = float(r.get("underlying_px_entry") or 0)
        d5 = float(r.get("underlying_px_5d") or 0)
        move = round((d5 - e) / e * 100.0, 1) if e > 0 and d5 > 0 else "n/a"
        lines.append(
            f"  {r.get('ticker')} [{r.get('arm')}] phase={r.get('phase', '')[:20]} "
            f"pnl_pct={r.get('pnl_pct_of_premium', 'n/a')} move_5d={move}% "
            f"clinical={r.get('clinical_outcome', 'n/a')} prob={r.get('llm_prob_low')}-{r.get('llm_prob_high')}"
        )
    return "\n".join(lines)


def candidate_history_score(ticker: str, phase: str = "", weeks: int = 24) -> float:
    """Soft ranking boost from historical phase/ticker PnL (-1 to +1)."""
    from src.biotech.policy_learning import phase_pnl_stats, ticker_pnl_stats

    score = 0.0
    ph_stats = phase_pnl_stats(weeks=weeks)
    if phase:
        for ph, st in ph_stats.items():
            if phase.lower() in ph.lower() and st["count"] >= 2:
                score += max(-0.5, min(0.5, st["avg_pnl_pct"] / 100.0))
                break
    t_stats = ticker_pnl_stats(weeks=weeks)
    st = t_stats.get(ticker.upper())
    if st and st["count"] >= 2:
        score += max(-0.5, min(0.5, st["avg_pnl_pct"] / 100.0))
    return score


def recent_entries(weeks: int = 12, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    rows = _read_lines(_ledger_path(path))
    if not weeks or not rows:
        return rows
    dates = sorted({str(r.get("run_date") or "")[:10] for r in rows if r.get("run_date")})
    if len(dates) <= weeks:
        return rows
    cutoff = dates[-weeks]
    return [r for r in rows if str(r.get("run_date") or "")[:10] >= cutoff]


def scorecard(weeks: int = 12, path: Optional[Path] = None) -> Dict[str, Any]:
    rows = recent_entries(weeks=weeks, path=path)
    closed = [r for r in rows if str(r.get("status") or "") in ("closed", "expired")]
    open_rows = [r for r in rows if r not in closed]

    def _arm_stats(arm: str) -> Dict[str, Any]:
        arm_closed = [r for r in closed if str(r.get("arm")) == arm]
        pnls = [
            float(r.get("pnl_pct_of_premium") or 0)
            for r in arm_closed
            if r.get("pnl_pct_of_premium") is not None
        ]
        wins = sum(1 for x in pnls if x > 0)
        return {
            "closed_count": len(arm_closed),
            "open_count": sum(1 for r in open_rows if str(r.get("arm")) == arm),
            "win_rate_pct": round(100.0 * wins / len(pnls), 1) if pnls else None,
            "avg_pnl_pct_of_premium": round(sum(pnls) / len(pnls), 2) if pnls else None,
            "total_premium_filled": round(
                sum(float(r.get("premium_filled_usd") or 0) for r in arm_closed), 2
            ),
        }

    mech = _arm_stats("mechanical")
    llm = _arm_stats("llm_gated")

    high_prob = [r for r in closed if float(r.get("llm_prob_high") or 0) > 0.6]
    low_prob = [r for r in closed if float(r.get("llm_prob_high") or 1) < 0.4]
    cal_high = _avg_move(high_prob)
    cal_low = _avg_move(low_prob)

    by_phase: Dict[str, int] = {}
    for r in closed:
        ph = str(r.get("phase") or "unknown")
        by_phase[ph] = by_phase.get(ph, 0) + 1

    last_closed = sorted(
        closed,
        key=lambda r: str(r.get("resolved_at") or r.get("recorded_at") or ""),
        reverse=True,
    )[:5]

    return {
        "weeks": weeks,
        "total_rows": len(rows),
        "closed_count": len(closed),
        "open_count": len(open_rows),
        "mechanical": mech,
        "llm_gated": llm,
        "by_phase": by_phase,
        "calibration": {
            "avg_move_pct_high_prob": cal_high,
            "avg_move_pct_low_prob": cal_low,
            "high_prob_closed_n": len(high_prob),
            "low_prob_closed_n": len(low_prob),
        },
        "last_closed": last_closed,
    }


def _avg_move(closed: List[Dict[str, Any]]) -> Optional[float]:
    moves = []
    for r in closed:
        e = float(r.get("underlying_px_entry") or 0)
        d5 = float(r.get("underlying_px_5d") or 0)
        if e > 0 and d5 > 0:
            moves.append((d5 - e) / e * 100.0)
    return round(sum(moves) / len(moves), 2) if moves else None


def format_scorecard_markdown(sc: Optional[Dict[str, Any]] = None, weeks: int = 12) -> str:
    sc = sc or scorecard(weeks=weeks)
    lines = [
        "BIOTECH THESIS SCORECARD",
        "=" * 70,
        f"Window: last {sc.get('weeks', weeks)} weeks | "
        f"closed={sc.get('closed_count', 0)} open={sc.get('open_count', 0)}",
    ]
    for arm in ("mechanical", "llm_gated"):
        a = sc.get(arm) or {}
        wr = a.get("win_rate_pct")
        avg = a.get("avg_pnl_pct_of_premium")
        lines.append(
            f"  {arm}: closed={a.get('closed_count', 0)} open={a.get('open_count', 0)} "
            f"win_rate={wr if wr is not None else 'n/a'}% "
            f"avg_pnl_pct_premium={avg if avg is not None else 'n/a'}"
        )
    cal = sc.get("calibration") or {}
    lines.append(
        f"  LLM calibration (closed): high_prob_avg_5d_move={cal.get('avg_move_pct_high_prob', 'n/a')}% "
        f"(n={cal.get('high_prob_closed_n', 0)}) | "
        f"low_prob={cal.get('avg_move_pct_low_prob', 'n/a')}% (n={cal.get('low_prob_closed_n', 0)})"
    )
    lines.append("  Recent closed:")
    for r in sc.get("last_closed") or []:
        lines.append(
            f"    {r.get('ticker')} [{r.get('arm')}] readout={r.get('readout_date_expected', 'n/a')} "
            f"pnl_pct={r.get('pnl_pct_of_premium', 'n/a')} clinical={r.get('clinical_outcome', 'n/a')}"
        )
    return "\n".join(lines)


def catalyst_fields_from_snapshot(
    snap: Any,
    *,
    forward_days: int,
    past_grace_days: int,
    min_phase: int = 0,
    readout_max_forward_days: Optional[int] = None,
) -> Dict[str, Any]:
    from src.biotech.readout_window import best_readout_date, primary_catalyst_trial

    trial = primary_catalyst_trial(
        snap,
        forward_days=forward_days,
        past_grace_days=past_grace_days,
        min_phase=min_phase,
        readout_max_forward_days=readout_max_forward_days,
    )
    if trial is None:
        return {}
    rd = best_readout_date(trial)
    return {
        "nct_id": trial.nct_id or "",
        "trial_title": (trial.title or "")[:200],
        "phase": trial.phase or "",
        "readout_date_expected": rd.isoformat() if rd else "",
        "trial_status": trial.status or "",
    }


def build_entry_from_execution(
    *,
    ticker: str,
    arm: str,
    run_id: str,
    run_date: str,
    snap: Any,
    analysis: Any,
    gates_ok: bool,
    gate_reasons: List[str],
    exec_result: Dict[str, Any],
    catalyst: Dict[str, Any],
) -> Dict[str, Any]:
    strat = exec_result.get("strategy") or {}
    status = str(exec_result.get("status") or "skipped")
    if status == "filled":
        ledger_status = "open"
    elif status in ("submitted", "partial"):
        ledger_status = status
    else:
        ledger_status = status

    prem_est = float(exec_result.get("premium_est_usd") or strat.get("estimated_premium_total") or 0)
    prem_fill = float(exec_result.get("premium_filled_usd") or exec_result.get("total_premium_filled") or 0)
    if prem_fill <= 0 and status == "filled":
        prem_fill = prem_est

    prob_lo = float(getattr(analysis, "prob_success_low", 0) or 0)
    prob_hi = float(getattr(analysis, "prob_success_high", 1) or 1)
    return {
        "ticker": ticker,
        "arm": arm,
        "run_id": run_id,
        "run_date": run_date,
        "entry_date": date.today().isoformat(),
        "nct_id": catalyst.get("nct_id", ""),
        "trial_title": catalyst.get("trial_title", ""),
        "phase": catalyst.get("phase", ""),
        "readout_date_expected": catalyst.get("readout_date_expected", ""),
        "expiry": strat.get("expiry", ""),
        "call_contract": strat.get("call_contract", ""),
        "put_contract": strat.get("put_contract", ""),
        "strike": float(strat.get("call_strike") or strat.get("strike") or 0),
        "strategy_type": strat.get("type", "long_straddle"),
        "premium_est_usd": round(prem_est, 2),
        "premium_filled_usd": round(prem_fill, 2),
        "status": ledger_status,
        "llm_prob_low": prob_lo,
        "llm_prob_high": prob_hi,
        "no_trade": bool(getattr(analysis, "no_trade", True)),
        "gates_ok": gates_ok,
        "gate_reasons": gate_reasons,
        "underlying_px_entry": float(getattr(snap, "last_price", 0) or 0),
        "execution": exec_result,
    }
