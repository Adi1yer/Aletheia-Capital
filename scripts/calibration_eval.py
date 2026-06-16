#!/usr/bin/env python3
"""Monthly A/B eval: prompt calibration on vs off over cached weekly runs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtesting.feedback import composite_for_agent
from src.backtesting.learning_outcomes import PAIR_SEP, load_ticker_calibration
from src.performance.weekly_ledger import _read_lines as read_ledger_lines

OUTPUT_PATH = Path("data/performance/calibration_eval_latest.json")
SUMMARY_MD_PATH = Path("data/performance/calibration_eval_latest.md")


def _score_signal(sig_val: str, conf: int, ret_pct: float) -> Tuple[bool, float]:
    if sig_val == "bullish":
        hit = ret_pct > 0
        cw = ret_pct * (conf / 100.0)
    elif sig_val == "bearish":
        hit = ret_pct < 0
        cw = (-ret_pct) * (conf / 100.0)
    else:
        return False, 0.0
    return hit, cw


def _effective_confidence(
    agent_key: str,
    ticker: str,
    sig_val: str,
    conf: int,
    ret_pct: float,
    cal_data: Dict[str, Any],
) -> int:
    """Apply calibration penalties for the 'on' bucket."""
    eff = conf
    composite = composite_for_agent(agent_key)
    wrong_dir = (sig_val == "bullish" and ret_pct <= 0) or (sig_val == "bearish" and ret_pct >= 0)
    if composite is not None and composite < 0.45 and wrong_dir and conf >= 70:
        eff = max(30, int(conf * 0.75))

    key = f"{agent_key}{PAIR_SEP}{ticker.strip().upper()}"
    evs = (cal_data.get("pairs") or {}).get(key) or []
    hits = [ev for ev in evs if ev.get("directionally_correct") is not None]
    if len(hits) >= 3:
        rate = sum(1 for x in hits if x) / len(hits)
        if rate < 0.40:
            eff = max(30, int(eff * 0.85))
    return eff


def _eligible_tickers_from_ledger_row(row: Dict[str, Any]) -> Set[str]:
    return set((row.get("tickers") or {}).keys())


def _eligible_tickers_from_scan_run(run: Dict[str, Any]) -> Set[str]:
    symbols: Set[str] = set()
    port = run.get("portfolio_before") or {}
    for sym, pos in (port.get("positions") or {}).items():
        if isinstance(pos, dict) and int(pos.get("long") or 0) > 0:
            symbols.add(sym)
    for sym, dec in (run.get("decisions") or {}).items():
        if not isinstance(dec, dict):
            continue
        if dec.get("action") in ("buy", "sell", "short", "cover") and int(dec.get("quantity") or 0) > 0:
            symbols.add(sym)
    return symbols


def _eval_pairs(
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    source: str,
    *,
    use_scan_cache: bool = False,
    eligible_fn=None,
) -> Dict[str, Any]:
    cal_data = load_ticker_calibration()
    on_hits = on_n = 0
    off_hits = off_n = 0
    on_cw = off_cw = 0.0

    for left, right in pairs:
        if use_scan_cache:
            left_risk = left.get("risk") or {}
            right_risk = right.get("risk") or {}
            signals = left.get("signals") or {}
            eligible = eligible_fn(left) if eligible_fn else set(left_risk) & set(right_risk)
            for ticker in eligible:
                p0 = float((left_risk.get(ticker) or {}).get("current_price") or 0)
                p1 = float((right_risk.get(ticker) or {}).get("current_price") or 0)
                if p0 <= 0:
                    continue
                ret_pct = (p1 - p0) / p0 * 100.0
                for agent_key, ticker_signals in signals.items():
                    if not isinstance(ticker_signals, dict):
                        continue
                    sig = ticker_signals.get(ticker)
                    if not isinstance(sig, dict):
                        continue
                    sig_val = sig.get("signal")
                    conf = int(sig.get("confidence") or 50)
                    if sig_val not in ("bullish", "bearish"):
                        continue
                    hit, cw = _score_signal(sig_val, conf, ret_pct)
                    off_n += 1
                    off_cw += cw
                    if hit:
                        off_hits += 1
                    eff_conf = _effective_confidence(
                        agent_key, ticker, sig_val, conf, ret_pct, cal_data
                    )
                    on_hit, on_cw_val = _score_signal(sig_val, eff_conf, ret_pct)
                    on_n += 1
                    on_cw += on_cw_val
                    if on_hit:
                        on_hits += 1
            continue

        left_map = left.get("tickers") or {}
        right_map = right.get("tickers") or {}
        eligible = eligible_fn(left) if eligible_fn else set(left_map) & set(right_map)
        for ticker in eligible:
            if ticker not in left_map or ticker not in right_map:
                continue
            p0 = float((left_map[ticker] or {}).get("price") or 0)
            p1 = float((right_map[ticker] or {}).get("price") or 0)
            agent_sigs = (left_map[ticker] or {}).get("agent_signals") or {}
            if p0 <= 0:
                continue
            ret_pct = (p1 - p0) / p0 * 100.0
            for agent_key, sig in agent_sigs.items():
                if not isinstance(sig, dict):
                    continue
                sig_val = sig.get("signal")
                conf = int(sig.get("confidence") or 50)
                if sig_val not in ("bullish", "bearish"):
                    continue
                hit, cw = _score_signal(sig_val, conf, ret_pct)
                off_n += 1
                off_cw += cw
                if hit:
                    off_hits += 1
                eff_conf = _effective_confidence(
                    agent_key, ticker, sig_val, conf, ret_pct, cal_data
                )
                on_hit, on_cw_val = _score_signal(sig_val, eff_conf, ret_pct)
                on_n += 1
                on_cw += on_cw_val
                if on_hit:
                    on_hits += 1

    off_acc = (off_hits / off_n) if off_n else 0.0
    on_acc = (on_hits / on_n) if on_n else 0.0
    lane_drift: Dict[str, float] = {}
    for key, evs in (cal_data.get("pairs") or {}).items():
        if "|" not in key:
            continue
        agent_key = key.split("|", 1)[0]
        lane = "other"
        low = agent_key.lower()
        if "growth" in low:
            lane = "growth"
        elif "value" in low or "valuation" in low:
            lane = "value"
        vals = [e for e in evs if e.get("directionally_correct") is not None]
        if vals:
            lane_drift[lane] = lane_drift.get(lane, 0.0) + (
                sum(1 for v in vals if v.get("directionally_correct")) / len(vals)
            )
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source": source,
        "pairs_used": len(pairs),
        "off_calibration": {
            "directional_accuracy": round(off_acc, 4),
            "observations": off_n,
            "confidence_weighted_return": round(off_cw, 4),
        },
        "on_calibration": {
            "directional_accuracy": round(on_acc, 4),
            "observations": on_n,
            "confidence_weighted_return": round(on_cw, 4),
        },
        "delta_accuracy_pp": round((on_acc - off_acc) * 100, 2),
        "alert": (on_acc - off_acc) < -0.02,
        "agent_lane_drift": lane_drift,
    }


def _eval_from_ledger(max_pairs: int = 8) -> Dict[str, Any]:
    rows = read_ledger_lines()
    if len(rows) < 2:
        return {"error": "insufficient_ledger_rows", "pairs": 0}
    rows = sorted(rows, key=lambda r: r.get("run_date") or "")
    pairs = [(rows[i], rows[i + 1]) for i in range(len(rows) - 1)][-max_pairs:]
    return _eval_pairs(pairs, "weekly_ledger", eligible_fn=_eligible_tickers_from_ledger_row)


def _eval_from_scan_cache(max_pairs: int = 8) -> Dict[str, Any]:
    from src.scan_cache import ScanCache

    cache = ScanCache()
    runs_meta = cache.list_runs(limit=max_pairs + 1)
    if len(runs_meta) < 2:
        return {"error": "insufficient_scan_cache_runs", "pairs": 0}
    runs_meta = sorted(runs_meta, key=lambda r: r.get("run_date") or "")[-(max_pairs + 1) :]
    loaded: List[Dict[str, Any]] = []
    for meta in runs_meta:
        try:
            loaded.append(cache.load_run(meta["run_id"]))
        except Exception:
            continue
    if len(loaded) < 2:
        return {"error": "could_not_load_scan_runs", "pairs": 0}
    pairs = [(loaded[i], loaded[i + 1]) for i in range(len(loaded) - 1)]
    return _eval_pairs(pairs, "scan_cache", use_scan_cache=True, eligible_fn=_eligible_tickers_from_scan_run)


def run_eval(source: str = "scan_cache", max_pairs: int = 8) -> Dict[str, Any]:
    if source == "production_replay":
        from src.backtesting.engine import BacktestingEngine

        replay = BacktestingEngine().run_weekly_replay(max_runs=max_pairs)
        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source": "production_replay",
            "pairs_used": int(replay.get("runs_used") or 0),
            "off_calibration": {"directional_accuracy": 0.0, "observations": 0, "confidence_weighted_return": 0.0},
            "on_calibration": {"directional_accuracy": 0.0, "observations": 0, "confidence_weighted_return": 0.0},
            "delta_accuracy_pp": 0.0,
            "alert": False,
            "replay_summary": replay,
        }
    if source == "ledger":
        return _eval_from_ledger(max_pairs=max_pairs)
    payload = _eval_from_scan_cache(max_pairs=max_pairs)
    if payload.get("error"):
        fallback = _eval_from_ledger(max_pairs=max_pairs)
        if not fallback.get("error"):
            fallback["fallback_from"] = payload.get("error")
            return fallback
    return payload


def compare_payloads(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    b = float((baseline.get("on_calibration") or {}).get("directional_accuracy") or 0.0)
    c = float((candidate.get("on_calibration") or {}).get("directional_accuracy") or 0.0)
    return {
        "baseline_accuracy": b,
        "candidate_accuracy": c,
        "delta_pp": round((c - b) * 100, 2),
        "winner": "candidate" if c > b else "baseline",
    }


def _write_outputs(payload: Dict[str, Any]) -> None:
    from src.performance.promotion_gates import set_calibration_hold

    if payload.get("alert"):
        set_calibration_hold(True, reason="calibration_eval_regression")
    else:
        set_calibration_hold(False, reason="calibration_eval_ok")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    try:
        from src.performance.confidence_calibration import rebuild_calibration_files, reliability_metrics

        rm = reliability_metrics(rebuild_calibration_files())
        payload["reliability"] = rm
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass
    lines = [
        "# Calibration A/B eval",
        "",
        f"Generated: {payload.get('generated_at')}",
        f"Source: {payload.get('source')}",
        f"Pairs used: {payload.get('pairs_used', 0)}",
        "",
        f"- Off accuracy: {payload.get('off_calibration', {}).get('directional_accuracy', 0):.1%}",
        f"- On accuracy: {payload.get('on_calibration', {}).get('directional_accuracy', 0):.1%}",
        f"- Delta: {payload.get('delta_accuracy_pp', 0):+.2f} pp",
        "",
    ]
    if payload.get("alert"):
        lines.append("**ALERT:** Calibration appears to hurt accuracy by >2pp.")
    SUMMARY_MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def _maybe_email_alert(payload: Dict[str, Any]) -> None:
    if not payload.get("alert"):
        return
    try:
        from src.utils.email import get_email_notifier
        from src.config.settings import settings

        recipient = (settings.recipient_email or "").strip()
        if not recipient:
            return
        notifier = get_email_notifier()
        body = SUMMARY_MD_PATH.read_text(encoding="utf-8") if SUMMARY_MD_PATH.is_file() else str(payload)
        notifier.send_email(
            recipient=recipient,
            subject="Calibration A/B alert: calibration may be hurting accuracy",
            body_text=body,
        )
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibration A/B evaluation")
    parser.add_argument("--max-pairs", type=int, default=8)
    parser.add_argument(
        "--source",
        choices=("scan_cache", "ledger", "production_replay"),
        default="scan_cache",
        help="Primary data source (scan_cache falls back to ledger on error)",
    )
    args = parser.parse_args()
    payload = run_eval(source=args.source, max_pairs=args.max_pairs)
    _write_outputs(payload)
    _maybe_email_alert(payload)
    print(json.dumps(payload, indent=2))
    return 0 if "error" not in payload else 1


if __name__ == "__main__":
    raise SystemExit(main())
