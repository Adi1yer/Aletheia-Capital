"""Reliable equity quotes for biotech pipeline (CI-safe: Alpaca/Finnhub before yfinance)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

import structlog

from src.config.settings import settings

logger = structlog.get_logger()

_BIOTECH_INDUSTRY_HINTS = (
    "biotech",
    "biotechnology",
    "drug",
    "pharmaceutical",
    "life sciences",
)


def _biotech_alpaca_credentials() -> tuple[str, str]:
    key = (settings.biotech_alpaca_api_key or "").strip()
    secret = (settings.biotech_alpaca_secret_key or "").strip()
    return key, secret


def _price_from_alpaca(ticker: str, api_key: str, secret_key: str) -> Optional[float]:
    if not api_key or not secret_key:
        return None
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest

        client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)
        req = StockLatestQuoteRequest(symbol_or_symbols=ticker.upper())
        quotes = client.get_stock_latest_quote(req)
        q = quotes.get(ticker.upper()) if quotes else None
        if q is None:
            return None
        for val in (getattr(q, "ask_price", None), getattr(q, "bid_price", None)):
            if val is not None:
                try:
                    px = float(val)
                    if px > 0:
                        return px
                except (TypeError, ValueError):
                    continue
    except Exception as e:
        logger.debug("Alpaca quote failed", ticker=ticker, error=str(e))

    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)
        end = date.today()
        start = end - timedelta(days=5)
        req = StockBarsRequest(
            symbol_or_symbols=ticker.upper(),
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        bars = client.get_stock_bars(req)
        bar_list = bars.data.get(ticker.upper()) if bars and bars.data else None
        if bar_list:
            close = float(bar_list[-1].close)
            if close > 0:
                return close
    except Exception as e:
        logger.debug("Alpaca bars failed", ticker=ticker, error=str(e))
    return None


def _price_from_finnhub(ticker: str) -> Optional[float]:
    key = (settings.finnhub_api_key or "").strip()
    if not key:
        return None
    try:
        from src.data.providers.finnhub import FinnhubProvider

        return FinnhubProvider(api_key=key).get_latest_quote(ticker)
    except Exception as e:
        logger.debug("Finnhub quote failed", ticker=ticker, error=str(e))
        return None


def _price_from_yfinance(ticker: str) -> Optional[float]:
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker.upper()).history(period="5d")
        if hist is not None and not hist.empty:
            px = float(hist["Close"].iloc[-1])
            if px > 0:
                return px
    except Exception as e:
        logger.debug("yfinance price failed", ticker=ticker, error=str(e))
    return None


def get_last_price(
    ticker: str,
    *,
    alpaca_key: str = "",
    alpaca_secret: str = "",
) -> Optional[float]:
    """Layered last price: Alpaca → Finnhub → yfinance."""
    t = ticker.upper().strip()
    ak = (alpaca_key or "").strip() or _biotech_alpaca_credentials()[0]
    sec = (alpaca_secret or "").strip() or _biotech_alpaca_credentials()[1]

    for fetch in (
        lambda: _price_from_alpaca(t, ak, sec),
        lambda: _price_from_finnhub(t),
        lambda: _price_from_yfinance(t),
    ):
        px = fetch()
        if px is not None and px > 0:
            return px
    return None


def _profile_from_finnhub(ticker: str) -> Dict[str, Any]:
    key = (settings.finnhub_api_key or "").strip()
    if not key:
        return {}
    try:
        from src.data.providers.finnhub import FinnhubProvider

        return FinnhubProvider(api_key=key).get_company_profile(ticker) or {}
    except Exception:
        return {}


def _profile_from_yfinance(ticker: str) -> Dict[str, Any]:
    try:
        import yfinance as yf

        info = yf.Ticker(ticker.upper()).info or {}
        sector = str(info.get("sector") or "")
        industry = str(info.get("industry") or "")
        mc = info.get("marketCap")
        market_cap = float(mc) if mc is not None else None
        hist = yf.Ticker(ticker.upper()).history(period="1mo")
        avg_dv = 0.0
        if hist is not None and not hist.empty:
            avg_dv = float((hist["Close"] * hist["Volume"]).mean())
        has_opts = False
        try:
            has_opts = bool(getattr(yf.Ticker(ticker.upper()), "options", []) or [])
        except Exception:
            pass
        return {
            "company_name": info.get("longName") or info.get("shortName") or ticker,
            "sector": sector,
            "industry": industry,
            "market_cap": market_cap,
            "avg_dollar_volume_30d": avg_dv,
            "has_yf_options": has_opts,
        }
    except Exception:
        return {}


def _is_biotech_sector(sector: str, industry: str) -> bool:
    s = sector.lower()
    i = industry.lower()
    return (
        "healthcare" in s and any(h in i for h in _BIOTECH_INDUSTRY_HINTS)
    ) or any(h in i for h in _BIOTECH_INDUSTRY_HINTS)


def get_ticker_profile(
    ticker: str,
    *,
    alpaca_key: str = "",
    alpaca_secret: str = "",
) -> Dict[str, Any]:
    """Lightweight metadata for discovery filters and snapshots."""
    t = ticker.upper().strip()
    out: Dict[str, Any] = {
        "ticker": t,
        "is_biotech": False,
        "last_price": 0.0,
        "avg_dollar_volume_30d": 0.0,
        "has_yf_options": False,
        "market_cap": None,
        "company_name": t,
        "sector": "",
        "industry": "",
        "error": "",
    }

    fh = _profile_from_finnhub(t)
    if fh:
        industry = str(fh.get("finnhubIndustry") or fh.get("industry") or "")
        sector = str(fh.get("gsector") or fh.get("sector") or "")
        out["company_name"] = str(fh.get("name") or t)
        out["sector"] = sector
        out["industry"] = industry
        mc = fh.get("marketCapitalization")
        if mc is not None:
            try:
                out["market_cap"] = float(mc)
            except (TypeError, ValueError):
                pass
        out["is_biotech"] = _is_biotech_sector(sector, industry)

    yf_prof = _profile_from_yfinance(t)
    if yf_prof:
        if not out["sector"]:
            out["sector"] = yf_prof.get("sector") or ""
        if not out["industry"]:
            out["industry"] = yf_prof.get("industry") or ""
        if out["market_cap"] is None:
            out["market_cap"] = yf_prof.get("market_cap")
        if not out["company_name"] or out["company_name"] == t:
            out["company_name"] = yf_prof.get("company_name") or t
        if yf_prof.get("avg_dollar_volume_30d"):
            out["avg_dollar_volume_30d"] = float(yf_prof["avg_dollar_volume_30d"])
        if yf_prof.get("has_yf_options"):
            out["has_yf_options"] = True
        if not out["is_biotech"]:
            out["is_biotech"] = _is_biotech_sector(out["sector"], out["industry"])

    px = get_last_price(t, alpaca_key=alpaca_key, alpaca_secret=alpaca_secret)
    if px is not None:
        out["last_price"] = px

    if out["avg_dollar_volume_30d"] <= 0 and px and px > 0:
        # Finnhub/Alpaca path without volume history — leave 0 (may fail liquidity filter)
        pass

    if not out["is_biotech"] and out["sector"]:
        out["is_biotech"] = _is_biotech_sector(out["sector"], out["industry"])

    if out["last_price"] <= 0 and not out["sector"] and not fh and not yf_prof:
        out["error"] = "no_market_data"

    return out
