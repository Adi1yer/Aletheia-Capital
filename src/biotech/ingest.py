"""Assemble BiotechSnapshot from public sources."""

from __future__ import annotations

from datetime import datetime
from typing import List

import structlog

from src.biotech.clinicaltrials import search_trials_by_term
from src.biotech.edgar import recent_filings
from src.biotech.market_quotes import get_last_price, get_ticker_profile
from src.biotech.models import BiotechSnapshot, FilingRef, TrialSummary

logger = structlog.get_logger()


def build_snapshot(ticker: str, news_limit: int = 12) -> BiotechSnapshot:
    t = ticker.upper().strip()
    end = datetime.now().strftime("%Y-%m-%d")

    profile = get_ticker_profile(t)
    company_name = str(profile.get("company_name") or t)
    sector = str(profile.get("sector") or "")
    industry = str(profile.get("industry") or "")
    last_price = get_last_price(t)
    if last_price is None and profile.get("last_price"):
        try:
            lp = float(profile["last_price"])
            last_price = lp if lp > 0 else None
        except (TypeError, ValueError):
            pass

    term = company_name or t
    trials: List[TrialSummary] = search_trials_by_term(term, page_size=60)

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
        import yfinance as yf

        news = yf.Ticker(t).news or []
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
