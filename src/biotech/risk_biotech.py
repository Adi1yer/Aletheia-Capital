"""Paper-account risk caps for biotech options (relative to equity, not fixed dollars)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class BiotechRiskBudget:
    """Caps expressed as fractions of account equity (paper)."""

    max_premium_pct_equity: float = 0.02
    max_contracts_per_leg: int = 1

    def max_premium_dollars(self, equity: float, *, arm_fraction: float = 1.0) -> float:
        frac = max(0.0, min(1.0, float(arm_fraction)))
        return max(0.0, float(equity) * float(self.max_premium_pct_equity) * frac)

    def per_arm_budget(self, equity: float) -> "BiotechRiskBudget":
        """Split equity cap 50/50 when running mechanical + LLM-gated arms."""
        half = float(self.max_premium_pct_equity) * 0.5
        return BiotechRiskBudget(
            max_premium_pct_equity=half,
            max_contracts_per_leg=self.max_contracts_per_leg,
        )


def equity_from_alpaca_account(acct: Dict) -> float:
    for k in ("equity", "portfolio_value"):
        v = acct.get(k)
        if v is not None:
            return float(v)
    return float(acct.get("cash", 0) or 0)
