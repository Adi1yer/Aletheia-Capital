"""Persist Alpaca fill data linked to weekly runs for slippage and PnL attribution."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.performance.decision_ledger import parse_reason_class

logger = structlog.get_logger()

LEDGER_PATH = Path("data/performance/fill_ledger.jsonl")


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


def _slippage_bps(side: str, decision_price: float, fill_price: float) -> Optional[float]:
    if decision_price <= 0 or fill_price <= 0:
        return None
    side = (side or "").lower()
    if side == "buy":
        return round((fill_price - decision_price) / decision_price * 10000.0, 2)
    if side == "sell":
        return round((decision_price - fill_price) / decision_price * 10000.0, 2)
    return None


def append_fills_from_run(
    *,
    run_id: str,
    run_date: str,
    decisions: Dict[str, Any],
    risk_analysis: Dict[str, Any],
    execution_results: Optional[Dict[str, Any]],
    recent_orders: Optional[List[Dict[str, Any]]],
    path: Path = LEDGER_PATH,
) -> int:
    """Append fill rows from execution_results and/or recent Alpaca orders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = {str(r.get("order_id")) for r in _read_lines(path) if r.get("order_id")}
    count = 0
    now = datetime.utcnow().isoformat() + "Z"

    def _write_row(row: Dict[str, Any]) -> None:
        nonlocal count
        oid = str(row.get("order_id") or "")
        if oid and oid in existing_ids:
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        if oid:
            existing_ids.add(oid)
        count += 1

    exec_map = execution_results if isinstance(execution_results, dict) else {}
    for ticker, res in exec_map.items():
        if not isinstance(res, dict):
            continue
        if res.get("status") not in ("filled", "executed", "success") and not res.get("success"):
            continue
        dec = decisions.get(ticker)
        dec_dict = dec.model_dump() if hasattr(dec, "model_dump") else (dec or {})
        if not isinstance(dec_dict, dict):
            continue
        action = dec_dict.get("action", "hold")
        if action == "hold":
            continue
        side = "buy" if action in ("buy", "cover") else "sell"
        decision_price = float((risk_analysis.get(ticker) or {}).get("current_price") or 0)
        fill_price = float(res.get("filled_avg_price") or res.get("fill_price") or decision_price)
        qty = int(res.get("filled_qty") or res.get("qty") or dec_dict.get("quantity") or 0)
        oid = str(res.get("order_id") or res.get("id") or f"{run_id}-{ticker}")
        reasoning = str(dec_dict.get("reasoning") or "")
        _write_row(
            {
                "run_id": run_id,
                "run_date": run_date,
                "order_id": oid,
                "ticker": ticker,
                "side": side,
                "qty": qty,
                "filled_avg_price": fill_price,
                "decision_price": decision_price,
                "slippage_bps": _slippage_bps(side, decision_price, fill_price),
                "filled_at": res.get("filled_at"),
                "reason_class": parse_reason_class(reasoning),
                "executed": True,
                "saved_at": now,
            }
        )

    for order in recent_orders or []:
        if not isinstance(order, dict):
            continue
        sym = str(order.get("symbol") or "").strip()
        if not sym or len(sym) > 6:
            continue
        status = (order.get("status") or "").lower()
        if status not in ("filled", "partially_filled", "closed"):
            continue
        oid = str(order.get("id") or "")
        if not oid:
            continue
        side = (order.get("side") or "buy").lower()
        dec = decisions.get(sym)
        dec_dict = dec.model_dump() if hasattr(dec, "model_dump") else (dec or {})
        decision_price = float((risk_analysis.get(sym) or {}).get("current_price") or 0)
        fill_price = float(order.get("filled_avg_price") or decision_price)
        qty = int(order.get("filled_qty") or order.get("qty") or 0)
        reasoning = str((dec_dict or {}).get("reasoning") or "")
        _write_row(
            {
                "run_id": run_id,
                "run_date": run_date,
                "order_id": oid,
                "ticker": sym,
                "side": side,
                "qty": qty,
                "filled_avg_price": fill_price,
                "decision_price": decision_price,
                "slippage_bps": _slippage_bps(side, decision_price, fill_price),
                "filled_at": order.get("filled_at"),
                "reason_class": parse_reason_class(reasoning),
                "executed": True,
                "saved_at": now,
            }
        )

    if count:
        logger.info("Appended fill ledger rows", count=count, run_id=run_id)
    return count


def recent_fills(run_id: Optional[str] = None, weeks: int = 12, path: Path = LEDGER_PATH) -> List[Dict[str, Any]]:
    rows = _read_lines(path)
    if run_id:
        return [r for r in rows if r.get("run_id") == run_id]
    if not rows or not weeks:
        return rows
    dates = sorted({str(r.get("run_date") or "")[:10] for r in rows if r.get("run_date")})
    if len(dates) <= weeks:
        return rows
    cutoff = dates[-weeks]
    return [r for r in rows if str(r.get("run_date") or "")[:10] >= cutoff]


def slippage_by_reason_class(weeks: int = 12, path: Path = LEDGER_PATH) -> Dict[str, float]:
    rows = recent_fills(weeks=weeks, path=path)
    buckets: Dict[str, List[float]] = {}
    for r in rows:
        bps = r.get("slippage_bps")
        if bps is None:
            continue
        rc = str(r.get("reason_class") or "other")
        buckets.setdefault(rc, []).append(float(bps))
    return {k: round(sum(v) / len(v), 2) for k, v in buckets.items() if v}
