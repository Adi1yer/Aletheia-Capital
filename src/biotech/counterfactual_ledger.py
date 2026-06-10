"""Counterfactual ledger: LLM no_trade vs mechanical-eligible catalysts."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

LEDGER_PATH = Path("data/biotech/counterfactual_ledger.jsonl")


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


def append_counterfactual(
    *,
    run_id: str,
    run_date: str,
    ticker: str,
    catalyst: Dict[str, Any],
    analysis: Any,
    gate_reasons: List[str],
    premium_est_usd: float = 0.0,
    path: Path = LEDGER_PATH,
) -> None:
    """Log when LLM/gates blocked trade but mechanical arm would have been eligible."""
    key = (ticker.upper(), run_date[:10])
    for r in _read_lines(path):
        if (
            str(r.get("ticker") or "").upper(),
            str(r.get("run_date") or "")[:10],
        ) == key:
            return
    row = {
        "run_id": run_id,
        "run_date": run_date,
        "ticker": ticker.upper(),
        "nct_id": catalyst.get("nct_id", ""),
        "readout_date_expected": catalyst.get("readout_date_expected", ""),
        "phase": catalyst.get("phase", ""),
        "no_trade": bool(getattr(analysis, "no_trade", True)),
        "llm_prob_low": float(getattr(analysis, "prob_success_low", 0) or 0),
        "llm_prob_high": float(getattr(analysis, "prob_success_high", 1) or 1),
        "gate_reasons": gate_reasons,
        "premium_est_usd": round(premium_est_usd, 2),
        "underlying_px_entry": None,
        "underlying_px_5d": None,
        "hypothetical_pnl_pct": None,
        "resolved": False,
        "saved_at": datetime.utcnow().isoformat() + "Z",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def resolve_counterfactuals(
    *,
    today: Optional[date] = None,
    min_age_days: int = 5,
    path: Path = LEDGER_PATH,
) -> int:
    """Fill 5d underlying move for rows old enough."""
    today = today or date.today()
    rows = _read_lines(path)
    updated = 0
    for i, r in enumerate(rows):
        if r.get("resolved"):
            continue
        saved = str(r.get("saved_at") or r.get("run_date") or "")[:10]
        try:
            sd = date.fromisoformat(saved[:10])
        except ValueError:
            continue
        if (today - sd).days < min_age_days:
            continue
        ticker = str(r.get("ticker") or "")
        if not ticker:
            continue
        from src.biotech.outcome_resolver import _price_on_date

        entry_d = sd
        px0 = _price_on_date(ticker, entry_d)
        px5 = _price_on_date(ticker, entry_d + timedelta(days=5))
        if px0 <= 0:
            continue
        move_pct = (px5 - px0) / px0 * 100.0 if px5 > 0 else 0.0
        prem = float(r.get("premium_est_usd") or 0)
        # Rough straddle proxy: absolute move % vs premium % of 100-share notional
        hypo_pnl = None
        if prem > 0 and px0 > 0:
            notional = px0 * 100
            hypo_pnl = round(abs(move_pct) / 100.0 * notional - prem, 2)
        rows[i] = {
            **r,
            "underlying_px_entry": round(px0, 2),
            "underlying_px_5d": round(px5, 2),
            "move_5d_pct": round(move_pct, 2),
            "hypothetical_pnl_pct": hypo_pnl,
            "resolved": True,
            "resolved_at": datetime.utcnow().isoformat() + "Z",
        }
        updated += 1
    if updated:
        _write_lines(rows, path)
    return updated


def recent_for_email(weeks: int = 8, limit: int = 5, path: Path = LEDGER_PATH) -> List[Dict[str, Any]]:
    rows = _read_lines(path)
    dates = sorted({str(r.get("run_date") or "")[:10] for r in rows if r.get("run_date")})
    if len(dates) > weeks:
        cutoff = dates[-weeks]
        rows = [r for r in rows if str(r.get("run_date") or "")[:10] >= cutoff]
    resolved = [r for r in rows if r.get("resolved")]
    return sorted(
        resolved,
        key=lambda r: str(r.get("resolved_at") or ""),
        reverse=True,
    )[:limit]
