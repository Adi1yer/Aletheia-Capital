"""Optional exit rules for open biotech straddles (+/- % of premium)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from src.biotech.thesis_ledger import open_entries, update_entry

logger = structlog.get_logger()

TAKE_PROFIT_PCT = 50.0
STOP_LOSS_PCT = -50.0


def evaluate_open_straddles_for_exit(
    broker: Any,
    *,
    take_profit_pct: float = TAKE_PROFIT_PCT,
    stop_loss_pct: float = STOP_LOSS_PCT,
) -> List[Dict[str, Any]]:
    """
    Close straddle legs when combined unrealized PnL vs premium crosses thresholds.
    Returns list of actions taken.
    """
    actions: List[Dict[str, Any]] = []
    try:
        positions = broker.get_positions()
        option_positions = broker.get_option_positions()
    except Exception as e:
        logger.warning("Exit policy: could not load positions", error=str(e))
        return actions

    opt_mv: Dict[str, float] = {}
    for op in option_positions or []:
        if isinstance(op, dict):
            sym = str(op.get("symbol") or "")
            if sym:
                opt_mv[sym] = float(op.get("market_value") or 0)

    for row in open_entries():
        trade_id = str(row.get("trade_id") or "")
        call_sym = str(row.get("call_contract") or "")
        put_sym = str(row.get("put_contract") or "")
        premium = float(row.get("premium_filled_usd") or row.get("premium_est_usd") or 0)
        if premium <= 0 or not trade_id:
            continue
        current_val = abs(opt_mv.get(call_sym, 0)) + abs(opt_mv.get(put_sym, 0))
        if current_val <= 0:
            continue
        pnl = current_val - premium
        pnl_pct = pnl / premium * 100.0
        if pnl_pct >= take_profit_pct or pnl_pct <= stop_loss_pct:
            closed = _close_legs(broker, call_sym, put_sym, positions)
            if closed:
                update_entry(
                    trade_id,
                    {
                        "status": "closed",
                        "straddle_pnl_usd": round(pnl, 2),
                        "pnl_pct_of_premium": round(pnl_pct, 2),
                        "exit_reason": "take_profit" if pnl_pct > 0 else "stop_loss",
                    },
                )
                actions.append(
                    {
                        "trade_id": trade_id,
                        "ticker": row.get("ticker"),
                        "pnl_pct": round(pnl_pct, 2),
                        "closed_legs": closed,
                    }
                )
    return actions


def _close_legs(
    broker: Any,
    call_sym: str,
    put_sym: str,
    positions: Dict[str, Any],
) -> List[str]:
    """Submit sell-to-close for long option legs if held."""
    closed: List[str] = []
    for sym in (call_sym, put_sym):
        if not sym:
            continue
        pos = positions.get(sym) if isinstance(positions, dict) else None
        if not pos:
            continue
        qty = int(pos.get("qty") or 0)
        if qty <= 0:
            continue
        try:
            broker.submit_option_order(
                contract_symbol=sym,
                qty=qty,
                side="sell",
                order_type="market",
            )
            closed.append(sym)
        except Exception as e:
            logger.warning("Failed to close leg", symbol=sym, error=str(e))
    return closed
