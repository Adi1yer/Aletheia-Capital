"""US equity session timing and per-run order fill status for weekly emails."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)

_FILLED = frozenset({"filled", "done_for_day"})
_OPEN = frozenset(
    {
        "new",
        "accepted",
        "pending_new",
        "partially_filled",
        "open",
        "pending_replace",
        "accepted_for_bidding",
    }
)
_FAILED = frozenset({"failed", "rejected", "canceled", "cancelled", "expired"})


def execution_state_machine(status: str, filled_qty: int, qty: int) -> str:
    s = str(status or "").lower()
    if s in _FAILED:
        return "rejected"
    if qty > 0 and filled_qty >= qty:
        return "filled"
    if filled_qty > 0:
        return "partiallyFilled"
    if s in _OPEN:
        return "accepted"
    return "submitted"


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("UTC"))


def is_us_equity_rth(dt: datetime) -> bool:
    """True during NYSE regular session (Mon–Fri 9:30 AM–4:00 PM ET, no holiday calendar)."""
    et = _as_utc(dt).astimezone(ET)
    if et.weekday() >= 5:
        return False
    t = et.time()
    return RTH_OPEN <= t < RTH_CLOSE


def next_us_equity_open_after(dt: datetime) -> datetime:
    """Next regular-session open at or after ``dt`` (ET, naive holiday handling)."""
    et = _as_utc(dt).astimezone(ET)
    candidate = et.replace(hour=9, minute=30, second=0, microsecond=0)
    if et.weekday() >= 5:
        days_ahead = 7 - et.weekday()
        candidate = (et + timedelta(days=days_ahead)).replace(
            hour=9, minute=30, second=0, microsecond=0
        )
    elif et.time() >= RTH_CLOSE:
        candidate = (et + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
    elif et.time() < RTH_OPEN:
        if et.weekday() >= 5:
            while candidate.weekday() >= 5:
                candidate += timedelta(days=1)
    else:
        return candidate
    return candidate


def _parse_run_timestamp(ts: Optional[str]) -> datetime:
    if not ts:
        return datetime.now(ZoneInfo("UTC"))
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(ZoneInfo("UTC"))


def _index_orders(orders: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    by_id: Dict[str, Dict] = {}
    by_symbol: Dict[str, Dict] = {}
    for o in orders or []:
        if not isinstance(o, dict):
            continue
        oid = str(o.get("id") or o.get("order_id") or "")
        sym = str(o.get("symbol") or "").upper()
        if oid:
            by_id[oid] = o
        if sym:
            by_symbol[sym] = o
    return by_id, by_symbol


def _classify_ticker_order(
    ticker: str,
    exec_res: Dict[str, Any],
    open_by_id: Dict[str, Dict],
    recent_by_id: Dict[str, Dict],
    open_by_symbol: Dict[str, Dict],
    recent_by_symbol: Dict[str, Dict],
) -> Tuple[str, str]:
    """Return (status_bucket, broker_status_detail)."""
    if not exec_res or exec_res.get("success") is False:
        err = str(exec_res.get("error") or exec_res.get("status") or "failed")
        return "failed", err
    if str(exec_res.get("status") or "").lower() in _FAILED:
        return "failed", str(exec_res.get("status") or "failed")

    oid = str(exec_res.get("order_id") or "")
    sym = str(ticker or exec_res.get("symbol") or "").upper()
    broker_row = None
    if oid and oid in recent_by_id:
        broker_row = recent_by_id[oid]
    elif oid and oid in open_by_id:
        broker_row = open_by_id[oid]
    elif sym and sym in recent_by_symbol:
        broker_row = recent_by_symbol[sym]
    elif sym and sym in open_by_symbol:
        broker_row = open_by_symbol[sym]

    if broker_row:
        status = str(broker_row.get("status") or "").lower()
        qty = int(broker_row.get("qty") or 0)
        filled_qty = int(broker_row.get("filled_qty") or 0)
        if status in _FILLED or (qty > 0 and filled_qty >= qty):
            return "filled", status or "filled"
        if status in _OPEN or filled_qty < qty:
            if filled_qty > 0:
                return "partial", status or "partially_filled"
            return "pending", status or "open"
        if status in _FAILED:
            return "failed", status

    # Submitted successfully but not yet visible in open/recent snapshots → pending
    if exec_res.get("success") is True or exec_res.get("order_id"):
        return "pending", str(exec_res.get("status") or "submitted")

    return "failed", "no_order_id"


def build_execution_status(
    execution_results: Optional[Dict[str, Any]],
    open_orders: Optional[List[Dict[str, Any]]],
    recent_orders: Optional[List[Dict[str, Any]]],
    *,
    run_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Summarize this run's broker orders for email and diagnostics."""
    run_dt = _parse_run_timestamp(run_timestamp)
    in_rth = is_us_equity_rth(run_dt)
    next_open = next_us_equity_open_after(run_dt)
    next_open_label = next_open.strftime("%a %b %d, %Y %I:%M %p")

    open_by_id, open_by_sym = _index_orders(open_orders or [])
    recent_by_id, recent_by_sym = _index_orders(recent_orders or [])

    by_ticker: Dict[str, Dict[str, Any]] = {}
    counts = {"submitted": 0, "filled": 0, "pending": 0, "partial": 0, "failed": 0}

    for ticker, exec_res in (execution_results or {}).items():
        if ticker == "error" or not isinstance(exec_res, dict):
            continue
        bucket, detail = _classify_ticker_order(
            str(ticker),
            exec_res,
            open_by_id,
            recent_by_id,
            open_by_sym,
            recent_by_sym,
        )
        if bucket == "failed" and not exec_res:
            continue
        counts["submitted"] += 1
        counts[bucket] = counts.get(bucket, 0) + 1
        by_ticker[str(ticker)] = {
            "status": bucket,
            "broker_status": detail,
            "state": execution_state_machine(
                detail,
                int((recent_by_id.get(str(exec_res.get("order_id") or ""), {}) or {}).get("filled_qty") or 0),
                int((recent_by_id.get(str(exec_res.get("order_id") or ""), {}) or {}).get("qty") or 0),
            ),
            "order_id": exec_res.get("order_id"),
            "side": exec_res.get("side"),
            "qty": exec_res.get("qty"),
        }

    note_parts: List[str] = []
    if counts["submitted"] > 0 and not in_rth:
        note_parts.append(
            "This run completed outside US regular market hours (9:30 AM–4:00 PM ET, Mon–Fri)."
        )
        note_parts.append(
            f"Pending orders usually fill at the next session open (~{next_open_label} ET)."
        )
    elif counts["pending"] > 0 and counts["filled"] == 0 and counts["submitted"] > 0:
        note_parts.append(
            "Orders were accepted by the broker but are not filled yet — check Open Orders in Alpaca."
        )

    return {
        "run_in_rth": in_rth,
        "run_timestamp": run_dt.isoformat(),
        "next_open_et": next_open_label,
        "submitted": counts["submitted"],
        "filled": counts["filled"],
        "pending": counts["pending"],
        "partial": counts["partial"],
        "failed": counts["failed"],
        "by_ticker": by_ticker,
        "note": " ".join(note_parts),
        "had_live_execution": counts["submitted"] > 0,
    }


def execution_subject_fragment(status: Dict[str, Any]) -> str:
    """Short subject suffix for weekly email."""
    if not status.get("had_live_execution"):
        return ""
    sub = int(status.get("submitted") or 0)
    filled = int(status.get("filled") or 0)
    pending = int(status.get("pending") or 0) + int(status.get("partial") or 0)
    failed = int(status.get("failed") or 0)
    if sub <= 0:
        return ""
    if failed and not filled and not pending:
        return f"{sub} Failed"
    if pending and not filled:
        return f"{sub} Submitted (pending)"
    if pending and filled:
        return f"{sub} Submitted ({filled} filled, {pending} pending)"
    if filled == sub:
        return f"{sub} Filled"
    return f"{sub} Submitted ({filled} filled)"
