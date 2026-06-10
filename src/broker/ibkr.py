"""Interactive Brokers adapter (paper via IB Gateway). Dry-run when gateway unavailable."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from src.broker.registry import WorkflowAccount

logger = structlog.get_logger()


class IBKRBroker:
    """Minimal IBKR broker: connects via ib_insync when available, else dry-run."""

    def __init__(self, workflow: WorkflowAccount, *, dry_run: Optional[bool] = None):
        self.workflow = workflow
        self.account_id = (os.environ.get(workflow.account_id_env) or "").strip()
        self.host = (os.environ.get("IBKR_GATEWAY_HOST") or os.environ.get("IBKR_HOST") or "127.0.0.1").strip()
        self.port = int(os.environ.get("IBKR_GATEWAY_PORT") or os.environ.get("IBKR_PORT") or "4002")
        self.client_id = int(os.environ.get("IBKR_CLIENT_ID") or "1")
        self._ib = None
        self.dry_run = dry_run if dry_run is not None else not self.account_id

    def connect(self) -> bool:
        if self.dry_run:
            logger.info("IBKR dry-run mode", workflow=self.workflow.workflow_id)
            return False
        try:
            from ib_insync import IB

            self._ib = IB()
            self._ib.connect(self.host, self.port, clientId=self.client_id, timeout=15)
            if self.account_id:
                self._ib.reqAccountSummary()
            logger.info(
                "IBKR connected",
                workflow=self.workflow.workflow_id,
                account=self.account_id,
            )
            return True
        except ImportError:
            logger.warning("ib_insync not installed; IBKR dry-run")
            self.dry_run = True
            return False
        except Exception as e:
            logger.warning("IBKR connect failed; dry-run", error=str(e))
            self.dry_run = True
            return False

    def disconnect(self) -> None:
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()

    def get_account(self) -> Dict[str, Any]:
        if self.dry_run or not self._ib or not self._ib.isConnected():
            return {
                "cash": 100_000.0,
                "buying_power": 100_000.0,
                "portfolio_value": 100_000.0,
                "equity": 100_000.0,
                "dry_run": True,
            }
        summary = {}
        for av in self._ib.accountSummary(self.account_id):
            summary[av.tag] = av.value
        equity = float(summary.get("NetLiquidation") or summary.get("EquityWithLoanValue") or 0)
        cash = float(summary.get("TotalCashValue") or summary.get("CashBalance") or 0)
        return {
            "cash": cash,
            "buying_power": float(summary.get("BuyingPower") or equity),
            "portfolio_value": equity,
            "equity": equity,
            "dry_run": False,
        }

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        if self.dry_run or not self._ib or not self._ib.isConnected():
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for pos in self._ib.positions(self.account_id):
            sym = getattr(pos.contract, "symbol", "") or getattr(pos.contract, "localSymbol", "")
            qty = float(pos.position)
            side = "long" if qty >= 0 else "short"
            out[sym] = {
                "qty": int(abs(qty)),
                "side": side,
                "market_value": float(pos.marketValue or 0),
                "avg_entry_price": float(pos.avgCost or 0),
            }
        return out

    def place_market_order(
        self,
        symbol: str,
        quantity: float,
        side: str,
        *,
        sec_type: str = "CASH",
        exchange: str = "IDEALPRO",
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """Place order or log dry-run intent."""
        if self.dry_run or not self._ib or not self._ib.isConnected():
            row = {
                "symbol": symbol,
                "quantity": quantity,
                "side": side,
                "status": "dry_run",
                "submitted_at": datetime.utcnow().isoformat() + "Z",
            }
            logger.info("IBKR dry-run order", **row)
            return row
        from ib_insync import Forex, Future, MarketOrder

        if sec_type == "CASH":
            contract = Forex(symbol[:3] + symbol[3:] if len(symbol) == 6 else symbol)
        elif sec_type == "FUT":
            contract = Future(symbol=symbol, exchange=exchange, currency=currency)
        else:
            contract = Forex(symbol)
        self._ib.qualifyContracts(contract)
        order = MarketOrder("BUY" if side.lower() == "buy" else "SELL", abs(quantity))
        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(1)
        return {
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "status": str(trade.orderStatus.status),
            "order_id": trade.order.orderId,
        }
