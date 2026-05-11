"""Data aggregator that combines multiple data providers"""

from typing import List, Optional, Any, Dict
from src.data.models import Price, FinancialMetrics, LineItem, InsiderTrade, CompanyNews
from src.data.providers.base import DataProvider
from src.data.providers.crypto import CRYPTO_IDS
from src.data.cache.memory import get_cache, MemoryCache
from src.data.cache.redis import RedisCache
from src.config.settings import settings
import structlog

logger = structlog.get_logger()


class DataAggregator(DataProvider):
    """Aggregates data from multiple providers with fallback logic and caching"""
    
    def __init__(self, redis_client=None):
        """
        Initialize with available providers and cache
        
        Args:
            redis_client: Optional Redis client for distributed caching (falls back to memory cache)
        """
        from src.data.providers.yahoo import YahooFinanceProvider
        from src.data.providers.finnhub import FinnhubProvider
        from src.data.providers.congressional import CongressionalProvider
        from src.data.providers.crypto import CryptoProvider

        self.providers: List[DataProvider] = [
            YahooFinanceProvider(),  # Primary provider (free, reliable)
        ]
        if getattr(settings, "finnhub_api_key", None):
            self.providers.append(FinnhubProvider(api_key=settings.finnhub_api_key))
            logger.info("Finnhub provider added (insider + analyst)")
        if getattr(settings, "finnhub_api_key", None) or getattr(settings, "congressional_api_key", None):
            self.providers.append(CongressionalProvider(
                finnhub_api_key=getattr(settings, "finnhub_api_key", None),
                congressional_api_key=getattr(settings, "congressional_api_key", None),
            ))
            logger.info("Congressional provider added (politician trades)")
        crypto_on = getattr(settings, "crypto_enabled", False)
        if crypto_on:
            self.providers.append(CryptoProvider(api_key=getattr(settings, "coingecko_api_key", None)))
            logger.info("Crypto provider added (CoinGecko)")
        
        # Try Redis cache first, fallback to memory cache
        if redis_client:
            try:
                self.cache = RedisCache(redis_client=redis_client)
                logger.info("Using Redis cache for data aggregation")
            except Exception as e:
                logger.warning("Redis cache initialization failed, using memory cache", error=str(e))
                self.cache = get_cache()
        else:
            self.cache = get_cache()
        
        logger.info("Initialized data aggregator", provider_count=len(self.providers))
    
    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> List[Price]:
        """Get prices from cache or first available provider"""
        # Check cache first
        cached = self.cache.get_prices(ticker, start_date, end_date)
        if cached is not None:
            logger.debug("Cache hit for prices", ticker=ticker, start=start_date, end=end_date)
            # Convert dict back to Price objects
            return [Price(**p) if isinstance(p, dict) else p for p in cached]

        # Crypto symbols: try crypto provider first
        ticker_upper = ticker.upper()
        if ticker_upper in CRYPTO_IDS:
            for provider in self.providers:
                if isinstance(provider, CryptoProvider):
                    try:
                        prices = provider.get_prices(ticker, start_date, end_date)
                        if prices:
                            prices_dict = [p.model_dump() if hasattr(p, "model_dump") else p for p in prices]
                            self.cache.set_prices(ticker, start_date, end_date, prices_dict)
                            return prices
                    except Exception as e:
                        logger.warning("Crypto provider failed", ticker=ticker, error=str(e))
                    break

        # Cache miss - fetch from provider
        for provider in self.providers:
            try:
                prices = provider.get_prices(ticker, start_date, end_date)
                if prices:
                    # Cache the results (convert to dict for caching)
                    prices_dict = [p.model_dump() if hasattr(p, 'model_dump') else p for p in prices]
                    self.cache.set_prices(ticker, start_date, end_date, prices_dict)
                    logger.debug("Cached prices", ticker=ticker, count=len(prices))
                    return prices
            except Exception as e:
                logger.warning("Provider failed, trying next", provider=type(provider).__name__, error=str(e))
                continue
        
        # This is expected for some symbols (e.g., delisted/SPAC/ADR tickers); treat as a soft warning
        logger.warning("All providers failed to fetch prices", ticker=ticker)
        return []
    
    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> List[FinancialMetrics]:
        """Get financial metrics from cache or first available provider"""
        # Check cache first
        cached = self.cache.get_financial_metrics(ticker, end_date, period)
        if cached is not None:
            logger.debug("Cache hit for financial metrics", ticker=ticker, end_date=end_date, period=period)
            # Convert dict back to FinancialMetrics objects
            return [FinancialMetrics(**m) if isinstance(m, dict) else m for m in cached]
        
        # Cache miss - fetch from provider
        for provider in self.providers:
            try:
                metrics = provider.get_financial_metrics(ticker, end_date, period, limit)
                if metrics:
                    # Cache the results (convert to dict for caching)
                    metrics_dict = [m.model_dump() if hasattr(m, 'model_dump') else m for m in metrics]
                    self.cache.set_financial_metrics(ticker, end_date, period, metrics_dict)
                    logger.debug("Cached financial metrics", ticker=ticker, count=len(metrics))
                    return metrics
            except Exception as e:
                logger.warning("Provider failed, trying next", provider=type(provider).__name__, error=str(e))
                continue
        
        logger.warning("All providers failed to fetch financial metrics", ticker=ticker)
        return []
    
    def get_line_items(
        self,
        ticker: str,
        line_items: List[str],
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> List[LineItem]:
        """Get line items from cache or first available provider"""
        # Check cache first
        cached = self.cache.get_line_items(ticker, line_items, end_date, period)
        if cached is not None:
            logger.debug("Cache hit for line items", ticker=ticker, end_date=end_date, period=period)
            # Convert dict back to LineItem objects
            return [LineItem(**item) if isinstance(item, dict) else item for item in cached]
        
        # Cache miss - fetch from provider
        for provider in self.providers:
            try:
                items = provider.get_line_items(ticker, line_items, end_date, period, limit)
                if items:
                    # Cache the results (convert to dict for caching)
                    items_dict = [item.model_dump() if hasattr(item, 'model_dump') else item for item in items]
                    self.cache.set_line_items(ticker, line_items, end_date, period, items_dict)
                    logger.debug("Cached line items", ticker=ticker, count=len(items))
                    return items
            except Exception as e:
                logger.warning("Provider failed, trying next", provider=type(provider).__name__, error=str(e))
                continue
        
        logger.warning("All providers failed to fetch line items", ticker=ticker)
        return []
    
    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: Optional[str] = None,
        limit: int = 1000,
    ) -> List[InsiderTrade]:
        """Get insider trades from first available provider"""
        for provider in self.providers:
            try:
                trades = provider.get_insider_trades(ticker, end_date, start_date, limit)
                if trades:
                    return trades
            except Exception as e:
                logger.warning("Provider failed, trying next", provider=type(provider).__name__, error=str(e))
                continue
        
        return []
    
    def get_congressional_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get congressional (House/Senate) trades for a ticker from first available provider."""
        for provider in self.providers:
            if hasattr(provider, "get_congressional_trades"):
                try:
                    trades = provider.get_congressional_trades(ticker, end_date, start_date, limit)
                    if trades:
                        return trades
                except Exception as e:
                    logger.warning("Congressional trades failed", provider=type(provider).__name__, error=str(e))
        return []

    def get_crypto_metrics(self, symbol: str) -> Dict[str, Any]:
        """Get crypto metrics from crypto provider if available."""
        for provider in self.providers:
            if isinstance(provider, CryptoProvider) and hasattr(provider, "get_crypto_metrics"):
                try:
                    return provider.get_crypto_metrics(symbol)
                except Exception as e:
                    logger.warning("Crypto metrics failed", symbol=symbol, error=str(e))
        return {}

    def get_next_earnings_date(self, ticker: str) -> Optional[str]:
        """Next earnings date from first provider that implements it (Yahoo)."""
        for provider in self.providers:
            if hasattr(provider, "get_next_earnings_date"):
                try:
                    d = provider.get_next_earnings_date(ticker)
                    if d:
                        return d
                except Exception as e:
                    logger.debug("Earnings lookup failed", provider=type(provider).__name__, error=str(e))
        return None

    def get_analyst_recommendations(self, ticker: str) -> List[Dict[str, Any]]:
        """Get analyst recommendation trends from first provider that supports it (e.g. Finnhub)."""
        for provider in self.providers:
            if hasattr(provider, "get_analyst_recommendations"):
                try:
                    out = provider.get_analyst_recommendations(ticker)
                    if out:
                        return out
                except Exception as e:
                    logger.warning("Analyst recommendations failed", provider=type(provider).__name__, error=str(e))
        return []
    
    def get_company_news(
        self,
        ticker: str,
        end_date: str,
        start_date: Optional[str] = None,
        limit: int = 1000,
    ) -> List[CompanyNews]:
        """Get company news from first available provider"""
        for provider in self.providers:
            try:
                news = provider.get_company_news(ticker, end_date, start_date, limit)
                if news:
                    return news
            except Exception as e:
                logger.warning("Provider failed, trying next", provider=type(provider).__name__, error=str(e))
                continue
        
        return []


# Global data aggregator instance
_data_aggregator: Optional[DataAggregator] = None


def get_data_provider() -> DataAggregator:
    """Get the global data aggregator instance"""
    global _data_aggregator
    if _data_aggregator is None:
        _data_aggregator = DataAggregator()
    return _data_aggregator

