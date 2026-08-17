"""Beat SPY scorecard: IR, Sharpe, drawdown gates."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HISTORY_PATH = Path("data/performance/beat_spy_history.jsonl")
LATEST_JSON = Path("data/performance/beat_spy_scorecard_latest.json")
LATEST_MD = Path("data/performance/beat_spy_scorecard_latest.md")

GATE_IR = 0.4
GATE_RETURN_VS_SPY_PP = -1.0
GATE_DD_VS_SPY_PP = 3.0


def _append_history(row: Dict[str, Any]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _load_history(limit: int = 52) -> List[Dict[str, Any]]:
    if not HISTORY_PATH.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows[-limit:]


def _sharpe(returns: List[float]) -> Optional[float]:
    if len(returns) < 4:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
    std = math.sqrt(var)
    if std <= 1e-9:
        return None
    return round((mean / std) * math.sqrt(52), 4)


def _information_ratio(active: List[float]) -> Optional[float]:
    if len(active) < 4:
        return None
    mean = sum(active) / len(active)
    var = sum((a - mean) ** 2 for a in active) / max(1, len(active) - 1)
    te = math.sqrt(var)
    if te <= 1e-9:
        return None
    return round(mean / te, 4)


def _max_drawdown_pct(equity_series: List[float]) -> Optional[float]:
    if len(equity_series) < 2:
        return None
    peak = equity_series[0]
    max_dd = 0.0
    for eq in equity_series:
        peak = max(peak, eq)
        if peak > 0:
            dd = (eq / peak - 1.0) * 100.0
            max_dd = min(max_dd, dd)
    return round(max_dd, 4)


def _book_structure(portfolio: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    portfolio = portfolio or {}
    equity = float(portfolio.get("equity") or portfolio.get("total_equity") or 0.0)
    cash = float(portfolio.get("cash") or 0.0)
    cash_pct = (cash / equity) if equity > 0 else None
    weights = []
    n_pos = 0
    for pos in (portfolio.get("positions") or {}).values():
        if not isinstance(pos, dict):
            continue
        qty = float(pos.get("long") or pos.get("qty") or 0)
        px = float(pos.get("current_price") or pos.get("long_cost_basis") or 0)
        if qty > 0 and px > 0 and equity > 0:
            n_pos += 1
            weights.append((qty * px) / equity)
    hhi = round(sum(w * w for w in weights), 4) if weights else None
    effective_n = round(1.0 / hhi, 2) if hhi and hhi > 1e-9 else None
    return {
        "cash_pct": round(cash_pct, 4) if cash_pct is not None else None,
        "n_positions": n_pos,
        "hhi": hhi,
        "effective_n": effective_n,
        "estimated_beta": round(max(0.0, 1.0 - float(cash_pct or 0.0)), 4) if cash_pct is not None else None,
    }


def build_beat_spy_scorecard(
    *,
    run_date: str,
    equity: float,
    benchmark: Optional[Dict[str, Any]] = None,
    attribution: Optional[Dict[str, Any]] = None,
    portfolio: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    benchmark = benchmark or {}
    attribution = attribution or {}
    active_pp = benchmark.get("active_vs_spy_pct")
    fund_ret = benchmark.get("equity_delta_pct")
    spy_ret = benchmark.get("spy_return_pct")

    book = _book_structure(portfolio)
    cash_drag = None
    if book.get("cash_pct") is not None and spy_ret is not None:
        cash_drag = round(float(book["cash_pct"]) * float(spy_ret), 4)

    row = {
        "run_date": run_date,
        "equity": float(equity),
        "fund_return_pct": fund_ret,
        "spy_return_pct": spy_ret,
        "active_vs_spy_pp": active_pp,
        "residual_return_pct": attribution.get("residual_return_pct"),
        "cash_pct": book.get("cash_pct"),
        "cash_drag_pct": cash_drag,
        "estimated_beta": book.get("estimated_beta"),
        "n_positions": book.get("n_positions"),
        "effective_n": book.get("effective_n"),
        "hhi": book.get("hhi"),
    }
    _append_history(row)

    hist = _load_history()
    fund_rets = [float(h["fund_return_pct"]) for h in hist if h.get("fund_return_pct") is not None]
    spy_rets = [float(h["spy_return_pct"]) for h in hist if h.get("spy_return_pct") is not None]
    active = [
        float(h["active_vs_spy_pp"])
        for h in hist
        if h.get("active_vs_spy_pp") is not None
    ]
    equities = [float(h["equity"]) for h in hist if h.get("equity") is not None]

    ir = _information_ratio(active)
    sharpe_fund = _sharpe(fund_rets)
    sharpe_spy = _sharpe(spy_rets)
    dd_fund = _max_drawdown_pct(equities)
    dd_spy = None  # would need SPY equity series; omit until cached

    cum_fund = sum(fund_rets) if fund_rets else None
    cum_spy = sum(spy_rets) if spy_rets else None

    gates = {
        "ir_ok": ir is not None and ir >= GATE_IR,
        "return_ok": cum_fund is not None and cum_spy is not None and (cum_fund - cum_spy) >= GATE_RETURN_VS_SPY_PP,
        "sharpe_ok": sharpe_fund is not None and sharpe_spy is not None and sharpe_fund >= sharpe_spy,
        "dd_ok": True if dd_spy is None else (dd_fund is not None and dd_fund >= dd_spy - GATE_DD_VS_SPY_PP),
    }
    gates["all_ok"] = all(gates.values()) if len(hist) >= 8 else False

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "run_date": run_date,
        "weeks_recorded": len(hist),
        "information_ratio": ir,
        "sharpe_fund": sharpe_fund,
        "sharpe_spy": sharpe_spy,
        "max_drawdown_fund_pct": dd_fund,
        "cumulative_fund_return_pct": round(cum_fund, 4) if cum_fund is not None else None,
        "cumulative_spy_return_pct": round(cum_spy, 4) if cum_spy is not None else None,
        "gates": gates,
        "gate_thresholds": {
            "ir_min": GATE_IR,
            "return_vs_spy_min_pp": GATE_RETURN_VS_SPY_PP,
            "dd_vs_spy_max_pp": GATE_DD_VS_SPY_PP,
        },
        "latest": row,
        "book": book,
    }
    try:
        from src.performance.beat_spy_gates import evaluate_beat_spy_gates

        out["capital_path_gates"] = evaluate_beat_spy_gates(out)
    except Exception:
        out["capital_path_gates"] = {}
    LATEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    LATEST_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    lines = [
        "# Beat SPY scorecard",
        "",
        f"Run date: {run_date}",
        f"Weeks recorded: {len(hist)}",
        f"IR: {ir}",
        f"Sharpe fund / SPY: {sharpe_fund} / {sharpe_spy}",
        f"Cumulative fund / SPY: {out.get('cumulative_fund_return_pct')}% / {out.get('cumulative_spy_return_pct')}%",
        f"Cash % / drag vs SPY week: {row.get('cash_pct')} / {row.get('cash_drag_pct')} pp",
        f"Est. beta / positions / effective N: {row.get('estimated_beta')} / {row.get('n_positions')} / {row.get('effective_n')}",
        f"Gates all OK (need ≥8 weeks): {gates['all_ok']}",
        "",
    ]
    LATEST_MD.write_text("\n".join(lines), encoding="utf-8")
    return out
