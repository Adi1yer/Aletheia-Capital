"""Options outcome ledger for CC/CSP learning and policy calibration."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

LEDGER_PATH = Path("data/performance/options_ledger.jsonl")


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


def append_cc_results(
    *,
    run_id: str,
    run_date: str,
    cc_results: List[Dict[str, Any]],
    regime: Optional[str] = None,
    path: Path = LEDGER_PATH,
) -> int:
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in cc_results or []:
            if not isinstance(r, dict):
                continue
            row = {
                "run_id": run_id,
                "run_date": run_date,
                "regime": regime,
                "underlying": r.get("underlying"),
                "strategy": "covered_call",
                "contract_symbol": r.get("contract_symbol"),
                "expiry": r.get("expiry"),
                "strike": float(r.get("strike") or 0),
                "contracts": int(r.get("contracts") or 0),
                "premium_usd": float(r.get("estimated_premium") or 0),
                "collateral_usd": float(r.get("strike") or 0) * 100 * int(r.get("contracts") or 0),
                "annualized_yield_pct": None,
                "status": r.get("status"),
                "cc_score": r.get("cc_score"),
                "outcome": None,
                "realized_pnl_usd": None,
                "effective_yield_pct": None,
                "underlying_price_at_write": r.get("underlying_price_at_write"),
                "saved_at": datetime.utcnow().isoformat() + "Z",
            }
            f.write(json.dumps(row, default=str) + "\n")
            count += 1
    return count


def append_csp_results(
    *,
    run_id: str,
    run_date: str,
    csp_results: List[Dict[str, Any]],
    regime: Optional[str] = None,
    path: Path = LEDGER_PATH,
) -> int:
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in csp_results or []:
            if not isinstance(r, dict):
                continue
            premium = float(r.get("estimated_premium") or r.get("premium") or 0)
            strike = float(r.get("strike") or 0)
            collateral = float(r.get("collateral") or strike) * 100
            days = int(r.get("days_to_expiry") or 30)
            ann_yield = (premium / collateral * (365.0 / max(1, days)) * 100.0) if collateral > 0 else 0
            row = {
                "run_id": run_id,
                "run_date": run_date,
                "regime": regime,
                "underlying": r.get("underlying") or r.get("ticker"),
                "strategy": "csp",
                "contract_symbol": r.get("contract_symbol") or r.get("symbol"),
                "expiry": r.get("expiry"),
                "strike": strike,
                "contracts": int(r.get("contracts") or 1),
                "premium_usd": premium,
                "collateral_usd": collateral,
                "annualized_yield_pct": round(ann_yield, 4),
                "status": r.get("status"),
                "csp_score": r.get("csp_score"),
                "outcome": None,
                "realized_pnl_usd": None,
                "effective_yield_pct": None,
                "saved_at": datetime.utcnow().isoformat() + "Z",
            }
            f.write(json.dumps(row, default=str) + "\n")
            count += 1
    return count


def resolve_option_outcomes(
    run_date: str,
    current_prices: Optional[Dict[str, float]] = None,
    closed_option_symbols: Optional[List[str]] = None,
    path: Path = LEDGER_PATH,
) -> int:
    """
    Resolve unresolved option rows when legs closed or past expiry.

    Uses closed OCC symbols from daily snapshot lifecycle when broker unavailable.
    """
    rows = _read_lines(path)
    if not rows:
        return 0
    closed = set(closed_option_symbols or [])
    now = datetime.utcnow().isoformat() + "Z"
    resolved = 0
    for row in rows:
        if row.get("outcome") is not None:
            continue
        if row.get("status") != "executed":
            continue
        sym = str(row.get("contract_symbol") or "")
        underlying = str(row.get("underlying") or "")
        expiry = str(row.get("expiry") or "")[:10]
        if expiry and expiry <= str(run_date)[:10]:
            px = float((current_prices or {}).get(underlying) or 0)
            strike = float(row.get("strike") or 0)
            premium = float(row.get("premium_usd") or 0)
            strategy = row.get("strategy")
            if strategy == "covered_call" and px > strike > 0:
                row["outcome"] = "called_away"
                row["realized_pnl_usd"] = round(premium + (strike - px) * 100 * int(row.get("contracts") or 1), 2)
            elif strategy == "csp" and px < strike > 0:
                row["outcome"] = "assigned"
                row["realized_pnl_usd"] = round(premium, 2)
            else:
                row["outcome"] = "expired_otm"
                row["realized_pnl_usd"] = round(premium, 2)
            row["effective_yield_pct"] = row.get("annualized_yield_pct")
            row["resolved_at"] = now
            resolved += 1
        elif sym and sym in closed:
            row["outcome"] = "closed_early"
            row["realized_pnl_usd"] = round(float(row.get("premium_usd") or 0), 2)
            row["resolved_at"] = now
            resolved += 1
    if resolved:
        _write_lines(rows, path)
        logger.info("Resolved option ledger outcomes", count=resolved)
    return resolved


def outcome_summary(weeks: int = 8, path: Path = LEDGER_PATH) -> Dict[str, Any]:
    rows = recent_entries(weeks=weeks, path=path)
    resolved = [r for r in rows if r.get("outcome")]
    counts: Dict[str, int] = {}
    for r in resolved:
        o = str(r.get("outcome") or "unknown")
        counts[o] = counts.get(o, 0) + 1
    return {
        "weeks": weeks,
        "resolved_count": len(resolved),
        "outcome_counts": counts,
    }


def recent_entries(weeks: int = 12, path: Path = LEDGER_PATH) -> List[Dict[str, Any]]:
    rows = _read_lines(path)
    if not rows or not weeks:
        return rows
    dates = sorted({str(r.get("run_date") or "")[:10] for r in rows if r.get("run_date")})
    if len(dates) <= weeks:
        return rows
    cutoff = dates[-weeks]
    return [r for r in rows if str(r.get("run_date") or "")[:10] >= cutoff]


def recent_summary(weeks: int = 8, path: Path = LEDGER_PATH) -> Dict[str, Any]:
    """Rolling CSP/CC stats for email learning section."""
    rows = recent_entries(weeks=weeks, path=path)
    csp_exec = [r for r in rows if r.get("strategy") == "csp" and r.get("status") == "executed"]
    cc_exec = [
        r for r in rows if r.get("strategy") == "covered_call" and r.get("status") == "executed"
    ]
    csp_premiums = [float(r.get("premium_usd") or 0) for r in csp_exec]
    cc_premiums = [float(r.get("premium_usd") or 0) for r in cc_exec]
    floor = 75.0
    try:
        from src.performance.policy_calibration import load_policy

        floor = float((load_policy() or {}).get("min_csp_premium_usd") or 75.0)
    except Exception:
        pass
    sub_floor = [p for p in csp_premiums if p < floor]
    out = outcome_summary(weeks=weeks, path=path)
    return {
        "weeks": weeks,
        "csp_executed": len(csp_exec),
        "cc_executed": len(cc_exec),
        "csp_avg_premium_usd": round(sum(csp_premiums) / len(csp_premiums), 2) if csp_premiums else 0.0,
        "cc_avg_premium_usd": round(sum(cc_premiums) / len(cc_premiums), 2) if cc_premiums else 0.0,
        "csp_sub_floor_count": len(sub_floor),
        "min_csp_premium_floor": floor,
        "resolved_count": out.get("resolved_count", 0),
        "outcome_counts": out.get("outcome_counts") or {},
    }
