"""Redis-based caching for financial data"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import json
import structlog

logger = structlog.get_logger()


class RedisCache:
    """Redis-based cache with TTL support"""
    
    def __init__(self, redis_client=None, ttl_hours: int = 24):
        """
        Initialize Redis cache
        
        Args:
            redis_client: Redis client instance (from redis package)
            ttl_hours: Time-to-live in hours (default: 24)
        """
        self.redis_client = redis_client
        self.ttl_seconds = ttl_hours * 3600
        self.enabled = redis_client is not None
        
        if self.enabled:
            logger.info("Redis cache initialized", ttl_hours=ttl_hours)
        else:
            logger.warning("Redis cache disabled - no client provided")
    
    def _make_key(self, prefix: str, *args) -> str:
        """Create cache key from prefix and arguments"""
        parts = [prefix] + [str(arg) for arg in args]
        return ":".join(parts)
    
    def _serialize(self, data: Any) -> str:
        """Serialize data to JSON string"""
        if isinstance(data, list):
            return json.dumps([item.model_dump() if hasattr(item, 'model_dump') else item for item in data])
        elif hasattr(data, 'model_dump'):
            return json.dumps(data.model_dump())
        else:
            return json.dumps(data)
    
    def _deserialize(self, data: str, model_class=None):
        """Deserialize JSON string to data"""
        obj = json.loads(data)
        if model_class and isinstance(obj, dict):
            return model_class(**obj)
        elif model_class and isinstance(obj, list):
            return [model_class(**item) if isinstance(item, dict) else item for item in obj]
        return obj
    
    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> Optional[List]:
        """Get cached prices"""
        if not self.enabled:
            return None
        
        try:
            key = self._make_key("prices", ticker, start_date, end_date)
            data = self.redis_client.get(key)
            if data:
                logger.debug("Redis cache hit for prices", ticker=ticker)
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning("Redis cache get error", error=str(e))
            return None
    
    def set_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        prices: List,
    ):
        """Cache prices"""
        if not self.enabled:
            return
        
        try:
            key = self._make_key("prices", ticker, start_date, end_date)
            data = self._serialize(prices)
            self.redis_client.setex(key, self.ttl_seconds, data)
            logger.debug("Cached prices in Redis", ticker=ticker, count=len(prices))
        except Exception as e:
            logger.warning("Redis cache set error", error=str(e))
    
    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "annual",
    ) -> Optional[List]:
        """Get cached financial metrics"""
        if not self.enabled:
            return None
        
        try:
            key = self._make_key("metrics", ticker, end_date, period)
            data = self.redis_client.get(key)
            if data:
                logger.debug("Redis cache hit for financial metrics", ticker=ticker)
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning("Redis cache get error", error=str(e))
            return None
    
    def set_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str,
        metrics: List,
    ):
        """Cache financial metrics"""
        if not self.enabled:
            return
        
        try:
            key = self._make_key("metrics", ticker, end_date, period)
            data = self._serialize(metrics)
            self.redis_client.setex(key, self.ttl_seconds, data)
            logger.debug("Cached financial metrics", ticker=ticker, count=len(metrics))
        except Exception as e:
            logger.warning("Redis cache set error", error=str(e))
    
    def get_line_items(
        self,
        ticker: str,
        line_items: List[str],
        end_date: str,
        period: str = "annual",
    ) -> Optional[List]:
        """Get cached line items"""
        if not self.enabled:
            return None
        
        try:
            items_key = ",".join(sorted(line_items))
            key = self._make_key("line_items", ticker, items_key, end_date, period)
            data = self.redis_client.get(key)
            if data:
                logger.debug("Redis cache hit for line items", ticker=ticker)
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning("Redis cache get error", error=str(e))
            return None
    
    def set_line_items(
        self,
        ticker: str,
        line_items: List[str],
        end_date: str,
        period: str,
        items: List,
    ):
        """Cache line items"""
        if not self.enabled:
            return
        
        try:
            items_key = ",".join(sorted(line_items))
            key = self._make_key("line_items", ticker, items_key, end_date, period)
            data = self._serialize(items)
            self.redis_client.setex(key, self.ttl_seconds, data)
            logger.debug("Cached line items in Redis", ticker=ticker, count=len(items))
        except Exception as e:
            logger.warning("Redis cache set error", error=str(e))
    
    def clear(self, pattern: Optional[str] = None):
        """Clear cache entries (optionally by pattern)"""
        if not self.enabled:
            return
        
        try:
            if pattern:
                keys = self.redis_client.keys(pattern)
                if keys:
                    self.redis_client.delete(*keys)
                    logger.info("Cleared Redis cache", pattern=pattern, count=len(keys))
            else:
                self.redis_client.flushdb()
                logger.info("Cleared all Redis cache")
        except Exception as e:
            logger.warning("Redis cache clear error", error=str(e))

