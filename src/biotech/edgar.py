"""SEC EDGAR helpers — ticker to CIK and recent filing references."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from src.biotech.http_cache import cached_get_json, cached_get_text

logger = structlog.get_logger()

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_TMPL = "https://data.sec.gov/submissions/CIK{cik}.json"


def _load_ticker_map(cache_dir: str = "data/biotech_cache") -> Dict[str, int]:
    path = Path(cache_dir) / "sec_company_tickers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = cached_get_text(SEC_TICKERS_URL, cache_dir=f"{cache_dir}/http", ttl_seconds=7 * 86400)
    data = json.loads(raw)
    out: Dict[str, int] = {}
    if isinstance(data, dict) and "data" in data and "fields" in data:
        fields = list(data["fields"])
        try:
            it = fields.index("ticker")
            ic = fields.index("cik_str")
        except ValueError:
            it, ic = -1, -1
        if it >= 0 and ic >= 0:
            for row in data.get("data") or []:
                if isinstance(row, (list, tuple)) and len(row) > max(it, ic):
                    t = str(row[it]).upper()
                    cik = int(row[ic])
                    if t and cik:
                        out[t] = cik
    else:
        for row in (data.values() if isinstance(data, dict) else data or []):
            if not isinstance(row, dict):
                continue
            t = str(row.get("ticker", "")).upper()
            cik = int(row.get("cik_str", 0) or 0)
            if t and cik:
                out[t] = cik
    path.write_text(json.dumps(out))
    return out


def ticker_to_cik(ticker: str, cache_dir: str = "data/biotech_cache") -> Optional[int]:
    m = _load_ticker_map(cache_dir)
    return m.get(ticker.upper())


def recent_filings(
    ticker: str,
    limit: int = 8,
    cache_dir: str = "data/biotech_cache",
) -> List[dict]:
    cik = ticker_to_cik(ticker, cache_dir=cache_dir)
    if not cik:
        logger.warning("No CIK for ticker", ticker=ticker)
        return []
    cik10 = f"{cik:010d}"
    url = SEC_SUBMISSIONS_TMPL.format(cik=cik10)
    data = cached_get_json(url, cache_dir=f"{cache_dir}/http", ttl_seconds=6 * 3600)
    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    acc = filings.get("accessionNumber", [])
    primary = filings.get("primaryDocument", [])
    out = []
    for i in range(min(len(forms), len(dates), limit)):
        accn = acc[i] if i < len(acc) else ""
        doc = primary[i] if i < len(primary) else ""
        cik_num = str(cik)
        if accn:
            acc_clean = accn.replace("-", "")
            link = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_clean}/{doc}" if doc else ""
        else:
            link = ""
        out.append({"form": forms[i], "filed_at": dates[i], "url": link, "accession": accn})
    return out
