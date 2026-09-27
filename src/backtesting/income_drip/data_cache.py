"""Data cache for yfinance to avoid rate limits and redundant fetches."""

import json
import pickle
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import structlog

logger = structlog.get_logger()


class DataCache:
    """Disk cache for yfinance data with rate limiting."""
    
    def __init__(self, cache_dir: str = ".data_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.prices_dir = self.cache_dir / "prices"
        self.dividends_dir = self.cache_dir / "dividends"
        self.prices_dir.mkdir(exist_ok=True)
        self.dividends_dir.mkdir(exist_ok=True)
        self.last_fetch_time = 0.0
        self.min_fetch_interval = 2.0  # 2 seconds between fetches (more conservative)
        self.consecutive_failures = 0  # Track consecutive failures for adaptive backoff
    
    def _get_price_cache_path(self, ticker: str, start: str, end: str) -> Path:
        """Get cache file path for price data."""
        cache_key = f"{ticker}_{start}_{end}.pkl"
        return self.prices_dir / cache_key
    
    def _get_dividend_cache_path(self, ticker: str, start: str, end: str) -> Path:
        """Get cache file path for dividend data."""
        cache_key = f"{ticker}_{start}_{end}.pkl"
        return self.dividends_dir / cache_key
    
    def _should_rate_limit(self) -> bool:
        """Check if we should wait before fetching."""
        elapsed = time.time() - self.last_fetch_time
        return elapsed < self.min_fetch_interval
    
    def _wait_for_rate_limit(self):
        """Wait if needed to respect rate limits."""
        if self._should_rate_limit():
            wait_time = self.min_fetch_interval - (time.time() - self.last_fetch_time)
            if wait_time > 0:
                logger.debug(f"Rate limit wait: {wait_time:.2f}s")
                time.sleep(wait_time)
    
    def get_prices(self, ticker: str, start: str, end: str, data_provider) -> List:
        """Get prices from cache or fetch with rate limiting."""
        cache_path = self._get_price_cache_path(ticker, start, end)
        
        # Try cache first
        if cache_path.exists():
            try:
                with open(cache_path, 'rb') as f:
                    prices = pickle.load(f)
                logger.debug(f"Loaded {ticker} prices from cache", count=len(prices))
                return prices
            except Exception as e:
                logger.warning(f"Cache read failed for {ticker} prices: {e}")
        
        # Cache miss or read error - fetch with rate limiting
        self._wait_for_rate_limit()
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                prices = data_provider.get_prices(ticker, start, end)
                self.last_fetch_time = time.time()
                self.consecutive_failures = 0  # Reset on success
                
                # Save to cache
                if prices:
                    try:
                        with open(cache_path, 'wb') as f:
                            pickle.dump(prices, f)
                        logger.debug(f"Cached {ticker} prices", count=len(prices))
                    except Exception as e:
                        logger.warning(f"Cache write failed for {ticker} prices: {e}")
                
                return prices
                
            except Exception as e:
                error_str = str(e)
                if "Too Many Requests" in error_str or "Rate limit" in error_str or "429" in error_str:
                    self.consecutive_failures += 1
                    if attempt < max_retries - 1:
                        # Aggressive exponential backoff with jitter for rate limits
                        base_wait = min(60, (3 ** attempt) * (1 + self.consecutive_failures))
                        jitter = time.time() % 5
                        wait = base_wait + jitter  # 3-8s, 9-14s, 27-32s, 81-86s, 243-248s
                        logger.warning(f"Rate limit hit for {ticker}, retry {attempt+1}/{max_retries} in {wait:.1f}s")
                        time.sleep(wait)
                    else:
                        logger.error(f"Rate limit exceeded for {ticker} after {max_retries} retries")
                        return []
                else:
                    logger.error(f"Failed to fetch {ticker} prices: {e}")
                    return []
        
        return []
    
    def get_dividends(self, ticker: str, start: str, end: str, data_provider) -> List:
        """Get dividends from cache or fetch with rate limiting."""
        cache_path = self._get_dividend_cache_path(ticker, start, end)
        
        # Try cache first
        if cache_path.exists():
            try:
                with open(cache_path, 'rb') as f:
                    dividends = pickle.load(f)
                logger.debug(f"Loaded {ticker} dividends from cache", count=len(dividends))
                return dividends
            except Exception as e:
                logger.warning(f"Cache read failed for {ticker} dividends: {e}")
        
        # Cache miss or read error - fetch with rate limiting
        self._wait_for_rate_limit()
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                dividends = data_provider.get_dividends(ticker, start, end)
                self.last_fetch_time = time.time()
                self.consecutive_failures = 0  # Reset on success
                
                # Save to cache
                if dividends:
                    try:
                        with open(cache_path, 'wb') as f:
                            pickle.dump(dividends, f)
                        logger.debug(f"Cached {ticker} dividends", count=len(dividends))
                    except Exception as e:
                        logger.warning(f"Cache write failed for {ticker} dividends: {e}")
                
                return dividends
                
            except Exception as e:
                error_str = str(e)
                if "Too Many Requests" in error_str or "Rate limit" in error_str or "429" in error_str:
                    self.consecutive_failures += 1
                    if attempt < max_retries - 1:
                        # Aggressive exponential backoff with jitter
                        base_wait = min(60, (3 ** attempt) * (1 + self.consecutive_failures))
                        jitter = time.time() % 5
                        wait = base_wait + jitter
                        logger.warning(f"Rate limit hit for {ticker} dividends, retry {attempt+1}/{max_retries} in {wait:.1f}s")
                        time.sleep(wait)
                    else:
                        logger.error(f"Rate limit exceeded for {ticker} dividends after {max_retries} retries")
                        return []
                else:
                    logger.error(f"Failed to fetch {ticker} dividends: {e}")
                    return []
        
        return []
    
    def clear_cache(self):
        """Clear all cached data."""
        import shutil
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.prices_dir.mkdir(exist_ok=True)
            self.dividends_dir.mkdir(exist_ok=True)
        logger.info("Cache cleared")
