"""Congressional stock trading data provider (STOCK Act disclosures).
Uses Finnhub congressional endpoint when FINNHUB_API_KEY is set, or FinBrain when CONGRESSIONAL_API_KEY is set.
"""

import os
from datetime import datetime
from typing import List, Optional, Dict, Any

import structlog

from src.data.providers.base import DataProvider
from src.data.models import Price, FinancialMetrics, LineItem, InsiderTrade, CompanyNews

logger = structlog.get_logger()


def _parse_date(s: Any) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    if isinstance(s, str):
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        try:
            from dateutil import parser as date_parser
            return date_parser.parse(s)
        except Exception:
            pass
    return None


class CongressionalProvider(DataProvider):
    """
    Congressional trading data (House/Senate disclosures under STOCK Act).
    Tries Finnhub first (FINNHUB_API_KEY), then FinBrain (CONGRESSIONAL_API_KEY).
    """

    def __init__(
        self,
        finnhub_api_key: Optional[str] = None,
        congressional_api_key: Optional[str] = None,
    ):
        self.finnhub_key = finnhub_api_key or os.getenv("FINNHUB_API_KEY")
        self.congressional_key = congressional_api_key or os.getenv("CONGRESSIONAL_API_KEY")
        self.finnhub_base = "https://finnhub.io/api/v1"
        self.finbrain_base = "https://api.finbrain.tech"

    def _finnhub_get(self, path: str, params: Optional[Dict[str, str]] = None) -> Any:
        if not self.finnhub_key:
            return None
        try:
            import urllib.request
            import urllib.parse
            p = dict(params or {})
            p["token"] = self.finnhub_key
            url = f"{self.finnhub_base}{path}?{urllib.parse.urlencode(p)}"
            req = urllib.request.Request(url, headers={"User-Agent": "AI-Hedge-Fund/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                import json
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.debug("Finnhub congressional request failed", path=path, error=str(e))
            return None

    def _finbrain_get(self, ticker: str, date_from: Optional[str] = None, date_to: Optional[str] = None) -> Any:
        if not self.congressional_key:
            return None
        try:
            import urllib.request
            import urllib.parse
            params: Dict[str, str] = {"token": self.congressional_key}
            if date_from:
                params["dateFrom"] = date_from
            if date_to:
                params["dateTo"] = date_to
            url = f"{self.finbrain_base}/v1/housetrades/us/{ticker}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers={"User-Agent": "AI-Hedge-Fund/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                import json
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.debug("FinBrain house trades request failed", ticker=ticker, error=str(e))
            return None

    def get_congressional_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Fetch congressional trades for a ticker.
        Returns list of dicts: {date, name, transaction_type, amount_range, party}.
        """
        out: List[Dict[str, Any]] = []

        # Try Finnhub (congressional trading endpoint)
        if self.finnhub_key:
            raw = self._finnhub_get("/stock/congressional-trading", params={"symbol": ticker})
            if raw:
                data = raw.get("data") or raw.get("trades") or raw if isinstance(raw, list) else []
                if isinstance(data, list):
                    for t in data[:limit]:
                        try:
                            dt = _parse_date(t.get("transactionDate") or t.get("date") or t.get("filingDate"))
                            name = t.get("representative") or t.get("politicianName") or t.get("name") or "Unknown"
                            tx = (t.get("transactionType") or t.get("transaction") or "unknown").lower()
                            tx_type = "buy" if "purchase" in tx or tx == "buy" else "sell" if "sale" in tx or tx == "sell" else "unknown"
                            amount = t.get("amount") or t.get("amountRange") or t.get("value")
                            out.append({
                                "date": dt.isoformat() if dt else None,
                                "name": str(name),
                                "transaction_type": tx_type,
                                "amount_range": str(amount) if amount else None,
                                "party": t.get("party"),
                            })
                        except Exception as e:
                            logger.debug("Parse congressional trade failed", error=str(e))

        if out:
            return out[:limit]

        # Try FinBrain
        if self.congressional_key:
            raw = self._finbrain_get(ticker, start_date, end_date)
            if raw:
                data = raw.get("data") or raw.get("trades") or raw if isinstance(raw, list) else []
                if isinstance(data, list):
                    for t in data[:limit]:
                        try:
                            dt = _parse_date(t.get("transactionDate") or t.get("date"))
                            name = t.get("representative") or t.get("politicianName") or "Unknown"
                            tx = (t.get("transactionType") or t.get("transaction") or "unknown").lower()
                            tx_type = "buy" if "purchase" in tx or tx == "buy" else "sell" if "sale" in tx or tx == "sell" else "unknown"
                            amount = t.get("amount") or t.get("amountRange")
                            out.append({
                                "date": dt.isoformat() if dt else None,
                                "name": str(name),
                                "transaction_type": tx_type,
                                "amount_range": str(amount) if amount else None,
                                "party": t.get("party"),
                            })
                        except Exception as e:
                            logger.debug("Parse FinBrain trade failed", error=str(e))

        return out[:limit]

    def get_prices(self, ticker: str, start_date: str, end_date: str) -> List[Price]:
        return []

    def get_financial_metrics(
        self, ticker: str, end_date: str, period: str = "ttm", limit: int = 10
    ) -> List[FinancialMetrics]:
        return []

    def get_line_items(
        self,
        ticker: str,
        line_items: List[str],
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> List[LineItem]:
        return []
