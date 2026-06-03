"""Decision attribution ledger: track actionable trades and forward outcomes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

LEDGER_PATH = Path("data/performance/decision_ledger.jsonl")


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


def parse_reason_class(reasoning: str) -> str:
    text = (reasoning or "").strip().lower()
    if text.startswith("cash rotation"):
        return "cash_rotation"
    if "conviction" in text:
        return "conviction"
    if text.startswith("rebalance"):
        return "rebalance"
    if "cc lot build" in text:
        return "cc_lot"
    return "other"


def _agent_attribution(
    ticker: str,
    agent_signals: Dict[str, Dict[str, Any]],
    action: str,
) -> tuple[List[str], List[str]]:
    """Top bullish/bearish agents for attribution."""
    bulls: List[tuple] = []
    bears: List[tuple] = []
    for ak, tsigs in (agent_signals or {}).items():
        sig = (tsigs or {}).get(ticker)
        if not isinstance(sig, dict):
            continue
        sval = sig.get("signal")
        conf = int(sig.get("confidence") or 0)
        if sval == "bullish":
            bulls.append((conf, ak))
        elif sval == "bearish":
            bears.append((conf, ak))
    bulls.sort(reverse=True)
    bears.sort(reverse=True)
    if action == "buy":
        return [a for _, a in bulls[:3]], [a for _, a in bears[:3]]
    if action == "sell":
        return [a for _, a in bears[:3]], [a for _, a in bulls[:3]]
    return [a for _, a in bulls[:3]], [a for _, a in bears[:3]]


def _was_executed(ticker: str, execution_results: Optional[Dict[str, Any]]) -> bool:
    if not execution_results or ticker == "error":
        return False
    res = execution_results.get(ticker)
    if not res:
        return False
    if isinstance(res, dict) and res.get("status") == "failed":
        return False
    return True


def append_decisions_from_run(
    *,
    run_id: str,
    run_date: str,
    regime: Optional[Dict[str, Any]],
    decisions: Dict[str, Any],
    risk_analysis: Dict[str, Any],
    agent_signals: Dict[str, Dict[str, Any]],
    execution_results: Optional[Dict[str, Any]] = None,
    path: Path = LEDGER_PATH,
) -> int:
    """Append one line per actionable buy/sell decision."""
    path.parent.mkdir(parents=True, exist_ok=True)
    regime_mode = (regime or {}).get("mode") if isinstance(regime, dict) else None
    count = 0
    with open(path, "a", encoding="utf-8") as f:
        for ticker, dec in (decisions or {}).items():
            if hasattr(dec, "model_dump"):
                dec = dec.model_dump()
            if not isinstance(dec, dict):
                continue
            action = dec.get("action")
            qty = int(dec.get("quantity") or 0)
            if action not in ("buy", "sell") or qty <= 0:
                continue
            risk = (risk_analysis or {}).get(ticker) or {}
            entry = float(risk.get("current_price") or 0)
            if entry <= 0:
                continue
            reasoning = str(dec.get("reasoning") or "")
            agents_for, agents_against = _agent_attribution(ticker, agent_signals, action)
            row = {
                "run_id": run_id,
                "run_date": run_date,
                "regime": regime_mode or "unknown",
                "ticker": ticker,
                "action": action,
                "qty": qty,
                "confidence": int(dec.get("confidence") or 0),
                "reasoning": reasoning[:500],
                "reason_class": parse_reason_class(reasoning),
                "entry_price": entry,
                "executed": _was_executed(ticker, execution_results),
                "agents_for": agents_for,
                "agents_against": agents_against,
                "saved_at": datetime.utcnow().isoformat() + "Z",
            }
            f.write(json.dumps(row, default=str) + "\n")
            count += 1
    if count:
        logger.info("Appended decision ledger entries", run_id=run_id, count=count)
    return count


def resolve_pending_outcomes(
    current_prices: Dict[str, float],
    run_date: str,
    path: Path = LEDGER_PATH,
) -> int:
    """Fill forward_return_pct for unresolved rows from the immediately prior run_date only."""
    rows = _read_lines(path)
    if not rows:
        return 0

    run_day = str(run_date)[:10]
    dates = sorted({str(r.get("run_date") or "")[:10] for r in rows if r.get("run_date")})
    prior_run_date = None
    for d in dates:
        if d < run_day:
            prior_run_date = d

    stale = 0
    if prior_run_date is None:
        return 0

    resolved = 0
    now = datetime.utcnow().isoformat() + "Z"
    for row in rows:
        if row.get("forward_return_pct") is not None:
            continue
        row_day = str(row.get("run_date") or "")[:10]
        if row_day != prior_run_date:
            if row_day < prior_run_date:
                stale += 1
            continue
        ticker = row.get("ticker")
        p0 = float(row.get("entry_price") or 0)
        p1 = float((current_prices or {}).get(ticker) or 0)
        if p0 <= 0 or p1 <= 0:
            continue
        raw_ret = (p1 - p0) / p0 * 100.0
        action = row.get("action")
        if action == "sell":
            decision_ret = -raw_ret
            directionally_correct = raw_ret < 0
        else:
            decision_ret = raw_ret
            directionally_correct = raw_ret > 0
        row["forward_return_pct"] = round(decision_ret, 4)
        row["raw_price_return_pct"] = round(raw_ret, 4)
        row["directionally_correct"] = directionally_correct
        row["resolved_at"] = now
        row["resolved_on_run_date"] = run_date
        resolved += 1
    if stale:
        logger.warning("Skipped stale unresolved decision rows", count=stale)
    if resolved:
        _write_lines(rows, path)
        logger.info("Resolved decision ledger outcomes", count=resolved, prior_run_date=prior_run_date)
    return resolved


def recent_entries(
    weeks: int = 12,
    path: Path = LEDGER_PATH,
) -> List[Dict[str, Any]]:
    rows = _read_lines(path)
    if not weeks:
        return rows
    if not rows:
        return []
    dates = sorted({str(r.get("run_date") or "")[:10] for r in rows if r.get("run_date")})
    if len(dates) <= weeks:
        return rows
    cutoff = dates[-weeks]
    return [r for r in rows if str(r.get("run_date") or "")[:10] >= cutoff]


def outcome_rows_for_email(limit: int = 8, path: Path = LEDGER_PATH) -> List[Dict[str, Any]]:
    """Most recent resolved decisions for email display."""
    rows = [r for r in _read_lines(path) if r.get("forward_return_pct") is not None]
    rows.sort(key=lambda r: r.get("resolved_at") or r.get("saved_at") or "", reverse=True)
    out = []
    for r in rows[:limit]:
        out.append(
            {
                "ticker": r.get("ticker"),
                "action": r.get("action"),
                "return_pct": r.get("forward_return_pct"),
                "reason_class": r.get("reason_class"),
            }
        )
    return out
