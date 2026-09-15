"""Wheel hybrid ($10k) run-config defaults — CC/CSP on, Beat SPY off."""

from __future__ import annotations

from typing import Any, Dict


def apply_wheel_defaults(run_config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply when ``wheel_mode`` is set. Does not fight Beat SPY if that mode wins."""
    out = dict(run_config or {})
    if not bool(out.get("wheel_mode")):
        return out
    if bool(out.get("beat_spy_mode")):
        # Explicit Beat SPY wins if both somehow set.
        return out

    out["enable_covered_calls"] = True
    out["enable_cash_secured_puts"] = True
    out["beat_spy_mode"] = False
    out["beat_spy_concentrated"] = False
    out["phase13_force_cc_lots"] = True
    out.setdefault("wheel_pct", 0.70)
    out.setdefault("directional_pct", 0.30)
    out.setdefault("max_underlying_price", 35.0)
    out.setdefault("min_adv_usd", 5_000_000.0)
    out.setdefault("min_option_oi", 100)
    out.setdefault("max_wheel_names", 4)
    out.setdefault("max_directional_names", 5)
    out.setdefault("wheel_rules_score", 55)
    out.setdefault("min_csp_premium_usd", 25.0)
    out.setdefault("min_csp_annualized_yield_pct", 8.0)
    out.setdefault("max_csp_collateral_pct", 0.45)
    out.setdefault("cash_buffer_pct", 0.06)
    out.setdefault("manage_dte_threshold", 7)
    out.setdefault("manage_itm_pct", 0.02)
    out.setdefault("execute_cutoff_et", "15:30")
    return out
