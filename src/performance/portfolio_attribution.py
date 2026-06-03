"""Weekly portfolio PnL attribution: equity delta, trading vs carry, agent dollar scores."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

LEDGER_PATH = Path("data/performance/portfolio_attribution.jsonl")


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


def _equity_from_portfolio(port: Dict[str, Any], risk: Dict[str, Any]) -> float:
    cash = float(port.get("cash") or 0)
    eq = cash
    for sym, pos in (port.get("positions") or {}).items():
        if not isinstance(pos, dict):
            continue
        long_q = int(pos.get("long") or 0)
        short_q = int(pos.get("short") or 0)
        px = float((risk.get(sym) or {}).get("current_price") or 0)
        if px <= 0:
            px = float(pos.get("long_cost_basis") or pos.get("short_cost_basis") or 0)
        eq += long_q * px - short_q * px
    return round(eq, 2)


def _trading_pnl_from_fills(fills: List[Dict[str, Any]]) -> float:
    total = 0.0
    for f in fills:
        qty = int(f.get("qty") or 0)
        dp = float(f.get("decision_price") or 0)
        fp = float(f.get("filled_avg_price") or dp)
        side = (f.get("side") or "").lower()
        if qty <= 0 or dp <= 0:
            continue
        if side == "buy":
            total -= qty * fp
        elif side == "sell":
            total += qty * fp
    return round(total, 2)


def _top_contributors(
    port_before: Dict[str, Any],
    port_after: Dict[str, Any],
    risk_before: Dict[str, Any],
    risk_after: Dict[str, Any],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    symbols = set((port_before.get("positions") or {})) | set((port_after.get("positions") or {}))
    rows: List[Dict[str, Any]] = []
    for sym in symbols:
        p0 = (port_before.get("positions") or {}).get(sym) or {}
        p1 = (port_after.get("positions") or {}).get(sym) or {}
        q0 = int(p0.get("long") or 0) - int(p0.get("short") or 0)
        q1 = int(p1.get("long") or 0) - int(p1.get("short") or 0)
        px0 = float((risk_before.get(sym) or {}).get("current_price") or 0)
        px1 = float((risk_after.get(sym) or {}).get("current_price") or 0)
        if px0 <= 0 or px1 <= 0:
            continue
        avg_q = (abs(q0) + abs(q1)) / 2.0
        contrib = avg_q * (px1 - px0)
        if abs(contrib) < 0.01:
            continue
        rows.append({"ticker": sym, "contrib_usd": round(contrib, 2), "price_change_pct": round((px1 - px0) / px0 * 100, 2)})
    rows.sort(key=lambda x: abs(x["contrib_usd"]), reverse=True)
    return rows[:limit]


def append_weekly_attribution(
    *,
    run_id: str,
    run_date: str,
    portfolio_before: Dict[str, Any],
    portfolio_after: Dict[str, Any],
    risk_analysis: Dict[str, Any],
    fills: Optional[List[Dict[str, Any]]] = None,
    options_premium_usd: float = 0.0,
    path: Path = LEDGER_PATH,
) -> Dict[str, Any]:
    """Append one weekly attribution row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    eq_before = float(portfolio_before.get("equity") or _equity_from_portfolio(portfolio_before, risk_analysis))
    eq_after = float(portfolio_after.get("equity") or _equity_from_portfolio(portfolio_after, risk_analysis))
    delta_usd = round(eq_after - eq_before, 2)
    delta_pct = round(delta_usd / eq_before * 100, 4) if eq_before > 0 else 0.0
    fills = fills or []
    trading_pnl = _trading_pnl_from_fills(fills)
    carry_pnl = round(delta_usd - trading_pnl, 2)
    row = {
        "run_id": run_id,
        "run_date": run_date,
        "equity_before": eq_before,
        "equity_after": eq_after,
        "equity_delta_usd": delta_usd,
        "equity_delta_pct": delta_pct,
        "trading_pnl_usd": trading_pnl,
        "carry_pnl_usd": carry_pnl,
        "options_premium_usd": round(float(options_premium_usd), 2),
        "cash_drag_usd": None,
        "top_contributors": _top_contributors(portfolio_before, portfolio_after, risk_analysis, risk_analysis),
        "saved_at": datetime.utcnow().isoformat() + "Z",
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    logger.info("Appended portfolio attribution", run_id=run_id, delta_usd=delta_usd)
    return row


def recent_rows(weeks: int = 12, path: Path = LEDGER_PATH) -> List[Dict[str, Any]]:
    rows = _read_lines(path)
    if not rows or not weeks:
        return rows
    dates = sorted({str(r.get("run_date") or "")[:10] for r in rows if r.get("run_date")})
    if len(dates) <= weeks:
        return rows
    cutoff = dates[-weeks]
    return [r for r in rows if str(r.get("run_date") or "")[:10] >= cutoff]


def attribution_week_count(path: Path = LEDGER_PATH) -> int:
    return len({str(r.get("run_date") or "")[:10] for r in _read_lines(path) if r.get("run_date")})


def agent_dollar_metrics(run_id: str, weeks: int = 12) -> Dict[str, float]:
    """Approximate agent dollar contribution from decision ledger agents_for + fill notional."""
    from src.performance.decision_ledger import LEDGER_PATH as DEC_PATH
    from src.performance.fill_ledger import recent_fills

    fills = {f.get("ticker"): f for f in recent_fills(run_id=run_id)}
    if not fills:
        fills = {f.get("ticker"): f for f in recent_fills(weeks=weeks)}

    dec_rows = []
    if DEC_PATH.is_file():
        with open(DEC_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    dec_rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    dec_rows = [r for r in dec_rows if r.get("run_id") == run_id and r.get("executed")]
    agent_pnl: Dict[str, float] = {}
    for d in dec_rows:
        ticker = d.get("ticker")
        fill = fills.get(ticker) or {}
        qty = int(fill.get("qty") or d.get("qty") or 0)
        dp = float(fill.get("decision_price") or d.get("entry_price") or 0)
        fp = float(fill.get("filled_avg_price") or dp)
        if qty <= 0:
            continue
        notional = abs(qty * (fp - dp)) if fp and dp else qty * dp * 0.001
        for agent in d.get("agents_for") or []:
            agent_pnl[agent] = agent_pnl.get(agent, 0.0) + notional / max(len(d.get("agents_for") or []), 1)
    return {k: round(v, 4) for k, v in agent_pnl.items()}


def latest_summary(path: Path = LEDGER_PATH) -> Optional[Dict[str, Any]]:
    rows = _read_lines(path)
    return rows[-1] if rows else None
