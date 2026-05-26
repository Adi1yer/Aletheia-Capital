"""Build per-ticker dossiers once per pipeline run (shared across agents)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.data.market_utils import compute_return_vs_index
from src.agents.prompt_helpers import format_insider_for_prompt
from src.portfolio.sectors import get_sector

LINE_ITEM_FIELDS = [
    "revenue",
    "net_income",
    "free_cash_flow",
    "total_debt",
    "shareholders_equity",
    "ebitda",
    "operating_income",
    "gross_profit",
]


def cap_bucket(market_cap: Optional[float]) -> str:
    if not market_cap or market_cap <= 0:
        return "unknown"
    if market_cap >= 200e9:
        return "mega"
    if market_cap >= 10e9:
        return "large"
    if market_cap >= 2e9:
        return "mid"
    return "small"


def _yoy_pct(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior is None or prior == 0:
        return None
    return round((current - prior) / abs(prior) * 100.0, 2)


def _compute_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-delta)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _price_summary(prices, spy_prices=None, qqq_prices=None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not prices:
        return out
    closes = [float(p.close) for p in prices]
    highs = [float(p.high) for p in prices]
    lows = [float(p.low) for p in prices]
    volumes = [int(p.volume) for p in prices if p.volume]
    last = closes[-1]
    out["last_close"] = last
    out["price_count"] = len(prices)
    if len(closes) >= 2:
        out["return_pct_period"] = round((closes[-1] - closes[0]) / closes[0] * 100.0, 2)
    period_high = max(highs) if highs else last
    period_low = min(lows) if lows else last
    out["pct_from_period_high"] = round((last - period_high) / period_high * 100.0, 2) if period_high else None
    out["pct_from_period_low"] = round((last - period_low) / period_low * 100.0, 2) if period_low else None
    recent = closes[-20:] if len(closes) >= 20 else closes
    sma_20 = sum(recent) / len(recent) if recent else last
    longer = closes[-50:] if len(closes) >= 50 else closes
    sma_50 = sum(longer) / len(longer) if longer else last
    out["sma_20"] = round(sma_20, 2)
    out["sma_50"] = round(sma_50, 2)
    out["golden_cross"] = sma_20 > sma_50
    out["rsi_14"] = _compute_rsi(closes)
    if volumes:
        avg_vol = sum(volumes[-20:]) / min(20, len(volumes))
        out["volume_ratio"] = round(volumes[-1] / avg_vol, 2) if avg_vol > 0 else 1.0
    if spy_prices:
        rv = compute_return_vs_index(prices, spy_prices)
        out["return_vs_spy_pct"] = rv
    if qqq_prices:
        out["return_vs_qqq_pct"] = compute_return_vs_index(prices, qqq_prices)
    return out


def _metrics_to_dicts(metrics_list) -> List[Dict[str, Any]]:
    rows = []
    for m in metrics_list or []:
        if hasattr(m, "model_dump"):
            rows.append(m.model_dump())
        elif isinstance(m, dict):
            rows.append(m)
    return rows


def _line_items_to_dicts(items) -> List[Dict[str, Any]]:
    rows = []
    for li in items or []:
        if hasattr(li, "model_dump"):
            rows.append(li.model_dump())
        elif isinstance(li, dict):
            rows.append(li)
    return rows


def _trends_from_line_items(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(rows) < 2:
        return {}
    cur, prior = rows[0], rows[1]
    return {
        "revenue_yoy_pct": _yoy_pct(cur.get("revenue"), prior.get("revenue")),
        "net_income_yoy_pct": _yoy_pct(cur.get("net_income"), prior.get("net_income")),
        "fcf_yoy_pct": _yoy_pct(cur.get("free_cash_flow"), prior.get("free_cash_flow")),
    }


def build_ticker_dossier(
    data_provider,
    ticker: str,
    start_date: str,
    end_date: str,
    financial_limit: int = 5,
    spy_prices=None,
    qqq_prices=None,
) -> Dict[str, Any]:
    """Full v2 dossier for hybrid agents."""
    dossier: Dict[str, Any] = {"ticker": ticker, "version": 2}

    prices = data_provider.get_prices(ticker, start_date, end_date)
    if spy_prices is None:
        spy_prices = data_provider.get_prices("SPY", start_date, end_date)
    if qqq_prices is None:
        qqq_prices = data_provider.get_prices("QQQ", start_date, end_date)

    dossier["prices"] = _price_summary(prices, spy_prices, qqq_prices)
    dossier["technicals"] = {
        "rsi_14": dossier["prices"].get("rsi_14"),
        "golden_cross": dossier["prices"].get("golden_cross"),
        "sma_20": dossier["prices"].get("sma_20"),
        "sma_50": dossier["prices"].get("sma_50"),
        "return_vs_spy_pct": dossier["prices"].get("return_vs_spy_pct"),
        "return_vs_qqq_pct": dossier["prices"].get("return_vs_qqq_pct"),
    }

    metrics_list = data_provider.get_financial_metrics(ticker, end_date, limit=financial_limit)
    dossier["metrics"] = _metrics_to_dicts(metrics_list)
    latest = dossier["metrics"][0] if dossier["metrics"] else {}
    market_cap = latest.get("market_cap")
    if market_cap is None:
        try:
            market_cap = data_provider.get_market_cap(ticker, end_date)
        except Exception:
            market_cap = None

    sector = latest.get("sector") or get_sector(ticker)
    dossier["context"] = {
        "market_cap": market_cap,
        "cap_bucket": cap_bucket(market_cap),
        "sector": sector,
        "industry": latest.get("industry"),
    }

    line_items = data_provider.get_line_items(
        ticker, LINE_ITEM_FIELDS, end_date, limit=financial_limit
    )
    dossier["line_items"] = _line_items_to_dicts(line_items)
    dossier["trends"] = _trends_from_line_items(dossier["line_items"])

    try:
        insider = data_provider.get_insider_trades(ticker, end_date, start_date, limit=20)
        dossier["insider_summary"] = format_insider_for_prompt(insider, max_entries=15)
    except Exception:
        dossier["insider_summary"] = "No recent insider transaction data available."

    try:
        news = data_provider.get_company_news(ticker, end_date, start_date, limit=10)
        dossier["news_titles"] = [
            (getattr(n, "title", None) or "")[:100] for n in (news or [])[:10]
        ]
        dossier["news_count"] = len(news or [])
    except Exception:
        dossier["news_titles"] = []
        dossier["news_count"] = 0

    dossier["benchmarks"] = {}
    if spy_prices and len(spy_prices) >= 2:
        dossier["benchmarks"]["spy_return_pct"] = round(
            (spy_prices[-1].close - spy_prices[0].close) / spy_prices[0].close * 100.0, 2
        )
    if qqq_prices and len(qqq_prices) >= 2:
        dossier["benchmarks"]["qqq_return_pct"] = round(
            (qqq_prices[-1].close - qqq_prices[0].close) / qqq_prices[0].close * 100.0, 2
        )

    # Legacy fingerprint fields for LLM cache
    m0 = dossier["metrics"][0] if dossier["metrics"] else {}
    dossier["metrics_summary"] = (
        f"mc={m0.get('market_cap', '')}|pe={m0.get('pe_ratio', '')}|pb={m0.get('price_to_book_ratio', '')}"
    )
    dossier["last_price"] = dossier["prices"].get("last_close")

    return dossier


def build_dossiers_for_tickers(
    data_provider,
    tickers: List[str],
    start_date: str,
    end_date: str,
    financial_limit: int = 5,
) -> Dict[str, Dict[str, Any]]:
    spy = data_provider.get_prices("SPY", start_date, end_date)
    qqq = data_provider.get_prices("QQQ", start_date, end_date)
    out: Dict[str, Dict[str, Any]] = {}
    for t in tickers:
        out[t] = build_ticker_dossier(
            data_provider,
            t,
            start_date,
            end_date,
            financial_limit=financial_limit,
            spy_prices=spy,
            qqq_prices=qqq,
        )
    return out


BENCHMARK_TICKERS = ("SPY", "QQQ")


def refresh_benchmarks(data_provider, start_date: str, end_date: str) -> None:
    for sym in BENCHMARK_TICKERS:
        try:
            data_provider.get_prices(sym, start_date, end_date)
        except Exception:
            pass
