"""Risk management agent - calculates position limits based on volatility and correlation"""

from typing import Dict, List

from src.portfolio.models import Portfolio
import structlog

logger = structlog.get_logger()


class RiskManager:
    """Manages risk through volatility and correlation-adjusted position limits"""
    
    def __init__(self):
        self._data_provider = None

    @property
    def data_provider(self):
        if self._data_provider is None:
            from src.data.providers.aggregator import get_data_provider

            self._data_provider = get_data_provider()
        return self._data_provider

    @data_provider.setter
    def data_provider(self, value):
        self._data_provider = value
    
    def calculate_position_limits(
        self,
        tickers: List[str],
        portfolio: Portfolio,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Dict]:
        """
        Calculate position limits for each ticker based on risk metrics
        
        Args:
            tickers: List of ticker symbols
            portfolio: Current portfolio state
            start_date: Start date for volatility calculation
            end_date: End date for analysis
        
        Returns:
            Dictionary mapping ticker to risk analysis including:
            - remaining_position_limit: Maximum dollar amount for new position
            - current_price: Current stock price
            - volatility_metrics: Volatility statistics
            - correlation_metrics: Correlation with other positions
        """
        import numpy as np
        import pandas as pd

        logger.info("Calculating position limits", ticker_count=len(tickers))

        # Fetch prices for all tickers
        prices_by_ticker: Dict[str, pd.DataFrame] = {}
        current_prices: Dict[str, float] = {}
        
        for ticker in tickers:
            prices = self.data_provider.get_prices(ticker, start_date, end_date)
            if prices:
                df = pd.DataFrame([p.model_dump() for p in prices])
                df['time'] = pd.to_datetime(df['time'])
                df = df.set_index('time').sort_index()
                prices_by_ticker[ticker] = df
                current_prices[ticker] = float(df['close'].iloc[-1])
            else:
                logger.warning("No price data", ticker=ticker)
                current_prices[ticker] = 0.0
        
        # Calculate portfolio value
        total_portfolio_value = portfolio.cash
        for ticker, position in portfolio.positions.items():
            if ticker in current_prices and current_prices[ticker] > 0:
                long_value = position.long * current_prices[ticker]
                short_value = position.short * current_prices[ticker]
                total_portfolio_value += long_value - short_value
        
        # Calculate volatility for each ticker
        volatility_data = {}
        returns_by_ticker: Dict[str, pd.Series] = {}
        
        for ticker in tickers:
            if ticker in prices_by_ticker:
                df = prices_by_ticker[ticker]
                returns = df['close'].pct_change().dropna()
                returns_by_ticker[ticker] = returns
                
                if len(returns) > 1:
                    daily_vol = returns.std()
                    annualized_vol = daily_vol * np.sqrt(252)
                    volatility_data[ticker] = {
                        'daily_volatility': float(daily_vol),
                        'annualized_volatility': float(annualized_vol),
                    }
                else:
                    volatility_data[ticker] = {
                        'daily_volatility': 0.05,
                        'annualized_volatility': 0.25,
                    }
            else:
                volatility_data[ticker] = {
                    'daily_volatility': 0.05,
                    'annualized_volatility': 0.25,
                }
        
        # Calculate correlation matrix
        correlation_matrix = None
        if len(returns_by_ticker) >= 2:
            try:
                returns_df = pd.DataFrame(returns_by_ticker).dropna(how='any')
                if returns_df.shape[1] >= 2 and returns_df.shape[0] >= 5:
                    correlation_matrix = returns_df.corr()
            except Exception as e:
                logger.warning("Correlation calculation failed", error=str(e))
        
        # Get active positions
        active_positions = {
            t for t, pos in portfolio.positions.items()
            if abs(pos.long - pos.short) > 0
        }
        
        # Calculate position limits for each ticker
        risk_analysis = {}
        
        for ticker in tickers:
            if ticker not in current_prices or current_prices[ticker] <= 0:
                risk_analysis[ticker] = {
                    'remaining_position_limit': 0.0,
                    'current_price': 0.0,
                    'reasoning': 'No valid price data',
                }
                continue
            
            current_price = current_prices[ticker]
            vol_data = volatility_data[ticker]
            annualized_vol = vol_data['annualized_volatility']
            
            # Calculate current position value
            position = portfolio.positions.get(ticker)
            if position:
                long_value = position.long * current_price
                short_value = position.short * current_price
                current_position_value = abs(long_value - short_value)
            else:
                current_position_value = 0.0
            
            # Volatility-adjusted limit percentage
            vol_adjusted_limit_pct = self._calculate_volatility_adjusted_limit(annualized_vol)
            
            # Correlation adjustment
            corr_multiplier = 1.0
            corr_metrics = {}
            
            if correlation_matrix is not None and ticker in correlation_matrix.columns:
                comparable = [t for t in active_positions if t in correlation_matrix.columns and t != ticker]
                if not comparable:
                    comparable = [t for t in correlation_matrix.columns if t != ticker]
                
                if comparable:
                    series = correlation_matrix.loc[ticker, comparable].dropna()
                    if len(series) > 0:
                        avg_corr = float(series.mean())
                        max_corr = float(series.max())
                        corr_metrics = {
                            'avg_correlation': avg_corr,
                            'max_correlation': max_corr,
                        }
                        corr_multiplier = self._calculate_correlation_multiplier(avg_corr)
            
            # Combined limit
            combined_limit_pct = vol_adjusted_limit_pct * corr_multiplier
            position_limit = total_portfolio_value * combined_limit_pct
            remaining_limit = position_limit - current_position_value

            risk_analysis[ticker] = {
                # Additional dollars allowed by risk (NOT cash-capped; cash is enforced at order sizing).
                'remaining_position_limit': float(max(0.0, remaining_limit)),
                'current_price': float(current_price),
                'volatility_metrics': vol_data,
                'correlation_metrics': corr_metrics,
                'reasoning': {
                    'portfolio_value': float(total_portfolio_value),
                    'current_position_value': float(current_position_value),
                    'base_limit_pct': float(vol_adjusted_limit_pct),
                    'correlation_multiplier': float(corr_multiplier),
                    'combined_limit_pct': float(combined_limit_pct),
                    'position_limit': float(position_limit),
                    'remaining_limit': float(remaining_limit),
                },
            }
        
        logger.info("Position limits calculated", ticker_count=len(risk_analysis))
        return risk_analysis
    
    def _calculate_volatility_adjusted_limit(self, annualized_volatility: float) -> float:
        """
        Calculate position limit percentage based on volatility
        
        Logic:
        - Low volatility (<15%): Up to 25% allocation
        - Medium volatility (15-30%): 15-20% allocation
        - High volatility (>30%): 10-15% allocation
        - Very high volatility (>50%): Max 10% allocation
        """
        base_limit = 0.20  # 20% baseline
        
        if annualized_volatility < 0.15:
            vol_multiplier = 1.25  # Up to 25%
        elif annualized_volatility < 0.30:
            vol_multiplier = 1.0 - (annualized_volatility - 0.15) * 0.5
        elif annualized_volatility < 0.50:
            vol_multiplier = 0.75 - (annualized_volatility - 0.30) * 0.5
        else:
            vol_multiplier = 0.50  # Max 10%
        
        vol_multiplier = max(0.25, min(1.25, vol_multiplier))
        return base_limit * vol_multiplier
    
    def _calculate_correlation_multiplier(self, avg_correlation: float) -> float:
        """
        Map average correlation to adjustment multiplier
        
        - Very high correlation (>= 0.8): reduce limit sharply (0.7x)
        - High correlation (0.6-0.8): reduce (0.85x)
        - Moderate correlation (0.4-0.6): neutral (1.0x)
        - Low correlation (0.2-0.4): slight increase (1.05x)
        - Very low correlation (< 0.2): increase (1.10x)
        """
        if avg_correlation >= 0.80:
            return 0.70
        elif avg_correlation >= 0.60:
            return 0.85
        elif avg_correlation >= 0.40:
            return 1.00
        elif avg_correlation >= 0.20:
            return 1.05
        else:
            return 1.10

