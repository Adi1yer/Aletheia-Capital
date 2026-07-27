"""Guards against comparing paper-account resets to stale prior equity."""

from __future__ import annotations

from typing import Any, Dict, Optional

# Reject prior equity when book size clearly jumped (account swap / cache poison).
MAX_EQUITY_RATIO = 2.0
MIN_EQUITY_RATIO = 0.5


def compatible_prior_equity(
    equity_now: Optional[float],
    equity_prev: Optional[float],
    *,
    max_ratio: float = MAX_EQUITY_RATIO,
    min_ratio: float = MIN_EQUITY_RATIO,
) -> Optional[float]:
    """
    Return equity_prev only if it is comparable to equity_now.

    A ~$100k → ~$10k jump (paper account reset + stale Actions cache) must not
    produce −90% “active return” and poison auto-throttle / outlook.
    """
    if equity_prev is None or equity_now is None:
        return None
    try:
        now = float(equity_now)
        prev = float(equity_prev)
    except (TypeError, ValueError):
        return None
    if now <= 0 or prev <= 0:
        return None
    ratio = now / prev
    if ratio > max_ratio or ratio < min_ratio:
        return None
    return prev


def sanitize_prior_context(
    prior: Dict[str, Any],
    *,
    equity_now: Optional[float],
) -> Dict[str, Any]:
    """Drop incompatible prev equity / do-nothing fields in place and return prior."""
    out = dict(prior or {})
    prev = compatible_prior_equity(equity_now, out.get("prev_equity"))
    if prev is None and out.get("prev_equity") is not None:
        out["prev_equity"] = None
        out["do_nothing_equity"] = None
        out["do_nothing_return_pct"] = None
        out["prior_equity_rejected"] = True
        out["prior_equity_reject_reason"] = "incompatible_account_scale"
    else:
        out["prev_equity"] = prev
        out["prior_equity_rejected"] = False
    return out
