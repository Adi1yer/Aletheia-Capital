"""Base class for data providers"""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
from src.data.models import Price, FinancialMetrics, LineItem, InsiderTrade, CompanyNews


class DataProvider(ABC):
    """Abstract base class for data providers"""
    
    @abstractmethod
    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> List[Price]:
        """Fetch historical price data"""
        pass
    
    @abstractmethod
    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> List[FinancialMetrics]:
        """Fetch financial metrics"""
        pass
    
    @abstractmethod
    def get_line_items(
        self,
        ticker: str,
        line_items: List[str],
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> List[LineItem]:
        """Fetch financial statement line items"""
        pass
    
    def get_market_cap(
        self,
        ticker: str,
        end_date: str,
    ) -> Optional[float]:
        """Get market capitalization"""
        metrics = self.get_financial_metrics(ticker, end_date, limit=1)
        if metrics and metrics[0].market_cap:
            return metrics[0].market_cap
        return None
    
    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: Optional[str] = None,
        limit: int = 1000,
    ) -> List[InsiderTrade]:
        """Fetch insider trading data (optional)"""
        return []
    
    def get_company_news(
        self,
        ticker: str,
        end_date: str,
        start_date: Optional[str] = None,
        limit: int = 1000,
    ) -> List[CompanyNews]:
        """Fetch company news (optional)"""
        return []

