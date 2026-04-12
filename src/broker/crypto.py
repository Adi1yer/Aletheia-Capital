"""Crypto broker - paper trading (mock) and optional exchange integration.
Set CRYPTO_BROKER_API_KEY and CRYPTO_BROKER_SECRET for live (future exchange integration).
"""

import json
import os
from typing import Dict, List, Optional

import structlog

from src.portfolio.models import Portfolio, Position
from src.portfolio.manager import PortfolioDecision

logger = structlog.get_logger()

DEFAULT_PAPER_CASH = 100000.0
PAPER_STATE_FILE = "data/crypto_paper_state.json"


class CryptoBroker:
    """
    Crypto broker - paper trading by default.
    Tracks virtual positions; no live exchange integration yet.
    """

    def __init__(self, paper: bool = True, paper_cash: float = DEFAULT_PAPER_CASH):
        self.paper = paper
        self._state_file = PAPER_STATE_FILE
        self._cash = paper_cash
        self._positions: Dict[str, Dict] = {}  # symbol -> {qty, avg_price, side}
        self._load_state()

    def _load_state(self):
        if os.path.exists(self._state_file):
            try:
                with open(self._state_file) as f:
                    d = json.load(f)
                self._cash = d.get("cash", self._cash)
                self._positions = d.get("positions", {})
            except Exception as e:
                logger.warning("Could not load crypto paper state", error=str(e))

    def _save_state(self):
        os.makedirs(os.path.dirname(self._state_file) or ".", exist_ok=True)
        try:
            with open(self._state_file, "w") as f:
                json.dump({"cash": self._cash, "positions": self._positions}, f, indent=2)
        except Exception as e:
            logger.warning("Could not save crypto paper state", error=str(e))

    def get_account(self) -> Dict:
        """Get account info (paper: virtual cash/equity)."""
        return {
            "cash": self._cash,
            "buying_power": self._cash,
            "portfolio_value": self._cash,  # Simplified; add position values if needed
            "equity": self._cash,
        }

    def get_positions(self) -> Dict[str, Dict]:
        """Get current crypto positions."""
        return dict(self._positions)

    def execute_order(
        self,
        symbol: str,
        decision: PortfolioDecision,
        price: float = 0.0,  # Pass current price for paper P&L
    ) -> Optional[Dict]:
        """Execute order (paper: update virtual state)."""
        if decision.action in ("hold",) or decision.quantity <= 0:
            return None

        if decision.action in ("buy", "cover"):
            cost = decision.quantity * (price or 1.0)
            if cost > self._cash and self.paper:
                logger.warning("Insufficient paper cash", symbol=symbol, cost=cost, cash=self._cash)
                return None
            self._cash -= cost
            key = symbol.upper()
            if key not in self._positions:
                self._positions[key] = {"qty": 0, "avg_price": 0.0, "side": "long"}
            pos = self._positions[key]
            old_qty, old_avg = pos["qty"], pos["avg_price"]
            new_qty = old_qty + decision.quantity
            pos["avg_price"] = (old_qty * old_avg + decision.quantity * price) / new_qty if new_qty else 0
            pos["qty"] = new_qty
        elif decision.action in ("sell", "short"):
            key = symbol.upper()
            if key not in self._positions:
                self._positions[key] = {"qty": 0, "avg_price": 0.0, "side": "long"}
            pos = self._positions[key]
            qty = pos["qty"] - decision.quantity
            if qty < 0:
                qty = 0
            proceeds = decision.quantity * (price or 1.0)
            self._cash += proceeds
            pos["qty"] = qty

        self._save_state()
        return {"order_id": "paper-" + symbol, "symbol": symbol, "qty": decision.quantity, "status": "filled"}

    def execute_decisions(
        self,
        decisions: Dict[str, PortfolioDecision],
        current_prices: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Optional[Dict]]:
        """Execute crypto decisions (paper mode)."""
        current_prices = current_prices or {}
        results = {}
        for symbol, dec in decisions.items():
            if dec.action in ("hold",) or dec.quantity <= 0:
                continue
            price = current_prices.get(symbol, 0.0)
            results[symbol] = self.execute_order(symbol, dec, price)
        return results

    def sync_portfolio(self) -> Portfolio:
        """Sync to Portfolio model (for pipeline compatibility)."""
        portfolio = Portfolio(cash=self._cash)
        for symbol, pos in self._positions.items():
            qty = pos.get("qty", 0)
            avg = pos.get("avg_price", 0.0)
            if qty > 0:
                portfolio.positions[symbol] = Position(
                    long=qty, short=0, long_cost_basis=avg, short_cost_basis=0.0, short_margin_used=0.0
                )
        return portfolio
