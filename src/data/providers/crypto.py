"""Crypto data provider - CoinGecko API for prices and metrics (optional COINGECKO_API_KEY)."""

import os
from datetime import datetime
from typing import List, Optional, Dict, Any

import structlog

from src.data.models import Price, FinancialMetrics, LineItem, InsiderTrade, CompanyNews
from src.data.providers.base import DataProvider

logger = structlog.get_logger()

# Map common symbols to CoinGecko ids
CRYPTO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "ETC": "ethereum-classic",
    "NEAR": "near",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "INJ": "injective-protocol",
    "TIA": "celestia",
    "SUI": "sui",
    "SEI": "sei-network",
    "RUNE": "thorchain",
    "FTM": "fantom",
    "AAVE": "aave",
    "CRV": "curve-dao-token",
    "MKR": "maker",
    "SNX": "havven",
}


class CryptoProvider(DataProvider):
    """CoinGecko API for crypto prices and market data."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("COINGECKO_API_KEY")
        self.base_url = "https://api.coingecko.com/api/v3"
        self._client = None

    def _coin_id(self, symbol: str) -> str:
        sym = symbol.upper()
        return CRYPTO_IDS.get(sym, symbol.lower())

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        try:
            import requests
            url = f"{self.base_url}{path}"
            p = params or {}
            if self.api_key:
                p["x_cg_demo_api_key"] = self.api_key  # CoinGecko demo key header
            r = requests.get(url, params=p, headers={"User-Agent": "AI-Hedge-Fund/1.0"}, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug("CoinGecko request failed", path=path, error=str(e))
            return None

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> List[Price]:
        """Fetch OHLC prices from CoinGecko. Ticker should be BTC, ETH, etc."""
        coin_id = self._coin_id(ticker)
        try:
            from dateutil import parser as date_parser
            end_dt = date_parser.parse(end_date)
            start_dt = date_parser.parse(start_date)
            days = max(1, (end_dt - start_dt).days)
        except Exception:
            days = 90

        data = self._get(f"/coins/{coin_id}/ohlc", params={"vs_currency": "usd", "days": str(days)})
        if not data or not isinstance(data, list):
            return []

        out: List[Price] = []
        for bar in data:
            if len(bar) >= 5:
                ts, o, h, l, c = bar[0], bar[1], bar[2], bar[3], bar[4]
                vol = int(bar[5]) if len(bar) > 5 else 0
                out.append(Price(
                    time=datetime.fromtimestamp(ts / 1000),
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    volume=vol,
                ))
        return out

    def get_financial_metrics(
        self, ticker: str, end_date: str, period: str = "ttm", limit: int = 10
    ) -> List[FinancialMetrics]:
        """Crypto metrics: market cap, etc. from CoinGecko."""
        coin_id = self._coin_id(ticker)
        data = self._get(f"/coins/{coin_id}", params={"localization": "false"})
        if not data or not isinstance(data, dict):
            return []

        m = data.get("market_data") or {}
        mc = m.get("market_cap", {}).get("usd")
        return [FinancialMetrics(
            ticker=ticker,
            report_period=datetime.now(),
            market_cap=float(mc) if mc else None,
        )]

    def get_line_items(
        self,
        ticker: str,
        line_items: List[str],
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> List[LineItem]:
        return []

    def get_crypto_metrics(self, symbol: str) -> Dict[str, Any]:
        """Get crypto-specific metrics (market cap, volume, etc.)."""
        coin_id = self._coin_id(symbol)
        data = self._get(f"/coins/{coin_id}", params={"localization": "false"})
        if not data or not isinstance(data, dict):
            return {}

        m = data.get("market_data") or {}
        mc = m.get("market_cap")
        mc_usd = mc.get("usd") if isinstance(mc, dict) else mc
        vol = m.get("total_volume")
        vol_usd = vol.get("usd") if isinstance(vol, dict) else vol
        cp = m.get("current_price")
        price_usd = cp.get("usd") if isinstance(cp, dict) else cp
        return {
            "market_cap_usd": mc_usd,
            "total_volume_usd": vol_usd,
            "price_usd": price_usd,
            "price_change_24h": m.get("price_change_percentage_24h"),
        }
