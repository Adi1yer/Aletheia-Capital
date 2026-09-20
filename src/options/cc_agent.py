"""Covered-call decision overlay for ambiguous roll / assign cases.

Rules engine proposes candidates; this module only resolves ``ambiguous`` rows.
It never invents strikes outside the precomputed candidate list.
When ``execute`` is True and broker is provided, ``rewrite`` actions submit STO
and wait for fill.

Debit-policy rejects (profit_take credit / roll debit cap) must NOT be rewritten.
Rewrite qty is capped by live share coverage minus open short calls.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.broker.alpaca import AlpacaBroker

logger = structlog.get_logger()

_DEBIT_REJECT_MARKERS = (
    "profit_take_requires_credit",
    "roll_debit_exceeds_cap",
    "roll_debit_too_large",
    "btc_cost_unknown",
    "no_share_coverage_for_roll_sto",
)


def _is_debit_policy_reject(reason: str) -> bool:
    r = str(reason or "").lower()
    return any(m in r for m in _DEBIT_REJECT_MARKERS)


def _coverage_sto_qty(broker: "AlpacaBroker", underlying: str, requested: int) -> int:
    """Max new short calls = floor(shares/100) − existing short calls (never over-hedge)."""
    from src.options.covered_calls import live_coverage_sto_qty

    return live_coverage_sto_qty(broker, underlying, requested)


def resolve_ambiguous_cc_actions(
    ambiguous_rows: Sequence[Dict[str, Any]],
    *,
    candidate_contracts_by_underlying: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    broker: Optional["AlpacaBroker"] = None,
    execute: bool = False,
) -> List[Dict[str, Any]]:
    """
    Resolve ambiguous lifecycle rows into explicit actions.

    Default policy (no LLM required):
    - Debit-policy rejects → ``hold_assign`` (never STO a forbidden debit roll)
    - If a precomputed roll candidate / ``new_contract`` exists → ``rewrite``
    - Else → ``hold_assign`` (later CC write or atomic unwind)
    """
    cands = candidate_contracts_by_underlying or {}
    out: List[Dict[str, Any]] = []
    for row in ambiguous_rows or []:
        und = str(row.get("underlying") or "").upper()
        reason = str(row.get("reason") or "")
        # Never coerce missing/zero qty to 1 — that over-hedges after partial fills.
        raw_qty = row.get("qty")
        try:
            qty = int(raw_qty) if raw_qty is not None else 0
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0 and not _is_debit_policy_reject(reason):
            out.append(
                {
                    **dict(row),
                    "agent_action": "hold_assign",
                    "agent_contract": None,
                    "agent_reason": "zero_qty_no_rewrite",
                    "status": "agent_resolved",
                    "qty": 0,
                }
            )
            continue

        if _is_debit_policy_reject(reason):
            out.append(
                {
                    **dict(row),
                    "agent_action": "hold_assign",
                    "agent_contract": None,
                    "agent_reason": "debit_policy_reject_no_rewrite",
                    "status": "agent_resolved",
                    "qty": qty,
                }
            )
            continue

        choices = cands.get(und) or []
        preferred = str(row.get("new_contract") or "")
        allowed_syms = {str(c.get("symbol") or "") for c in choices if c.get("symbol")}
        action = "hold_assign"
        contract = None
        agent_reason = "no_valid_roll_candidate"

        if preferred and (not allowed_syms or preferred in allowed_syms):
            action = "rewrite"
            contract = preferred
            agent_reason = "use_precomputed_roll_candidate"
        elif choices:
            action = "rewrite"
            contract = str(choices[0].get("symbol") or "") or None
            agent_reason = "first_precomputed_candidate"

        # Cap rewrite qty by remaining share coverage (and zero out dead retries).
        sto_qty = qty
        if execute and broker and action == "rewrite" and contract:
            sto_qty = _coverage_sto_qty(broker, und, qty)
            if sto_qty <= 0:
                action = "hold_assign"
                contract = None
                agent_reason = "no_uncovered_lot_slots_for_rewrite"

        result = {
            **dict(row),
            "agent_action": action,
            "agent_contract": contract,
            "agent_reason": agent_reason,
            "status": "agent_resolved",
            "qty": sto_qty if action == "rewrite" else qty,
        }

        if execute and broker and action == "rewrite" and contract and sto_qty > 0:
            try:
                filled_total = 0
                last_order = None
                for _ in range(max(1, sto_qty)):
                    slot = _coverage_sto_qty(broker, und, 1)
                    if slot <= 0:
                        break
                    order = broker.submit_option_order(
                        contract_symbol=contract,
                        qty=1,
                        side="sell",
                        order_type="market",
                        wait_fill=True,
                        fill_timeout_s=45.0,
                    )
                    last_order = order
                    ok = bool(order) and order.get("fill_ok") is True
                    if not ok and order and hasattr(broker, "wait_for_order_fill"):
                        oid = str(order.get("order_id") or order.get("id") or "")
                        if oid:
                            fill = broker.wait_for_order_fill(oid, timeout_s=45.0)
                            order["fill"] = fill
                            ok = bool(fill.get("ok"))
                    if ok:
                        filled_total += 1
                    else:
                        break
                result["qty"] = filled_total
                result["order"] = last_order
                if filled_total >= sto_qty:
                    result["status"] = "agent_rewrite_executed"
                elif filled_total > 0:
                    result["status"] = "agent_rewrite_partial"
                    result["requested_qty"] = sto_qty
                else:
                    result["status"] = "agent_rewrite_failed"
            except Exception as e:
                logger.warning("CC agent rewrite failed", underlying=und, error=str(e))
                result["status"] = "agent_rewrite_failed"
                result["reason"] = str(e)[:200]
        out.append(result)
    return out
