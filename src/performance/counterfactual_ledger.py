"""Counterfactual ledger: high-conviction holds/skips with forward outcomes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

LEDGER_PATH = Path("data/performance/counterfactual_ledger.jsonl")


def _read_lines(path: Path = LEDGER_PATH) -> List[Dict[str, Any]]:
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


def _write_lines(rows: List[Dict[str, Any]], path: Path = LEDGER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")


def append_counterfactuals_from_run(
    *,
    run_id: str,
    run_date: str,
    decisions: Dict[str, Any],
    aggregated_signals: Dict[str, Dict[str, Any]],
    risk_analysis: Dict[str, Any],
    min_buy_confidence: int = 60,
    min_sell_confidence: int = 60,
    top_n: int = 20,
    path: Path = LEDGER_PATH,
) -> int:
    """Record high-conviction names that were not traded."""
    candidates: List[tuple] = []
    for ticker, agg in (aggregated_signals or {}).items():
        dec = decisions.get(ticker)
        dec_dict = dec.model_dump() if hasattr(dec, "model_dump") else (dec or {})
        action = (dec_dict or {}).get("action", "hold")
        if action != "hold":
            continue
        if not isinstance(agg, dict):
            continue
        sig = agg.get("signal")
        conf = int(agg.get("confidence") or 0)
        would = None
        if sig == "bullish" and conf >= min_buy_confidence:
            would = "buy"
        elif sig == "bearish" and conf >= min_sell_confidence:
            would = "sell"
        if not would:
            continue
        price = float((risk_analysis.get(ticker) or {}).get("current_price") or 0)
        if price <= 0:
            continue
        candidates.append((conf, ticker, sig, would, price))

    candidates.sort(key=lambda x: x[0], reverse=True)
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().isoformat() + "Z"
    with open(path, "a", encoding="utf-8") as f:
        for conf, ticker, sig, would, price in candidates[:top_n]:
            row = {
                "run_id": run_id,
                "run_date": run_date,
                "ticker": ticker,
                "signal": sig,
                "confidence": conf,
                "would_be_action": would,
                "decision_price": price,
                "forward_return_pct": None,
                "saved_at": now,
            }
            f.write(json.dumps(row, default=str) + "\n")
            count += 1
    return count


def resolve_pending_outcomes(
    current_prices: Dict[str, float],
    run_date: str,
    path: Path = LEDGER_PATH,
) -> int:
    """Resolve prior-week counterfactual rows (same time guard as decision ledger)."""
    rows = _read_lines(path)
    if not rows:
        return 0
    run_day = str(run_date)[:10]
    dates = sorted({str(r.get("run_date") or "")[:10] for r in rows if r.get("run_date")})
    prior_run_date = None
    for d in dates:
        if d < run_day:
            prior_run_date = d
    if prior_run_date is None:
        return 0

    resolved = 0
    now = datetime.utcnow().isoformat() + "Z"
    for row in rows:
        if row.get("forward_return_pct") is not None:
            continue
        if str(row.get("run_date") or "")[:10] != prior_run_date:
            continue
        ticker = row.get("ticker")
        p0 = float(row.get("decision_price") or 0)
        p1 = float((current_prices or {}).get(ticker) or 0)
        if p0 <= 0 or p1 <= 0:
            continue
        raw_ret = (p1 - p0) / p0 * 100.0
        would = row.get("would_be_action")
        if would == "sell":
            decision_ret = -raw_ret
        else:
            decision_ret = raw_ret
        row["forward_return_pct"] = round(decision_ret, 4)
        row["resolved_at"] = now
        resolved += 1
    if resolved:
        _write_lines(rows, path)
    return resolved


def recent_for_email(limit: int = 5, path: Path = LEDGER_PATH) -> List[Dict[str, Any]]:
    rows = [r for r in _read_lines(path) if r.get("forward_return_pct") is not None]
    rows.sort(key=lambda r: abs(float(r.get("forward_return_pct") or 0)), reverse=True)
    return rows[:limit]


def recent_resolved(weeks: int = 12, path: Path = LEDGER_PATH) -> List[Dict[str, Any]]:
    rows = [r for r in _read_lines(path) if r.get("forward_return_pct") is not None]
    if not weeks:
        return rows
    dates = sorted({str(r.get("run_date") or "")[:10] for r in rows if r.get("run_date")})
    if len(dates) <= weeks:
        return rows
    cutoff = dates[-weeks]
    return [r for r in rows if str(r.get("run_date") or "")[:10] >= cutoff]
