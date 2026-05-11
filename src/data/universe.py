"""Stock universe provider - gets all US stocks from stable GitHub sources only.

No Wikipedia. No hardcoded ticker lists. We use maintained, regularly updated sources:
- rreichel3/US-Stock-Symbols: all US exchange tickers (listed/delisted maintained)
- datasets/s-and-p-500-companies: S&P 500 constituents
- datasets/nasdaq-listings: NASDAQ listed symbols
- Bundled CSV (snapshot from same sources) when network is unavailable.

If every source fails, returns [] so the caller can fail explicitly (e.g. "No tickers to trade").
"""

import csv
import io
import urllib.request
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import structlog
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

logger = structlog.get_logger()

# Stable GitHub URLs (regularly updated; no Wikipedia)
# Order: most comprehensive first, then fallbacks.
UNIVERSE_URLS = [
    # All US stock symbols (NYSE, NASDAQ, etc.) - one symbol per line
    "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt",
    # S&P 500 constituents CSV
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
    # NASDAQ listed (Symbol column)
    "https://raw.githubusercontent.com/datasets/nasdaq-listings/main/data/nasdaq-listed-symbols.csv",
]

_BUNDLED_CSV = Path(__file__).parent / "universe_constituents.csv"
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"


def _dedupe_preserve_order(tickers: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _parse_txt_symbols(raw: str) -> List[str]:
    """Parse plain text: one symbol per line."""
    out = []
    for line in raw.strip().splitlines():
        s = line.strip()
        if s and not s.startswith("#") and s.upper() == s:
            out.append(s)
    return out


def _parse_csv_symbols(raw: str, symbol_columns: tuple = ("Symbol", "symbol")) -> List[str]:
    """Parse CSV; use first present of Symbol/symbol column."""
    import pandas as pd

    df = pd.read_csv(io.StringIO(raw))
    for col in symbol_columns:
        if col in df.columns:
            tickers = df[col].dropna().astype(str).str.strip().tolist()
            return [t for t in tickers if t and t.upper() == t]
    return []


def _fetch_url(url: str, timeout: int = 15) -> List[str]:
    """Fetch a single URL and return list of ticker symbols (or empty list on failure)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        logger.debug("Universe URL failed", url=url, error=str(e))
        return []
    if url.endswith(".txt"):
        return _parse_txt_symbols(raw)
    return _parse_csv_symbols(raw)


class StockUniverse:
    """Manages the stock universe for trading."""

    def __init__(
        self,
        min_market_cap: float = 50_000_000,
        min_volume: int = 100_000,
        exclude_otc: bool = True,
        exclude_penny_stocks: bool = True,
        min_price: float = 1.0,
    ):
        self.min_market_cap = min_market_cap
        self.min_volume = min_volume
        self.exclude_otc = exclude_otc
        self.exclude_penny_stocks = exclude_penny_stocks
        self.min_price = min_price
        self._data_provider = None
        logger.info(
            "Initialized stock universe",
            min_market_cap=min_market_cap,
            min_volume=min_volume,
            exclude_otc=exclude_otc,
        )

    @property
    def data_provider(self):
        if self._data_provider is None:
            from src.data.providers.aggregator import get_data_provider

            self._data_provider = get_data_provider()
        return self._data_provider

    @data_provider.setter
    def data_provider(self, value):
        self._data_provider = value

    def _load_from_bundled_csv(self) -> List[str]:
        """Load tickers from bundled CSV (no network)."""
        if not _BUNDLED_CSV.exists():
            return []
        tickers = []
        with open(_BUNDLED_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            col = "symbol" if (reader.fieldnames and "symbol" in reader.fieldnames) else "Symbol"
            for row in reader:
                s = (row.get(col) or "").strip()
                if s and s.upper() == s:
                    tickers.append(s)
        return tickers

    def _get_sp500_candidates(self) -> List[str]:
        """Get S&P 500 tickers (stable URL, then bundled CSV)."""
        tickers = _fetch_url(SP500_URL)
        if tickers:
            return _dedupe_preserve_order(tickers)
        # Bundled CSV is an S&P 500 snapshot
        return _dedupe_preserve_order(self._load_from_bundled_csv())

    def _rank_by_market_cap(
        self,
        tickers: List[str],
        as_of: Optional[str] = None,
        max_workers: int = 24,
    ) -> List[str]:
        """
        Rank tickers by market cap (desc) using our data provider's financial metrics.
        Skips tickers with missing market cap.
        """
        if not tickers:
            return []
        as_of = as_of or datetime.now().strftime("%Y-%m-%d")

        def fetch_mc(t: str) -> Tuple[str, float]:
            try:
                metrics_list = self.data_provider.get_financial_metrics(t, as_of, limit=1)
                if not metrics_list:
                    return (t, 0.0)
                mc = float(getattr(metrics_list[0], "market_cap", 0.0) or 0.0)
                return (t, mc)
            except Exception:
                return (t, 0.0)

        scored: List[Tuple[str, float]] = []
        # Use parallel calls; provider is cached, so this becomes cheaper over time.
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(fetch_mc, t): t for t in tickers}
            for fut in as_completed(futures):
                t, mc = fut.result()
                if mc > 0:
                    scored.append((t, mc))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in scored]

    def get_all_us_stocks(self) -> List[str]:
        """
        Get US stock tickers from stable GitHub sources only (no Wikipedia, no hardcoded list).
        Tries each UNIVERSE_URL in order, then bundled CSV. Returns [] if all fail.
        """
        logger.info("Fetching US stock tickers from stable sources only")
        for url in UNIVERSE_URLS:
            tickers = _fetch_url(url)
            if tickers:
                out = _dedupe_preserve_order(tickers)
                logger.info("Loaded universe from URL", url=url, count=len(out))
                return out

        tickers = self._load_from_bundled_csv()
        if tickers:
            logger.info("Loaded universe from bundled CSV", count=len(tickers))
            return tickers

        logger.warning("All universe sources failed or returned empty; no tickers available")
        return []

    def get_full_us_market(self) -> List[str]:
        """
        Full US market tickers. Uses the same stable sources as get_all_us_stocks (no Wikipedia).
        """
        return self.get_all_us_stocks()

    def filter_by_liquidity(self, tickers: List[str], max_tickers: Optional[int] = None) -> List[str]:
        """Filter tickers by liquidity criteria."""
        import yfinance as yf

        logger.info("Filtering tickers by liquidity", input_count=len(tickers))
        filtered = []
        failed = 0
        batch_size = 50
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i : i + batch_size]
            logger.info("Processing batch", batch_num=i // batch_size + 1, batch_size=len(batch))
            for ticker in batch:
                try:
                    stock = yf.Ticker(ticker)
                    info = stock.info
                    market_cap = info.get("marketCap", 0)
                    if market_cap and market_cap < self.min_market_cap:
                        continue
                    current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                    if self.exclude_penny_stocks and current_price < self.min_price:
                        continue
                    exchange = (info.get("exchange") or "").upper()
                    if self.exclude_otc and "OTC" in exchange:
                        continue
                    try:
                        hist = stock.history(period="5d")
                        if not hist.empty and hist["Volume"].mean() < self.min_volume:
                            continue
                    except Exception:
                        pass
                    filtered.append(ticker)
                    time.sleep(0.1)
                except Exception as e:
                    failed += 1
                    logger.debug("Failed to filter ticker", ticker=ticker, error=str(e))
                if max_tickers and len(filtered) >= max_tickers:
                    break
            if max_tickers and len(filtered) >= max_tickers:
                break
        if max_tickers:
            filtered = filtered[:max_tickers]
        logger.info(
            "Liquidity filtering complete",
            input_count=len(tickers),
            filtered_count=len(filtered),
            failed=failed,
        )
        return filtered

    def get_trading_universe(
        self,
        full_market: bool = False,
        max_stocks: Optional[int] = 5000,
        apply_filters: bool = True,
        rank_by_market_cap: bool = True,
    ) -> List[str]:
        """
        Get the trading universe (stable sources only).

        For weekly scans, this defaults to **top N by market cap** (N=max_stocks) using S&P 500
        as the candidate set for speed/stability, then applies liquidity checks only on that ranked subset.
        """
        if max_stocks is not None and max_stocks > 0 and rank_by_market_cap:
            candidates = self._get_sp500_candidates()
            if not candidates:
                # As a last resort, fall back to the full list (still no hardcoded tickers).
                candidates = self.get_full_us_market() if full_market else self.get_all_us_stocks()

            ranked = self._rank_by_market_cap(candidates)
            if not ranked:
                tickers = []
            else:
                # Keep pulling from the ranked list until we either have max_stocks liquid names
                # or we run out of candidates. This ensures we *try* to always end up with N usable tickers.
                desired = int(max_stocks)
                filtered: List[str] = []
                idx = 0
                chunk_size = 100
                while len(filtered) < desired and idx < len(ranked):
                    # Work on a chunk of ranked names at a time
                    chunk = ranked[idx : idx + chunk_size]
                    idx += chunk_size
                    if not apply_filters:
                        # If no liquidity filter, we can just take the next chunk.
                        for t in chunk:
                            if t not in filtered:
                                filtered.append(t)
                                if len(filtered) >= desired:
                                    break
                        continue

                    # Apply liquidity filter to this chunk, asking for only the remaining needed names
                    needed = desired - len(filtered)
                    if needed <= 0:
                        break
                    chunk_filtered = self.filter_by_liquidity(chunk, max_tickers=needed)
                    for t in chunk_filtered:
                        if t not in filtered:
                            filtered.append(t)
                            if len(filtered) >= desired:
                                break

                tickers = filtered
        else:
            tickers = self.get_full_us_market() if full_market else self.get_all_us_stocks()
            if apply_filters:
                tickers = self.filter_by_liquidity(tickers, max_tickers=max_stocks)
            elif max_stocks:
                tickers = tickers[:max_stocks]

        tickers = list(dict.fromkeys(tickers))
        logger.info("Trading universe ready", ticker_count=len(tickers))
        return tickers
