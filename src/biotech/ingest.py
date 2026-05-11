"""Assemble BiotechSnapshot from public sources."""

from __future__ import annotations

from datetime import datetime
from typing import List

import structlog

from src.biotech.clinicaltrials import search_trials_by_term
from src.biotech.edgar import recent_filings
from src.biotech.models import BiotechSnapshot, FilingRef, TrialSummary

logger = structlog.get_logger()


def build_snapshot(ticker: str, news_limit: int = 12) -> BiotechSnapshot:
    import yfinance as yf

    t = ticker.upper().strip()
    end = datetime.now().strftime("%Y-%m-%d")

    company_name = ""
    sector = ""
    industry = ""
    last_price = None
    try:
        stock = yf.Ticker(t)
        info = stock.info or {}
        company_name = info.get("longName") or info.get("shortName") or t
        sector = info.get("sector") or ""
        industry = info.get("industry") or ""
        hist = stock.history(period="5d")
        if hist is not None and not hist.empty:
            last_price = float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning("yfinance snapshot partial", ticker=t, error=str(e))

    term = company_name or t
    trials: List[TrialSummary] = search_trials_by_term(term, page_size=15)

    filings_raw = recent_filings(t, limit=8)
    filings: List[FilingRef] = []
    for fr in filings_raw:
        filings.append(
            FilingRef(
                form=fr.get("form", ""),
                filed_at=fr.get("filed_at", ""),
                url=fr.get("url", ""),
            )
        )

    news_titles: List[str] = []
    try:
        stock = yf.Ticker(t)
        news = stock.news or []
        for n in news[:news_limit]:
            if isinstance(n, dict):
                news_titles.append(n.get("title", "") or "")
    except Exception:
        pass

    return BiotechSnapshot(
        ticker=t,
        as_of=end,
        company_name=company_name,
        sector=sector,
        industry=industry,
        trials=trials,
        filings=filings,
        news_titles=[x for x in news_titles if x],
        last_price=last_price,
    )
