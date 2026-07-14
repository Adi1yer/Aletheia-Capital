"""Close or mark ghost biotech straddles (past catalyst, no topline)."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import structlog

from src.biotech.readout_window import is_ghost_catalyst, parse_iso_date
from src.biotech.models import TrialSummary
from src.biotech.thesis_ledger import open_entries, update_entry

logger = structlog.get_logger()


def _row_looks_ghost(row: Dict[str, Any], today: date) -> bool:
    rd = parse_iso_date(str(row.get("readout_date") or row.get("catalyst_date") or ""))
    if rd is None:
        # Fall back: catalyst blob may embed date
        cat = row.get("catalyst") or {}
        if isinstance(cat, dict):
            rd = parse_iso_date(str(cat.get("readout_date") or cat.get("primary_completion_date") or ""))
    if rd is None or rd >= today:
        return False
    # Treat as ghost if no results flag on row
    if row.get("has_results") or row.get("results_first_posted"):
        return False
    trial = TrialSummary(
        nct_id=str(row.get("nct_id") or ""),
        primary_completion_date=rd.isoformat(),
        has_results=False,
    )
    return is_ghost_catalyst(trial, today)


def prune_ghost_open_straddles(
    broker: Any = None,
    *,
    today: Optional[date] = None,
    close_legs: bool = True,
) -> List[Dict[str, Any]]:
    """
    For open mechanical (or any) straddles whose catalyst primary is past with no topline:
    optionally close option legs on the paper broker and mark ledger closed/expired.
    """
    today = today or date.today()
    actions: List[Dict[str, Any]] = []
    try:
        from src.biotech.exit_policy import _close_legs
    except Exception:
        _close_legs = None  # type: ignore

    positions = None
    if broker is not None and close_legs and _close_legs is not None:
        try:
            positions = broker.get_positions()
        except Exception as e:
            logger.warning("Ghost prune: could not load positions", error=str(e))

    for row in open_entries():
        if not _row_looks_ghost(row, today):
            continue
        trade_id = str(row.get("trade_id") or "")
        if not trade_id:
            continue
        closed_legs = False
        if broker is not None and close_legs and _close_legs is not None and positions is not None:
            try:
                closed_legs = bool(
                    _close_legs(
                        broker,
                        str(row.get("call_contract") or ""),
                        str(row.get("put_contract") or ""),
                        positions,
                    )
                )
            except Exception as e:
                logger.warning("Ghost prune close failed", trade_id=trade_id, error=str(e))
        update_entry(
            trade_id,
            {
                "status": "expired" if not closed_legs else "closed",
                "exit_reason": "ghost_catalyst_past_no_topline",
                "ghost_pruned": True,
            },
        )
        actions.append(
            {
                "trade_id": trade_id,
                "ticker": row.get("ticker"),
                "arm": row.get("arm"),
                "closed_legs": closed_legs,
                "reason": "ghost_catalyst_past_no_topline",
            }
        )
        logger.info("Ghost straddle pruned", trade_id=trade_id, ticker=row.get("ticker"))
    return actions
