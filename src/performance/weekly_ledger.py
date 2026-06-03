"""Compact weekly run ledger for learning when full scan_cache is unavailable."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

LEDGER_PATH = Path("data/performance/weekly_ledger.jsonl")


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


def append_ledger_entry(
    *,
    run_id: str,
    run_date: str,
    active_agents: List[str],
    tickers: Dict[str, Dict[str, Any]],
    position_opens: Optional[Dict[str, str]] = None,
    regime: Optional[str] = None,
    path: Path = LEDGER_PATH,
) -> None:
    """Append one compact row (~KB) for scorecard fallback."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "run_id": run_id,
        "run_date": run_date,
        "regime": regime or "unknown",
        "active_agents": active_agents,
        "tickers": tickers,
        "position_opens": position_opens or {},
        "saved_at": datetime.utcnow().isoformat() + "Z",
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    logger.info("Appended weekly ledger entry", run_id=run_id, ticker_count=len(tickers))


def build_tickers_from_run(
    portfolio_before: Dict[str, Any],
    decisions: Dict[str, Any],
    risk_analysis: Dict[str, Any],
    agent_signals: Dict[str, Dict[str, Any]],
    aggregated_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build compact ticker map for held, traded, and high-conviction names."""
    tickers: Dict[str, Dict[str, Any]] = {}
    symbols: set = set()

    for sym, pos in (portfolio_before.get("positions") or {}).items():
        if isinstance(pos, dict) and int(pos.get("long") or 0) > 0:
            symbols.add(sym)

    for sym, dec in (decisions or {}).items():
        if not isinstance(dec, dict):
            continue
        if dec.get("action") in ("buy", "sell", "short", "cover") and int(dec.get("quantity") or 0) > 0:
            symbols.add(sym)

    for sym in symbols:
        risk = (risk_analysis or {}).get(sym) or {}
        price = float(risk.get("current_price") or 0)
        if price <= 0:
            continue
        agg = (aggregated_by_ticker or {}).get(sym) or {}
        per_agent: Dict[str, Any] = {}
        for ak, tsigs in (agent_signals or {}).items():
            sig = (tsigs or {}).get(sym)
            if isinstance(sig, dict):
                per_agent[ak] = {
                    "signal": sig.get("signal"),
                    "confidence": sig.get("confidence"),
                }
        tickers[sym] = {
            "price": price,
            "signal": agg.get("signal"),
            "confidence": agg.get("confidence"),
            "agent_signals": per_agent,
        }
    return tickers


def _accumulate_signal(
    correct: Dict[str, int],
    total_dir: Dict[str, int],
    cw_ret_sum: Dict[str, float],
    agent_key: str,
    sig_val: str,
    conf: int,
    ret_pct: float,
) -> None:
    if sig_val not in ("bullish", "bearish"):
        return
    total_dir[agent_key] += 1
    hit = (sig_val == "bullish" and ret_pct > 0) or (sig_val == "bearish" and ret_pct < 0)
    if hit:
        correct[agent_key] += 1
    w = conf / 100.0
    contrib = ret_pct if sig_val == "bullish" else -ret_pct
    cw_ret_sum[agent_key] += contrib * w


def _agents_from_stats(
    correct: Dict[str, int],
    total_dir: Dict[str, int],
    cw_ret_sum: Dict[str, float],
    min_obs: int = 0,
) -> Dict[str, Any]:
    agents_out: Dict[str, Any] = {}
    for agent_key, td in total_dir.items():
        if td <= 0 or td < min_obs:
            continue
        acc = correct[agent_key] / td
        agents_out[agent_key] = {
            "directional_accuracy": round(acc, 4),
            "directional_observations": td,
            "confidence_weighted_return_pct": round(cw_ret_sum[agent_key], 4),
            "hypothetical_avg_return_pct": round(cw_ret_sum[agent_key] / td, 4),
            "sector_directional_accuracy": {},
        }
    return agents_out


def evaluate_ledger_scorecard(
    path: Optional[Path] = None,
    max_pairs: int = 20,
    min_regime_obs: int = 6,
) -> Dict[str, Any]:
    """Build agent scorecard from consecutive ledger rows (same shape as agent_evaluator)."""
    rows = _read_lines(path or LEDGER_PATH)
    if len(rows) < 2:
        return {}

    rows = sorted(rows, key=lambda r: r.get("run_date") or "")
    pairs: List[tuple] = []
    for i in range(len(rows) - 1):
        pairs.append((rows[i], rows[i + 1]))
    pairs = pairs[-max_pairs:]

    correct: Dict[str, int] = defaultdict(int)
    total_dir: Dict[str, int] = defaultdict(int)
    cw_ret_sum: Dict[str, float] = defaultdict(float)
    by_regime_correct: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_regime_total: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_regime_cw: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for left, right in pairs:
        left_t = left.get("tickers") or {}
        right_t = right.get("tickers") or {}
        regime = str(left.get("regime") or "unknown")
        common = set(left_t) & set(right_t)
        for ticker in common:
            p0 = float((left_t[ticker] or {}).get("price") or 0)
            p1 = float((right_t[ticker] or {}).get("price") or 0)
            if p0 <= 0:
                continue
            ret_pct = (p1 - p0) / p0 * 100.0
            for agent_key, sig in ((left_t[ticker] or {}).get("agent_signals") or {}).items():
                if not isinstance(sig, dict):
                    continue
                sig_val = sig.get("signal")
                conf = int(sig.get("confidence") or 50)
                _accumulate_signal(correct, total_dir, cw_ret_sum, agent_key, sig_val, conf, ret_pct)
                if sig_val in ("bullish", "bearish"):
                    _accumulate_signal(
                        by_regime_correct[regime],
                        by_regime_total[regime],
                        by_regime_cw[regime],
                        agent_key,
                        sig_val,
                        conf,
                        ret_pct,
                    )

    agents_out = _agents_from_stats(correct, total_dir, cw_ret_sum)
    if not agents_out:
        return {}

    by_regime_out: Dict[str, Any] = {}
    for regime, td_map in by_regime_total.items():
        reg_agents = _agents_from_stats(
            by_regime_correct[regime], td_map, by_regime_cw[regime], min_obs=min_regime_obs
        )
        if reg_agents:
            by_regime_out[regime] = {"agents": reg_agents}

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "run_pairs_used": len(pairs),
        "source": "weekly_ledger",
        "agents": agents_out,
        "by_regime": by_regime_out,
    }


def position_open_dates(path: Optional[Path] = None) -> Dict[str, str]:
    """Latest run_date a ticker was bought (from ledger position_opens + buy decisions)."""
    opens: Dict[str, str] = {}
    for row in _read_lines(path or LEDGER_PATH):
        rd = str(row.get("run_date") or "")
        for sym, dt in (row.get("position_opens") or {}).items():
            opens[sym] = dt or rd
        for sym, info in (row.get("tickers") or {}).items():
            if info.get("opened_this_run"):
                opens[sym] = rd
    return opens


def ledger_run_count(path: Optional[Path] = None) -> int:
    return len(_read_lines(path or LEDGER_PATH))
