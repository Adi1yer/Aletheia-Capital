"""Finnhub data provider: insider transactions and analyst recommendations (requires FINNHUB_API_KEY)."""

import os
from datetime import datetime
from typing import List, Optional, Any, Dict

import structlog

from src.data.models import Price, FinancialMetrics, LineItem, InsiderTrade, CompanyNews
from src.data.providers.base import DataProvider

logger = structlog.get_logger()


class FinnhubProvider(DataProvider):
    """
    Finnhub API: insider transactions and analyst recommendation trends.
    Free tier: 60 calls/min. Implements only get_insider_trades; other methods return [].
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY")
        self.base_url = "https://finnhub.io/api/v1"
        if not self.api_key:
            logger.debug("Finnhub API key not set; provider will return no data")

    def _get(self, path: str, params: Optional[Dict[str, str]] = None) -> Any:
        if not self.api_key:
            return None
        try:
            import urllib.request
            import urllib.parse
            p = params or {}
            p["token"] = self.api_key
            url = f"{self.base_url}{path}?{urllib.parse.urlencode(p)}"
            req = urllib.request.Request(url, headers={"User-Agent": "AI-Hedge-Fund/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                import json
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.debug("Finnhub request failed", path=path, error=str(e))
            return None

    def get_prices(self, ticker: str, start_date: str, end_date: str) -> List[Price]:
        """Not provided by Finnhub in this integration; use Yahoo."""
        return []

    def get_financial_metrics(
        self, ticker: str, end_date: str, period: str = "ttm", limit: int = 10
    ) -> List[FinancialMetrics]:
        """Not provided by this integration; use Yahoo."""
        return []

    def get_line_items(
        self,
        ticker: str,
        line_items: List[str],
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> List[LineItem]:
        """Not provided by this integration; use Yahoo."""
        return []

    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: Optional[str] = None,
        limit: int = 1000,
    ) -> List[InsiderTrade]:
        """Fetch insider transactions from Finnhub (stock/insider-transactions)."""
        if not self.api_key:
            return []
        raw = self._get("/stock/insider-transactions", params={"symbol": ticker})
        # API returns { "data": [...] } or { "insiderTransactions": [...] }
        transactions = raw.get("data") or raw.get("insiderTransactions") if isinstance(raw, dict) else None
        if not transactions or not isinstance(transactions, list):
            return []
        out: List[InsiderTrade] = []
        for t in transactions[:limit]:
            try:
                # Finnhub: date, SECForm4Date, transaction, cost, shares, USDValue
                filing_date = t.get("SECForm4Date") or t.get("filingDate") or t.get("date")
                if isinstance(filing_date, str) and "T" in filing_date:
                    fd = datetime.fromisoformat(filing_date.replace("Z", "+00:00"))
                elif isinstance(filing_date, str):
                    from dateutil import parser as date_parser
                    fd = date_parser.parse(filing_date)
                else:
                    fd = datetime.now()
                tx_type = t.get("transactionType") or t.get("transaction") or t.get("transactionCode") or ""
                shares = t.get("shares") or t.get("share") or t.get("change")
                if shares is not None and int(shares) < 0:
                    tx_type = tx_type or "Sale"
                elif shares is not None and int(shares) > 0:
                    tx_type = tx_type or "Buy"
                price = t.get("cost") or t.get("price")
                value = t.get("USDValue") or t.get("value")
                if value is None and shares is not None and price is not None:
                    value = int(shares) * float(price)
                out.append(
                    InsiderTrade(
                        ticker=ticker,
                        filing_date=fd,
                        transaction_date=None,
                        transaction_type=str(tx_type) if tx_type else None,
                        shares=int(shares) if shares is not None else None,
                        price=float(price) if price is not None else None,
                        value=float(value) if value is not None else None,
                    )
                )
            except Exception as e:
                logger.debug("Parse insider trade failed", ticker=ticker, item=t, error=str(e))
        if out:
            logger.info("Fetched insider trades", ticker=ticker, count=len(out))
        return out

    def get_analyst_recommendations(self, ticker: str) -> List[Dict[str, Any]]:
        """
        Analyst recommendation trends (strongBuy, buy, hold, sell, strongSell).
        Returns list of period summaries for use in prompts. Not part of DataProvider base.
        """
        if not self.api_key:
            return []
        raw = self._get("/stock/recommendation", params={"symbol": ticker})
        if not raw or not isinstance(raw, list):
            return []
        out = []
        for r in raw[:12]:  # last 12 periods
            if isinstance(r, dict):
                out.append({
                    "period": r.get("period"),
                    "strongBuy": r.get("strongBuy"),
                    "buy": r.get("buy"),
                    "hold": r.get("hold"),
                    "sell": r.get("sell"),
                    "strongSell": r.get("strongSell"),
                })
        if out:
            logger.info("Fetched analyst recommendations", ticker=ticker, count=len(out))
        return out
