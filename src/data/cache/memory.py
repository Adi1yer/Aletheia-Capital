"""In-memory cache for API responses"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()


class MemoryCache:
    """Simple in-memory cache with TTL"""
    
    def __init__(self, ttl_hours: int = 24):
        """Initialize cache with TTL in hours"""
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.ttl = timedelta(hours=ttl_hours)
        logger.info("Initialized memory cache", ttl_hours=ttl_hours)
    
    def _get_key(self, prefix: str, *args) -> str:
        """Generate cache key"""
        return f"{prefix}:{':'.join(str(arg) for arg in args)}"
    
    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        """Check if cache entry is expired"""
        if 'timestamp' not in entry:
            return True
        age = datetime.now() - entry['timestamp']
        return age > self.ttl
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        if self._is_expired(entry):
            del self._cache[key]
            return None
        
        return entry['value']
    
    def set(self, key: str, value: Any):
        """Set value in cache"""
        self._cache[key] = {
            'value': value,
            'timestamp': datetime.now(),
        }
    
    def clear(self):
        """Clear all cache"""
        self._cache.clear()
        logger.info("Cache cleared")
    
    def get_prices(self, ticker: str, start_date: str, end_date: str) -> Optional[List[Dict]]:
        """Get cached prices"""
        key = self._get_key("prices", ticker, start_date, end_date)
        return self.get(key)
    
    def set_prices(self, ticker: str, start_date: str, end_date: str, prices: List[Dict]):
        """Cache prices"""
        key = self._get_key("prices", ticker, start_date, end_date)
        self.set(key, prices)
    
    def get_financial_metrics(self, ticker: str, end_date: str, period: str) -> Optional[List[Dict]]:
        """Get cached financial metrics"""
        key = self._get_key("metrics", ticker, end_date, period)
        return self.get(key)
    
    def set_financial_metrics(self, ticker: str, end_date: str, period: str, metrics: List[Dict]):
        """Cache financial metrics"""
        key = self._get_key("metrics", ticker, end_date, period)
        self.set(key, metrics)
    
    def get_line_items(self, ticker: str, line_items: List[str], end_date: str, period: str) -> Optional[List[Dict]]:
        """Get cached line items"""
        # Convert line_items list to string for cache key
        line_items_str = ",".join(sorted(line_items))
        key = self._get_key("line_items", ticker, line_items_str, end_date, period)
        return self.get(key)
    
    def set_line_items(self, ticker: str, line_items: List[str], end_date: str, period: str, items: List[Dict]):
        """Cache line items"""
        # Convert line_items list to string for cache key
        line_items_str = ",".join(sorted(line_items))
        key = self._get_key("line_items", ticker, line_items_str, end_date, period)
        self.set(key, items)


# Global cache instance
_cache: Optional[MemoryCache] = None


def get_cache() -> MemoryCache:
    """Get global cache instance"""
    global _cache
    if _cache is None:
        _cache = MemoryCache(ttl_hours=24)  # 24 hour TTL for weekly trading
    return _cache

