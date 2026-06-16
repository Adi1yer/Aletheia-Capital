"""Stateful order reconciliation loop for unresolved orders."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


def reconcile_orders(
    *,
    broker: Any,
    max_polls: int = 3,
) -> Dict[str, Any]:
    transitions: List[Dict[str, Any]] = []
    unresolved = set()
    for _ in range(max(1, int(max_polls))):
        open_orders = broker.get_open_orders(limit=100) if broker else []
        recent_orders = broker.get_recent_orders(limit=100) if broker else []
        by_id = {str(o.get("id") or o.get("order_id") or ""): o for o in (recent_orders or [])}
        for o in open_orders or []:
            oid = str(o.get("id") or o.get("order_id") or "")
            unresolved.add(oid)
            row = by_id.get(oid) or o
            transitions.append(
                {
                    "order_id": oid,
                    "symbol": row.get("symbol"),
                    "status": row.get("status"),
                    "filled_qty": int(row.get("filled_qty") or 0),
                    "qty": int(row.get("qty") or 0),
                    "observed_at": datetime.utcnow().isoformat() + "Z",
                }
            )
        if not open_orders:
            break
    return {"unresolved_count": len(unresolved), "transitions": transitions}

