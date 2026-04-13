"""Yahoo Finance data provider (free)"""

import yfinance as yf
from typing import List, Optional
from datetime import datetime
from src.data.models import Price, FinancialMetrics, LineItem, CompanyNews
from src.data.providers.base import DataProvider
import structlog

logger = structlog.get_logger()


class YahooFinanceProvider(DataProvider):
    """Yahoo Finance provider using yfinance library"""
    
    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> List[Price]:
        """Fetch historical price data from Yahoo Finance"""
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date)
            
            if df.empty:
                logger.warning("No price data found", ticker=ticker, start=start_date, end=end_date)
                return []
            
            prices = []
            for idx, row in df.iterrows():
                prices.append(Price(
                    time=idx.to_pydatetime(),
                    open=float(row['Open']),
                    high=float(row['High']),
                    low=float(row['Low']),
                    close=float(row['Close']),
                    volume=int(row['Volume']),
                ))
            
            logger.info("Fetched prices", ticker=ticker, count=len(prices))
            return prices
            
        except Exception as e:
            logger.error("Error fetching prices", ticker=ticker, error=str(e))
            return []
    
    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> List[FinancialMetrics]:
        """Fetch financial metrics from Yahoo Finance"""
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Get market cap
            market_cap = info.get('marketCap')
            
            # Get key metrics
            metrics = FinancialMetrics(
                ticker=ticker,
                report_period=datetime.strptime(end_date, "%Y-%m-%d"),
                market_cap=market_cap,
                pe_ratio=info.get('trailingPE'),
                price_to_book_ratio=info.get('priceToBook'),
                debt_to_equity=info.get('debtToEquity'),
                roe=info.get('returnOnEquity'),
                revenue_growth=info.get('revenueGrowth'),
                earnings_growth=info.get('earningsGrowth'),
                interest_coverage=info.get('interestCoverage'),
            )
            
            logger.info("Fetched financial metrics", ticker=ticker)
            return [metrics]
            
        except Exception as e:
            logger.error("Error fetching financial metrics", ticker=ticker, error=str(e))
            return []
    
    def get_line_items(
        self,
        ticker: str,
        line_items: List[str],
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> List[LineItem]:
        """Fetch financial statement line items from Yahoo Finance"""
        try:
            stock = yf.Ticker(ticker)
            
            # Get financials
            financials = stock.financials
            balance_sheet = stock.balance_sheet
            cashflow = stock.cashflow
            
            if financials.empty and balance_sheet.empty and cashflow.empty:
                logger.warning("No financial data found", ticker=ticker)
                return []
            
            # Determine the most recent period for each statement independently.
            # Fiscal calendars differ across statements (e.g. ROST files income on Jan 31
            # but balance sheet may lag), so we cannot assume the same column exists in all.
            fin_period = financials.columns[0] if not financials.empty else None
            bs_period = balance_sheet.columns[0] if not balance_sheet.empty else None
            cf_period = cashflow.columns[0] if not cashflow.empty else None

            most_recent_period = fin_period or bs_period or cf_period
            if most_recent_period is None:
                return []

            line_item_data = {
                'ticker': ticker,
                'report_period': most_recent_period.to_pydatetime(),
            }

            def _safe_get(df, row_label, col):
                """Get a cell value only if both row and column exist in the DataFrame."""
                if col is not None and row_label in df.index and col in df.columns:
                    return df.loc[row_label, col]
                return None

            if not financials.empty:
                line_item_data['revenue'] = _safe_get(financials, 'Total Revenue', fin_period)
                line_item_data['net_income'] = _safe_get(financials, 'Net Income', fin_period)
                line_item_data['gross_profit'] = _safe_get(financials, 'Gross Profit', fin_period)
                line_item_data['operating_income'] = _safe_get(financials, 'Operating Income', fin_period)
                line_item_data['ebit'] = _safe_get(financials, 'EBIT', fin_period)
                line_item_data['ebitda'] = _safe_get(financials, 'EBITDA', fin_period)

            if not balance_sheet.empty:
                line_item_data['total_assets'] = _safe_get(balance_sheet, 'Total Assets', bs_period)
                line_item_data['total_liabilities'] = _safe_get(balance_sheet, 'Total Liab', bs_period)
                line_item_data['shareholders_equity'] = _safe_get(balance_sheet, 'Stockholders Equity', bs_period)
                line_item_data['cash_and_equivalents'] = _safe_get(balance_sheet, 'Cash And Cash Equivalents', bs_period)
                line_item_data['total_debt'] = _safe_get(balance_sheet, 'Total Debt', bs_period)
                line_item_data['outstanding_shares'] = _safe_get(balance_sheet, 'Share Issued', bs_period)

            if not cashflow.empty:
                line_item_data['free_cash_flow'] = _safe_get(cashflow, 'Free Cash Flow', cf_period)
                line_item_data['capital_expenditure'] = _safe_get(cashflow, 'Capital Expenditure', cf_period)
                line_item_data['depreciation_and_amortization'] = _safe_get(cashflow, 'Depreciation', cf_period)
                line_item_data['dividends_and_other_cash_distributions'] = _safe_get(cashflow, 'Dividends Paid', cf_period)
            
            # Convert None values and handle NaN
            for key, value in line_item_data.items():
                if key in ['ticker', 'report_period']:
                    continue
                if value is not None:
                    try:
                        line_item_data[key] = float(value) if not (isinstance(value, float) and value != value) else None
                    except (ValueError, TypeError):
                        line_item_data[key] = None
            
            line_item = LineItem(**line_item_data)
            logger.info("Fetched line items", ticker=ticker)
            return [line_item]
            
        except Exception as e:
            logger.error("Error fetching line items", ticker=ticker, error=str(e))
            return []

    def get_company_news(
        self,
        ticker: str,
        end_date: str,
        start_date: Optional[str] = None,
        limit: int = 1000,
    ) -> List[CompanyNews]:
        """Fetch company news from Yahoo Finance (yfinance)"""
        try:
            stock = yf.Ticker(ticker)
            raw = getattr(stock, "news", None)
            if callable(raw):
                raw = raw() if raw else []
            raw = raw or []
            if not raw:
                return []
            out: List[CompanyNews] = []
            for i, item in enumerate(raw[: min(limit, len(raw))]):
                if not isinstance(item, dict):
                    continue
                pub = item.get("providerPublishTime") or item.get("published_at") or 0
                try:
                    dt = datetime.fromtimestamp(pub) if isinstance(pub, (int, float)) else datetime.now()
                except (ValueError, OSError):
                    dt = datetime.now()
                out.append(
                    CompanyNews(
                        ticker=ticker,
                        date=dt,
                        title=item.get("title") or item.get("headline") or "No title",
                        url=item.get("link") or item.get("url"),
                        summary=item.get("summary"),
                    )
                )
            if out:
                logger.info("Fetched company news", ticker=ticker, count=len(out))
            return out
        except Exception as e:
            logger.debug("Could not fetch company news", ticker=ticker, error=str(e))
            return []

