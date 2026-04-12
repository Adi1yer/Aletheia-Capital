"""Daily market update system"""

from typing import Dict, List
from datetime import datetime, timedelta
from src.broker.alpaca import AlpacaBroker
from src.data.providers.aggregator import get_data_provider
from src.portfolio.models import Portfolio
from src.agents.registry import get_registry
import structlog

logger = structlog.get_logger()


class DailyUpdateSystem:
    """System for generating daily market updates"""
    
    def __init__(self):
        self.broker = AlpacaBroker()
        self.data_provider = get_data_provider()
        self.registry = get_registry()
        logger.info("Initialized daily update system")
    
    def generate_daily_update(
        self,
        portfolio_tickers: List[str] = None,
        market_summary: bool = True,
    ) -> Dict:
        """
        Generate daily market update
        
        Args:
            portfolio_tickers: List of tickers in portfolio (if None, gets from broker)
            market_summary: Include market summary
        
        Returns:
            Dictionary with daily update information
        """
        logger.info("Generating daily update")
        
        update = {
            'date': datetime.now().strftime("%Y-%m-%d"),
            'timestamp': datetime.now().isoformat(),
        }
        
        # 1. Portfolio Status
        try:
            portfolio = self.broker.sync_portfolio()
            account = self.broker.get_account()
            
            update['portfolio'] = {
                'cash': account['cash'],
                'equity': account['equity'],
                'portfolio_value': account['portfolio_value'],
                'buying_power': account['buying_power'],
                'position_count': len(portfolio.positions),
            }
            
            # Get current positions
            positions = self.broker.get_positions()
            update['positions'] = positions
            
            # Calculate portfolio performance
            if portfolio_tickers is None:
                portfolio_tickers = list(positions.keys())
            
        except Exception as e:
            logger.error("Error fetching portfolio", error=str(e))
            update['portfolio'] = {'error': str(e)}
            portfolio_tickers = []
        
        # 2. Market Data for Portfolio Holdings
        if portfolio_tickers:
            update['holdings_data'] = {}
            for ticker in portfolio_tickers[:50]:  # Limit to 50 for performance
                try:
                    # Get latest price
                    end_date = datetime.now().strftime("%Y-%m-%d")
                    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
                    prices = self.data_provider.get_prices(ticker, start_date, end_date)
                    
                    if prices:
                        latest_price = prices[-1].close
                        price_change = ((latest_price - prices[0].close) / prices[0].close * 100) if len(prices) > 1 else 0
                        
                        # Get basic metrics
                        metrics = self.data_provider.get_financial_metrics(ticker, end_date, limit=1)
                        
                        update['holdings_data'][ticker] = {
                            'current_price': latest_price,
                            'price_change_pct': round(price_change, 2),
                            'pe_ratio': metrics[0].pe_ratio if metrics else None,
                            'market_cap': metrics[0].market_cap if metrics else None,
                        }
                except Exception as e:
                    logger.debug("Error fetching data for ticker", ticker=ticker, error=str(e))
                    continue
        
        # 3. Market Summary (if requested)
        if market_summary:
            update['market_summary'] = self._get_market_summary()
        
        # 4. Agent Status
        agents = self.registry.get_all()
        update['agents'] = {
            'total_agents': len(agents),
            'agent_list': [agent.name for agent in agents.values()],
        }
        
        logger.info("Daily update generated", update_keys=list(update.keys()))
        return update
    
    def _get_market_summary(self) -> Dict:
        """Get market summary (major indices)"""
        try:
            # Get major indices
            indices = {
                'SPY': 'S&P 500',
                'QQQ': 'NASDAQ 100',
                'DIA': 'Dow Jones',
            }
            
            summary = {}
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
            
            for ticker, name in indices.items():
                try:
                    prices = self.data_provider.get_prices(ticker, start_date, end_date)
                    if prices:
                        current = prices[-1].close
                        previous = prices[0].close if len(prices) > 1 else current
                        change_pct = ((current - previous) / previous * 100) if previous > 0 else 0
                        
                        summary[name] = {
                            'ticker': ticker,
                            'current': round(current, 2),
                            'change_pct': round(change_pct, 2),
                        }
                except Exception as e:
                    logger.debug("Error fetching index", ticker=ticker, error=str(e))
                    continue
            
            return summary
            
        except Exception as e:
            logger.error("Error generating market summary", error=str(e))
            return {'error': str(e)}
    
    def format_update_report(self, update: Dict) -> str:
        """Format daily update as a readable report"""
        report = []
        report.append("=" * 80)
        report.append(f"DAILY MARKET UPDATE - {update['date']}")
        report.append("=" * 80)
        report.append("")
        
        # Portfolio Status
        if 'portfolio' in update and 'error' not in update['portfolio']:
            portfolio = update['portfolio']
            report.append("PORTFOLIO STATUS")
            report.append("-" * 80)
            report.append(f"Cash: ${portfolio.get('cash', 0):,.2f}")
            report.append(f"Equity: ${portfolio.get('equity', 0):,.2f}")
            report.append(f"Portfolio Value: ${portfolio.get('portfolio_value', 0):,.2f}")
            report.append(f"Buying Power: ${portfolio.get('buying_power', 0):,.2f}")
            report.append(f"Positions: {portfolio.get('position_count', 0)}")
            report.append("")
        
        # Market Summary
        if 'market_summary' in update:
            report.append("MARKET SUMMARY")
            report.append("-" * 80)
            for name, data in update['market_summary'].items():
                if 'error' not in data:
                    change_str = f"+{data['change_pct']:.2f}%" if data['change_pct'] >= 0 else f"{data['change_pct']:.2f}%"
                    report.append(f"{name} ({data['ticker']}): ${data['current']:.2f} ({change_str})")
            report.append("")
        
        # Top Holdings
        if 'holdings_data' in update and update['holdings_data']:
            report.append("TOP HOLDINGS")
            report.append("-" * 80)
            # Sort by price change
            sorted_holdings = sorted(
                update['holdings_data'].items(),
                key=lambda x: x[1].get('price_change_pct', 0),
                reverse=True
            )
            
            for ticker, data in sorted_holdings[:10]:  # Top 10
                change_str = f"+{data['price_change_pct']:.2f}%" if data['price_change_pct'] >= 0 else f"{data['price_change_pct']:.2f}%"
                report.append(f"{ticker}: ${data['current_price']:.2f} ({change_str})")
            report.append("")
        
        # Agent Status
        if 'agents' in update:
            report.append("AGENT STATUS")
            report.append("-" * 80)
            report.append(f"Total Agents: {update['agents']['total_agents']}")
            report.append("")
        
        report.append("=" * 80)
        
        return "\n".join(report)

