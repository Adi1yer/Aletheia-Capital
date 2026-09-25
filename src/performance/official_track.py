"""Official wheel-10k paper track: frozen start, daily snapshots, scoreboard math.

Official scoreboard NAV is Alpaca equity. cash+stocks is supplemental.
Never reset start_date / start_nav without a new track id.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

TRACK_ID = "wheel-10k-paper-v1"
START_DATE = date(2026, 9, 21)
START_NAV_USD = 10_000.0
RISK_FREE_ANNUAL = 0.0  # documented: 0% (no T-bill subtract)
PERIODS_PER_YEAR = 252.0
SNAPSHOT_DIR = Path("data/performance/official")
LAST_SUCCESS_NAME = "last_successful_run_et.txt"
EXPECTED_MORNING_ET = time(10, 30)
LATE_AFTER_ET = time(12, 0)

FINGERPRINT_KEYS = (
    "track_id",
    "start_date",
    "start_nav_usd",
    "wheel_pct",
    "directional_pct",
    "max_position_pct",
    "max_lots_per_name",
    "add_lot_min_score",
    "max_csp_collateral_pct",
    "csp_reserve_frac",
    "cc_otm_pct_low",
    "cc_otm_pct_high",
    "cc_target_otm_pct",
    "min_csp_premium_usd",
    "min_csp_annualized_yield_pct",
    "max_wheel_names",
    "cash_buffer_pct",
)


def _finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


def config_fingerprint(run_config: Optional[Dict[str, Any]] = None) -> str:
    cfg = dict(run_config or {})
    payload = {
        "track_id": TRACK_ID,
        "start_date": START_DATE.isoformat(),
        "start_nav_usd": START_NAV_USD,
    }
    for k in FINGERPRINT_KEYS:
        if k in ("track_id", "start_date", "start_nav_usd"):
            continue
        if k in cfg:
            payload[k] = cfg.get(k)
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def snapshot_dir(root: Optional[Path] = None) -> Path:
    return Path(root) if root is not None else SNAPSHOT_DIR


def last_success_path(root: Optional[Path] = None) -> Path:
    return snapshot_dir(root) / LAST_SUCCESS_NAME


def mark_successful_run(
    day: Optional[date] = None,
    *,
    root: Optional[Path] = None,
) -> Path:
    path = last_success_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    et_day = day or datetime.now(tz=ET).date()
    path.write_text(f"{et_day.isoformat()}\n", encoding="utf-8")
    return path


def read_last_successful_run(root: Optional[Path] = None) -> Optional[date]:
    path = last_success_path(root)
    if path.is_file():
        try:
            return date.fromisoformat(path.read_text(encoding="utf-8").strip().splitlines()[0])
        except (OSError, ValueError, IndexError):
            pass
    try:
        from src.trading.wheel_daily_once import read_completed_et_day

        return read_completed_et_day()
    except Exception:
        return None


def snapshot_path(day: date, root: Optional[Path] = None) -> Path:
    return snapshot_dir(root) / f"{day.isoformat()}.json"


def save_snapshot(snap: Dict[str, Any], *, root: Optional[Path] = None) -> Path:
    day = date.fromisoformat(str(snap.get("date") or datetime.now(tz=ET).date()))
    path = snapshot_path(day, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
    return path


def load_snapshots(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    d = snapshot_dir(root)
    if not d.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for p in sorted(d.glob("????-??-??.json")):
        try:
            row = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(row, dict) and row.get("date"):
            rows.append(row)
    rows.sort(key=lambda r: str(r.get("date") or ""))
    return rows


def expected_sessions(asof: date, start: date = START_DATE) -> int:
    from src.trading.us_equity_calendar import is_us_equity_trading_day

    if asof < start:
        return 0
    n = 0
    d = start
    while d <= asof:
        if is_us_equity_trading_day(d):
            n += 1
        d += timedelta(days=1)
    return n


def fetch_spy_level(data_provider: Any, asof: Optional[date] = None) -> Optional[float]:
    if data_provider is None:
        return None
    day = asof or datetime.now(tz=ET).date()
    start = (day - timedelta(days=12)).isoformat()
    end = day.isoformat()
    try:
        prices = data_provider.get_prices("SPY", start, end)
    except Exception:
        return None
    closes: List[float] = []
    for p in prices or []:
        c = getattr(p, "close", None)
        if c is None and isinstance(p, dict):
            c = p.get("close")
        v = _finite(c)
        if v is not None and v > 0:
            closes.append(v)
    return closes[-1] if closes else None


def _action_counts(results: Dict[str, Any]) -> Dict[str, int]:
    buys = sells = 0
    for d in (results.get("decisions") or {}).values():
        if not isinstance(d, dict):
            continue
        act = str(d.get("action") or "")
        if act == "buy":
            buys += 1
        elif act in ("sell", "cover"):
            sells += 1
    cc = sum(1 for r in (results.get("covered_call_results") or []) if r.get("status") == "executed")
    csp = sum(1 for r in (results.get("csp_results") or []) if r.get("status") == "executed")
    btc = sum(1 for r in (results.get("wheel_manage_results") or []) if r.get("status") == "btc_executed")
    rolls = sum(1 for r in (results.get("wheel_manage_results") or []) if r.get("status") == "roll_executed")
    return {"buys": buys, "sells": sells, "cc": cc, "csp": csp, "btc": btc, "rolls": rolls}


def _turnover_usd(results: Dict[str, Any], prices: Optional[Dict[str, float]] = None) -> float:
    px = {str(k).upper(): _finite(v, 0.0) or 0.0 for k, v in (prices or {}).items()}
    total = 0.0
    for t, d in (results.get("decisions") or {}).items():
        if not isinstance(d, dict):
            continue
        if str(d.get("action") or "") not in ("buy", "sell", "cover"):
            continue
        try:
            qty = abs(int(d.get("quantity") or 0))
        except (TypeError, ValueError):
            qty = 0
        p = px.get(str(t).upper(), 0.0)
        if p <= 0:
            p = _finite((d.get("price")), 0.0) or 0.0
        total += qty * p
    for r in (results.get("covered_call_results") or []) + (results.get("csp_results") or []):
        if str(r.get("status") or "") != "executed":
            continue
        total += abs(_finite(r.get("estimated_premium"), 0.0) or 0.0)
    return round(total, 2)


def _option_credit_stats(results: Dict[str, Any]) -> Tuple[int, int]:
    closed = 0
    credit = 0
    for r in results.get("wheel_manage_results") or []:
        st = str(r.get("status") or "")
        if st not in ("btc_executed", "roll_executed"):
            continue
        closed += 1
        if st == "roll_executed" and (_finite(r.get("est_net_credit"), 0.0) or 0.0) > 0:
            credit += 1
        elif st == "btc_executed" and "profit_take" in str(r.get("reason") or ""):
            credit += 1
    return credit, closed


def _fill_failures(results: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for t, er in (results.get("execution_results") or {}).items():
        if not isinstance(er, dict):
            continue
        fill = er.get("fill")
        if isinstance(fill, dict) and fill.get("ok") is False:
            out.append(f"{t}:fill_failed")
        if str(er.get("status") or "").lower() in ("rejected", "canceled", "cancelled", "failed"):
            out.append(f"{t}:{er.get('status')}")
    for r in results.get("covered_call_results") or []:
        st = str(r.get("status") or "")
        if st in ("atomic_unwind", "underhedge_trim", "failed", "atomic_unwind_failed"):
            out.append(f"CC {r.get('underlying')}:{st}")
    for r in results.get("csp_results") or []:
        if str(r.get("status") or "") in ("failed", "error"):
            out.append(f"CSP {r.get('underlying')}:{r.get('reason') or r.get('status')}")
    if results.get("coverage_unavailable"):
        out.append("coverage_unavailable")
    return out[:20]


def _coverage_alerts(results: Dict[str, Any]) -> List[str]:
    alerts = []
    for row in results.get("coverage_map") or []:
        cov = str(row.get("coverage") or "")
        if cov in ("UNCOVERED", "UNDERHEDGED", "OVERHEDGED", "NAKED_SHORT"):
            alerts.append(f"{row.get('ticker')}:{cov}")
    return alerts


def snapshot_from_results(
    results: Dict[str, Any],
    *,
    run_config: Optional[Dict[str, Any]] = None,
    mix: Optional[Dict[str, Any]] = None,
    spy_level: Optional[float] = None,
    morning_status: str = "ok",
    afternoon_status: str = "unknown",
) -> Dict[str, Any]:
    from src.utils.wheel_email import _sleeve_mix

    mix = mix or _sleeve_mix(results)
    ts = str(results.get("timestamp") or "")
    try:
        day = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except Exception:
        day = datetime.now(tz=ET).date()
    port = results.get("portfolio") or {}
    positions = {
        str(t).upper(): int((pos or {}).get("long") or 0)
        for t, pos in (port.get("positions") or {}).items()
        if int((pos or {}).get("long") or 0) > 0
    }
    credit_ok, credit_n = _option_credit_stats(results)
    es = results.get("execution_status") or {}
    orders = {
        "submitted": int(es.get("submitted") or 0),
        "filled": int(es.get("filled") or 0),
        "partial": int(es.get("partial") or 0),
        "rejected": int(es.get("failed") or 0),
        "pending": int(es.get("pending") or 0),
    }
    prices = {}
    for t, ra in (results.get("risk_analysis") or {}).items():
        v = _finite((ra or {}).get("current_price"))
        if v:
            prices[str(t).upper()] = v
    return {
        "track_id": TRACK_ID,
        "date": day.isoformat(),
        "official_nav_usd": round(_finite(mix.get("equity"), 0.0) or 0.0, 2),
        "cash_plus_stocks_usd": round(_finite(mix.get("cash_plus_stocks"), 0.0) or 0.0, 2),
        "cash_usd": round(_finite(mix.get("cash"), 0.0) or 0.0, 2),
        "spendable_cash_usd": round(_finite(mix.get("spendable_cash"), 0.0) or 0.0, 2),
        "wheel_mv": round(_finite(mix.get("wheel_mv"), 0.0) or 0.0, 2),
        "directional_mv": round(_finite(mix.get("directional_mv"), 0.0) or 0.0, 2),
        "premium_ledger_usd": round(_finite(mix.get("premium_ledger"), 0.0) or 0.0, 2),
        "option_mtm_usd": mix.get("option_mtm"),
        "spy_level": _finite(spy_level),
        "positions_summary": positions,
        "actions": _action_counts(results),
        "orders": orders,
        "fill_failures": _fill_failures(results),
        "coverage_alerts": _coverage_alerts(results),
        "turnover_usd": _turnover_usd(results, prices),
        "option_credit_closes": credit_ok,
        "option_closes": credit_n,
        "config_fingerprint": config_fingerprint(run_config),
        "job": {
            "morning": morning_status,
            "afternoon": afternoon_status,
            "timestamp": ts,
            "execute_skipped": results.get("execute_skipped_reason") or "",
        },
        "coverage_unavailable": bool(results.get("coverage_unavailable")),
    }


def _nav_series(snaps: Sequence[Dict[str, Any]]) -> List[Tuple[date, float]]:
    out: List[Tuple[date, float]] = [(START_DATE, START_NAV_USD)]
    seen = {START_DATE}
    for s in snaps:
        try:
            d = date.fromisoformat(str(s.get("date")))
        except ValueError:
            continue
        nav = _finite(s.get("official_nav_usd"))
        if nav is None or nav <= 0:
            continue
        if d == START_DATE:
            out[0] = (d, nav)
            continue
        if d in seen:
            continue
        seen.add(d)
        out.append((d, nav))
    out.sort(key=lambda x: x[0])
    return out


def _returns(series: Sequence[Tuple[date, float]]) -> List[float]:
    rets: List[float] = []
    for i in range(1, len(series)):
        prev = series[i - 1][1]
        cur = series[i][1]
        if prev > 0:
            rets.append((cur / prev) - 1.0)
    return rets


def _spy_returns(snaps: Sequence[Dict[str, Any]]) -> List[float]:
    levels: List[float] = []
    for s in snaps:
        lv = _finite(s.get("spy_level"))
        if lv is not None and lv > 0:
            levels.append(lv)
    rets = []
    for i in range(1, len(levels)):
        if levels[i - 1] > 0:
            rets.append(levels[i] / levels[i - 1] - 1.0)
    return rets


def _max_drawdown(navs: Sequence[float]) -> Optional[float]:
    if not navs:
        return None
    peak = navs[0]
    max_dd = 0.0
    for x in navs:
        peak = max(peak, x)
        if peak > 0:
            max_dd = min(max_dd, (x - peak) / peak)
    return max_dd


def _sharpe(rets: Sequence[float]) -> Optional[float]:
    if len(rets) < 4:
        return None
    rf_d = RISK_FREE_ANNUAL / PERIODS_PER_YEAR
    excess = [r - rf_d for r in rets]
    mean = sum(excess) / len(excess)
    if len(excess) < 2:
        return None
    std = statistics.stdev(excess)
    if std <= 1e-12:
        return None
    return (mean / std) * math.sqrt(PERIODS_PER_YEAR)


def _sortino(rets: Sequence[float]) -> Optional[float]:
    if len(rets) < 4:
        return None
    rf_d = RISK_FREE_ANNUAL / PERIODS_PER_YEAR
    mean = sum(rets) / len(rets) - rf_d
    downside = [min(0.0, r - rf_d) for r in rets]
    var = sum(x * x for x in downside) / max(1, len(downside))
    dstd = math.sqrt(var)
    if dstd <= 1e-12:
        return None
    return (mean / dstd) * math.sqrt(PERIODS_PER_YEAR)


def _beta_corr(fund: Sequence[float], spy: Sequence[float]) -> Tuple[Optional[float], Optional[float]]:
    n = min(len(fund), len(spy))
    if n < 4:
        return None, None
    f = list(fund[:n])
    s = list(spy[:n])
    mean_f = sum(f) / n
    mean_s = sum(s) / n
    cov = sum((a - mean_f) * (b - mean_s) for a, b in zip(f, s)) / max(1, n - 1)
    var_s = sum((b - mean_s) ** 2 for b in s) / max(1, n - 1)
    var_f = sum((a - mean_f) ** 2 for a in f) / max(1, n - 1)
    beta = cov / var_s if var_s > 1e-16 else None
    denom = math.sqrt(var_f * var_s) if var_f > 0 and var_s > 0 else 0.0
    corr = (cov / denom) if denom > 1e-16 else None
    return beta, corr


def _turnover_window(snaps: Sequence[Dict[str, Any]], n: int) -> Optional[float]:
    tail = list(snaps)[-n:]
    if not tail:
        return None
    traded = sum(_finite(s.get("turnover_usd"), 0.0) or 0.0 for s in tail)
    navs = [_finite(s.get("official_nav_usd"), 0.0) or 0.0 for s in tail]
    navs = [x for x in navs if x > 0]
    if not navs:
        return None
    avg = sum(navs) / len(navs)
    if avg <= 0:
        return None
    return traded / avg


def build_track_record(
    snaps: Sequence[Dict[str, Any]],
    *,
    asof: Optional[date] = None,
) -> Dict[str, Any]:
    asof = asof or datetime.now(tz=ET).date()
    series = _nav_series(snaps)
    navs = [v for _, v in series]
    current = navs[-1] if navs else START_NAV_USD
    fund_ret = current / START_NAV_USD - 1.0
    spy_levels = [
        (_finite(s.get("spy_level")))
        for s in snaps
        if _finite(s.get("spy_level")) and (_finite(s.get("spy_level")) or 0) > 0
    ]
    spy_ret = None
    if len(spy_levels) >= 2 and spy_levels[0] and spy_levels[-1]:
        spy_ret = spy_levels[-1] / spy_levels[0] - 1.0
    elif len(spy_levels) == 1:
        spy_ret = 0.0
    excess_pct = None if spy_ret is None else fund_ret - spy_ret
    excess_usd = None if excess_pct is None else excess_pct * START_NAV_USD
    rets = _returns(series)
    spy_rets = _spy_returns(snaps)
    beta, corr = _beta_corr(rets, spy_rets)
    alpha = None
    if beta is not None and rets and spy_rets:
        n = min(len(rets), len(spy_rets))
        mean_f = sum(rets[:n]) / n
        mean_s = sum(spy_rets[:n]) / n
        alpha = (mean_f - RISK_FREE_ANNUAL / PERIODS_PER_YEAR - beta * (
            mean_s - RISK_FREE_ANNUAL / PERIODS_PER_YEAR
        )) * PERIODS_PER_YEAR
    hit = sum(1 for r in rets if r > 0)
    opt_ok = sum(int(s.get("option_credit_closes") or 0) for s in snaps)
    opt_n = sum(int(s.get("option_closes") or 0) for s in snaps)
    peak = max(navs) if navs else START_NAV_USD
    current_dd = (current / peak - 1.0) if peak > 0 else 0.0
    expected = expected_sessions(asof)
    sessions = max(0, len(series) - 1) if series and series[0][0] == START_DATE else len(series)
    # If first snap is start date replacing 10k, sessions = len(snaps)
    if snaps:
        sessions = len({str(s.get("date")) for s in snaps})
    last = str(snaps[-1].get("date")) if snaps else None
    fp = None
    for s in reversed(snaps):
        if s.get("config_fingerprint"):
            fp = s.get("config_fingerprint")
            break
    return {
        "track_id": TRACK_ID,
        "start_date": START_DATE.isoformat(),
        "start_nav_usd": START_NAV_USD,
        "current_nav_usd": round(current, 2),
        "abs_return_pct": round(fund_ret * 100.0, 2),
        "abs_return_usd": round(current - START_NAV_USD, 2),
        "spy_return_pct": None if spy_ret is None else round(spy_ret * 100.0, 2),
        "excess_return_pct": None if excess_pct is None else round(excess_pct * 100.0, 2),
        "excess_return_usd": None if excess_usd is None else round(excess_usd, 2),
        "max_drawdown_pct": None if _max_drawdown(navs) is None else round((_max_drawdown(navs) or 0) * 100.0, 2),
        "current_drawdown_pct": round(current_dd * 100.0, 2),
        "sharpe": None if _sharpe(rets) is None else round(_sharpe(rets) or 0, 2),
        "sortino": None if _sortino(rets) is None else round(_sortino(rets) or 0, 2),
        "risk_free_annual": RISK_FREE_ANNUAL,
        "hit_rate_pct": None if not rets else round(100.0 * hit / len(rets), 1),
        "hit_sessions": hit,
        "return_sessions": len(rets),
        "option_credit_hit_pct": None if opt_n <= 0 else round(100.0 * opt_ok / opt_n, 1),
        "option_credit_closes": opt_ok,
        "option_closes": opt_n,
        "turnover_5": None if _turnover_window(snaps, 5) is None else round(_turnover_window(snaps, 5) or 0, 3),
        "turnover_21": None if _turnover_window(snaps, 21) is None else round(_turnover_window(snaps, 21) or 0, 3),
        "beta": None if beta is None else round(beta, 2),
        "corr": None if corr is None else round(corr, 2),
        "alpha_annual": None if alpha is None else round(alpha * 100.0, 2),
        "days_in_track": (asof - START_DATE).days + 1,
        "sessions_expected": expected,
        "sessions_with_email": sessions,
        "last_successful_date": last,
        "config_fingerprint": fp,
        "official_nav_definition": "alpaca_equity",
    }


def build_ops_health(
    results: Dict[str, Any],
    *,
    snaps: Optional[Sequence[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    morning_status: str = "ok",
    afternoon_status: str = "unknown",
    holiday_reason: str = "",
) -> Dict[str, Any]:
    now = now or datetime.now(tz=ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    now = now.astimezone(ET)
    ts = str(results.get("timestamp") or "")
    late = False
    try:
        run_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET)
        late = run_dt.timetz().replace(tzinfo=None) >= LATE_AFTER_ET if hasattr(run_dt, "timetz") else run_dt.time() >= LATE_AFTER_ET
        clock = run_dt.strftime("%H:%M ET")
    except Exception:
        clock = now.strftime("%H:%M ET")
        run_dt = now
        late = now.time() >= LATE_AFTER_ET
    es = results.get("execution_status") or {}
    port = results.get("portfolio") or {}
    csp_coll = 0.0
    for row in results.get("short_put_map") or []:
        csp_coll += _finite(row.get("collateral_usd"), 0.0) or 0.0
    eq = _finite((port.get("equity") or port.get("broker_equity")), 0.0) or 0.0
    csp_limit = 0.45 * eq if eq > 0 else None
    csp_over = bool(csp_limit and csp_coll > csp_limit + 1.0)
    halted = bool(results.get("execute_skipped_reason"))
    return {
        "morning": morning_status,
        "afternoon": afternoon_status,
        "holiday_reason": holiday_reason,
        "clock": clock,
        "expected_window": "10:30 ET",
        "late": late,
        "broker_ok": bool(results.get("broker_used")),
        "buying_power": _finite(port.get("cash")),
        "orders": {
            "submitted": int(es.get("submitted") or 0),
            "filled": int(es.get("filled") or 0),
            "partial": int(es.get("partial") or 0),
            "rejected": int(es.get("failed") or 0),
            "pending": int(es.get("pending") or 0),
        },
        "fill_failures": _fill_failures(results),
        "coverage_alerts": _coverage_alerts(results),
        "coverage_unavailable": bool(results.get("coverage_unavailable")),
        "csp_collateral_usd": round(csp_coll, 2),
        "csp_over_limit": csp_over,
        "max_position_pct": 0.35,
        "trading_halted": halted,
        "halt_reason": results.get("execute_skipped_reason") or "",
        "last_successful_date": (snaps[-1].get("date") if snaps else None),
    }


def missed_run_due(
    *,
    now: Optional[datetime] = None,
    root: Optional[Path] = None,
    last_success: Optional[date] = None,
    force: bool = False,
) -> Tuple[bool, str]:
    """True when an NYSE weekday has no successful morning marker after the window."""
    now = now or datetime.now(tz=ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    now = now.astimezone(ET)
    from src.trading.us_equity_calendar import is_us_equity_trading_day

    today = now.date()
    if force:
        return True, "forced"
    if not is_us_equity_trading_day(today):
        return False, f"market_closed:{today.isoformat()}"
    if now.time() < LATE_AFTER_ET:
        return False, "before_watchdog"
    last = last_success if last_success is not None else read_last_successful_run(root)
    if last == today:
        return False, f"already_succeeded:{today.isoformat()}"
    return True, f"missed_morning:{today.isoformat()}:last={last.isoformat() if last else 'none'}"


def attach_official_track(
    results: Dict[str, Any],
    *,
    run_config: Optional[Dict[str, Any]] = None,
    data_provider: Any = None,
    root: Optional[Path] = None,
    persist: bool = True,
    morning_status: str = "ok",
    afternoon_status: str = "unknown",
) -> Dict[str, Any]:
    """Write today's snapshot and attach track_record + ops_health onto results."""
    spy = None
    try:
        spy = fetch_spy_level(data_provider)
    except Exception:
        spy = None
    snap = snapshot_from_results(
        results,
        run_config=run_config,
        spy_level=spy,
        morning_status=morning_status,
        afternoon_status=afternoon_status,
    )
    if persist:
        try:
            save_snapshot(snap, root=root)
        except OSError:
            pass
    snaps = load_snapshots(root)
    if persist and snap.get("date") and not any(s.get("date") == snap["date"] for s in snaps):
        snaps.append(snap)
        snaps.sort(key=lambda s: str(s.get("date") or ""))
    elif persist:
        snaps = [s for s in snaps if s.get("date") != snap.get("date")] + [snap]
        snaps.sort(key=lambda s: str(s.get("date") or ""))
    try:
        asof = date.fromisoformat(str(snap.get("date")))
    except ValueError:
        asof = datetime.now(tz=ET).date()
    results["official_snapshot"] = snap
    results["track_record"] = build_track_record(snaps, asof=asof)
    results["ops_health"] = build_ops_health(
        results,
        snaps=snaps,
        morning_status=morning_status,
        afternoon_status=afternoon_status,
    )
    results["config_fingerprint"] = snap.get("config_fingerprint")
    return results


def weekly_slice(snaps: Sequence[Dict[str, Any]], friday: date) -> List[Dict[str, Any]]:
    monday = friday - timedelta(days=4)
    out = []
    for s in snaps:
        try:
            d = date.fromisoformat(str(s.get("date")))
        except ValueError:
            continue
        if monday <= d <= friday:
            out.append(s)
    return out


def top_contributors(snaps: Sequence[Dict[str, Any]], n: int = 5) -> Tuple[List[str], List[str]]:
    """Rough week contributors from first-to-last position set (names only)."""
    if len(snaps) < 2:
        return [], []
    first = snaps[0].get("positions_summary") or {}
    last = snaps[-1].get("positions_summary") or {}
    added = sorted(set(last) - set(first))
    dropped = sorted(set(first) - set(last))
    return added[:n], dropped[:n]
