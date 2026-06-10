"""Resolve open biotech thesis ledger rows (PnL, readout moves, clinical tags)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.biotech.clinical_outcome import clinical_outcome_from_status, refresh_trial_status
from src.biotech.thesis_ledger import _read_lines, _write_lines, open_entries, update_entry

logger = structlog.get_logger()


def _underlying_price(ticker: str) -> float:
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="5d")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


def _price_on_date(ticker: str, target: date) -> float:
    try:
        import yfinance as yf

        start = target - timedelta(days=5)
        end = target + timedelta(days=2)
        hist = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat())
        if hist is None or hist.empty:
            return _underlying_price(ticker)
        # nearest row on or after target
        for idx in sorted(hist.index):
            d = idx.date() if hasattr(idx, "date") else idx
            if d >= target:
                return float(hist.loc[idx]["Close"])
        return float(hist["Close"].iloc[-1])
    except Exception:
        return _underlying_price(ticker)


def _option_symbols_open(broker: Any) -> set:
    syms = set()
    try:
        for op in broker.get_option_positions() or []:
            if isinstance(op, dict) and op.get("symbol"):
                syms.add(str(op["symbol"]))
    except Exception:
        pass
    return syms


def _straddle_market_value(broker: Any, call_sym: str, put_sym: str) -> float:
    """Sum market value of open long legs if still held."""
    total = 0.0
    try:
        positions = broker.get_positions()
        for sym in (call_sym, put_sym):
            pos = positions.get(sym) if isinstance(positions, dict) else None
            if pos:
                total += abs(float(pos.get("market_value") or 0))
    except Exception:
        pass
    return total


def resolve_open_thesis_entries(
    broker: Optional[Any] = None,
    *,
    price_fn: Optional[Callable[[str], float]] = None,
    path: Optional[Any] = None,
    today: Optional[date] = None,
) -> int:
    """
    Close or enrich open thesis rows: legs gone from book → realized PnL;
    after readout date → underlying move windows + clinical outcome.
    """
    from src.biotech.thesis_ledger import _ledger_path

    today = today or date.today()
    p = _ledger_path(path)
    rows = _read_lines(p)
    open_syms = _option_symbols_open(broker) if broker else set()
    px_fn = price_fn or _underlying_price
    resolved = 0

    for i, row in enumerate(rows):
        status = str(row.get("status") or "")
        if status not in ("filled", "open", "submitted", "partial"):
            continue

        trade_id = str(row.get("trade_id") or "")
        ticker = str(row.get("ticker") or "").upper()
        call_sym = str(row.get("call_contract") or "")
        put_sym = str(row.get("put_contract") or "")
        premium = float(row.get("premium_filled_usd") or row.get("premium_est_usd") or 0)
        entry_d = _parse_date(str(row.get("entry_date") or row.get("run_date") or "")[:10])
        readout_d = _parse_date(str(row.get("readout_date_expected") or "")[:10])
        nct_id = str(row.get("nct_id") or "")
        company = str(row.get("trial_title") or ticker)

        updates: Dict[str, Any] = {}

        legs_open = bool(
            broker
            and (
                (call_sym and call_sym in open_syms)
                or (put_sym and put_sym in open_syms)
            )
        )

        if (
            broker
            and (call_sym or put_sym)
            and not legs_open
            and premium > 0
            and status in ("filled", "open", "partial")
        ):
            # Position closed — estimate PnL from last known value (0 if expired worthless)
            exit_val = _straddle_market_value(broker, call_sym, put_sym)
            pnl = exit_val - premium
            updates["status"] = "closed"
            updates["straddle_pnl_usd"] = round(pnl, 2)
            updates["pnl_pct_of_premium"] = round(pnl / premium * 100.0, 2) if premium else 0.0
            updates["resolved_at"] = datetime.utcnow().isoformat() + "Z"

        if readout_d and readout_d <= today:
            entry_px = float(row.get("underlying_px_entry") or 0)
            if entry_px <= 0:
                entry_px = px_fn(ticker) if ticker else 0.0
                updates["underlying_px_entry"] = entry_px
            if entry_d:
                updates["underlying_px_1d"] = _price_on_date(ticker, entry_d + timedelta(days=1))
                updates["underlying_px_5d"] = _price_on_date(ticker, entry_d + timedelta(days=5))
                updates["underlying_px_20d"] = _price_on_date(ticker, entry_d + timedelta(days=20))
            fresh_status = refresh_trial_status(nct_id, company)
            if fresh_status:
                updates["trial_status"] = fresh_status
                updates["clinical_outcome"] = clinical_outcome_from_status(fresh_status)
            elif row.get("trial_status"):
                updates["clinical_outcome"] = clinical_outcome_from_status(
                    str(row.get("trial_status") or "")
                )

        expiry_d = _parse_date(str(row.get("expiry") or "")[:10])
        if expiry_d and expiry_d < today and updates.get("status") not in ("closed",):
            if premium > 0 and "straddle_pnl_usd" not in updates:
                updates["status"] = "expired"
                updates["straddle_pnl_usd"] = round(-premium, 2)
                updates["pnl_pct_of_premium"] = -100.0
                updates["resolved_at"] = datetime.utcnow().isoformat() + "Z"

        if updates:
            rows[i] = {**row, **updates}
            resolved += 1
            logger.info(
                "Resolved biotech thesis row",
                trade_id=trade_id,
                ticker=ticker,
                status=rows[i].get("status"),
            )

    if resolved:
        _write_lines(rows, p)
    return resolved


def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
