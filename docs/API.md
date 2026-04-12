# API Documentation

## Overview

This document describes the main APIs and interfaces of the AI Hedge Fund Production System.

## Core Modules

### Trading Pipeline

#### `TradingPipeline`

Main orchestrator for weekly trading cycles.

**Initialization**:
```python
from src.trading.pipeline import TradingPipeline

# Default (parallel agents enabled)
pipeline = TradingPipeline()

# Custom configuration
pipeline = TradingPipeline(
    parallel_agents=True,  # Enable parallel agent execution
    max_workers=8          # Number of worker threads
)
```

**Methods**:

##### `run_weekly_trading(tickers: List[str], execute: bool = False) -> Dict`

Run a weekly trading cycle.

**Parameters**:
- `tickers`: List of stock ticker symbols to analyze
- `execute`: If True, execute trades. If False, only generate decisions (dry run)

**Returns**:
```python
{
    'timestamp': '2024-01-15T10:30:00',
    'tickers': ['AAPL', 'MSFT', 'GOOGL'],
    'portfolio': {
        'cash': 100000.0,
        'positions': {...}
    },
    'agent_signals': {
        'warren_buffett': {
            'AAPL': {
                'signal': 'buy',
                'confidence': 75,
                'reasoning': '...'
            }
        }
    },
    'risk_analysis': {...},
    'decisions': {...},
    'execution_results': {...}
}
```

**Example**:
```python
# Dry run
results = pipeline.run_weekly_trading(['AAPL', 'MSFT'], execute=False)

# Execute trades
results = pipeline.run_weekly_trading(['AAPL', 'MSFT'], execute=True)
```

---

### Investment Agents

#### `BaseAgent`

Base class for all investment agents.

**Initialization**:
```python
from src.agents.base import BaseAgent

class MyAgent(BaseAgent):
    def __init__(self, weight: float = 1.0):
        super().__init__(
            name="My Agent",
            description="Description",
            investing_style="Style description",
            weight=weight,
            llm_model="deepseek-r1",
            llm_provider="deepseek"
        )
    
    def analyze(self, ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal:
        # Implementation
        pass
```

**Methods**:

##### `analyze(ticker: str, start_date: str, end_date: str, **kwargs) -> AgentSignal`

Analyze a single ticker and return a signal.

**Parameters**:
- `ticker`: Stock ticker symbol
- `start_date`: Analysis start date (YYYY-MM-DD)
- `end_date`: Analysis end date (YYYY-MM-DD)
- `**kwargs`: Additional context/data

**Returns**: `AgentSignal` object

**Example**:
```python
agent = WarrenBuffettAgent()
signal = agent.analyze("AAPL", "2024-01-01", "2024-01-31")
print(signal.signal)      # 'buy', 'sell', 'hold', or 'neutral'
print(signal.confidence)  # 0-100
print(signal.reasoning)   # Explanation
```

##### `analyze_multiple(tickers: List[str], start_date: str, end_date: str, **kwargs) -> Dict[str, AgentSignal]`

Analyze multiple tickers.

**Returns**: Dictionary mapping ticker to `AgentSignal`

**Example**:
```python
signals = agent.analyze_multiple(['AAPL', 'MSFT'], "2024-01-01", "2024-01-31")
for ticker, signal in signals.items():
    print(f"{ticker}: {signal.signal} ({signal.confidence}%)")
```

#### `AgentSignal`

Standardized output from agents.

**Fields**:
- `signal`: str - One of 'buy', 'sell', 'hold', 'neutral'
- `confidence`: int - Confidence level (0-100)
- `reasoning`: str - Explanation for the signal

**Example**:
```python
from src.agents.base import AgentSignal

signal = AgentSignal(
    signal="buy",
    confidence=75,
    reasoning="Strong fundamentals and growth potential"
)
```

---

### Data Providers

#### `DataProvider`

Base interface for data providers.

**Methods**:
- `get_prices(ticker, start_date, end_date) -> List[Price]`
- `get_financial_metrics(ticker, end_date, period, limit) -> List[FinancialMetrics]`
- `get_line_items(ticker, line_items, end_date, period, limit) -> List[LineItem]`
- `get_insider_trades(ticker, end_date, start_date, limit) -> List[InsiderTrade]`
- `get_company_news(ticker, end_date, start_date, limit) -> List[CompanyNews]`

#### `DataAggregator`

Main data provider that aggregates multiple sources.

**Initialization**:
```python
from src.data.providers.aggregator import get_data_provider

# Default (memory cache)
provider = get_data_provider()

# With Redis cache
import redis
redis_client = redis.Redis(host='localhost', port=6379)
from src.data.providers.aggregator import DataAggregator
provider = DataAggregator(redis_client=redis_client)
```

**Example**:
```python
# Get prices
prices = provider.get_prices("AAPL", "2024-01-01", "2024-01-31")

# Get financial metrics
metrics = provider.get_financial_metrics("AAPL", "2024-01-31", period="ttm")

# Get line items
line_items = provider.get_line_items(
    "AAPL",
    ["revenue", "net_income", "free_cash_flow"],
    "2024-01-31"
)
```

---

### Risk Management

#### `RiskManager`

Calculates position limits based on risk metrics.

**Initialization**:
```python
from src.risk.manager import RiskManager

risk_manager = RiskManager()
```

**Methods**:

##### `calculate_position_limits(tickers, portfolio, start_date, end_date) -> Dict`

Calculate position limits for tickers.

**Parameters**:
- `tickers`: List of ticker symbols
- `portfolio`: Current portfolio state
- `start_date`: Start date for volatility calculation
- `end_date`: End date for analysis

**Returns**:
```python
{
    'AAPL': {
        'remaining_position_limit': 10000.0,
        'current_price': 150.0,
        'volatility_metrics': {
            'daily_volatility': 0.02,
            'annualized_volatility': 0.25
        },
        'correlation_metrics': {
            'avg_correlation': 0.5,
            'max_correlation': 0.7
        },
        'reasoning': {...}
    }
}
```

**Example**:
```python
from src.portfolio.models import Portfolio

portfolio = Portfolio(cash=100000.0)
risk_analysis = risk_manager.calculate_position_limits(
    ['AAPL', 'MSFT'],
    portfolio,
    "2024-01-01",
    "2024-01-31"
)

for ticker, analysis in risk_analysis.items():
    print(f"{ticker}: ${analysis['remaining_position_limit']:.2f} limit")
```

---

### Portfolio Management

#### `PortfolioManager`

Aggregates signals and generates trading decisions.

**Initialization**:
```python
from src.portfolio.manager import PortfolioManager

portfolio_manager = PortfolioManager()
```

**Methods**:

##### `aggregate_signals(agent_signals: Dict, agent_weights: Dict) -> Dict`

Aggregate signals from multiple agents.

**Parameters**:
- `agent_signals`: Dictionary mapping agent_key to ticker signals
- `agent_weights`: Dictionary mapping agent_key to weight

**Returns**: Aggregated signals dictionary

##### `generate_decisions(tickers, agent_signals, risk_analysis, portfolio, agent_weights) -> Dict`

Generate trading decisions.

**Parameters**:
- `tickers`: List of ticker symbols
- `agent_signals`: Aggregated agent signals
- `risk_analysis`: Risk analysis from RiskManager
- `portfolio`: Current portfolio state
- `agent_weights`: Agent weights

**Returns**: Dictionary mapping ticker to decision

**Example**:
```python
decisions = portfolio_manager.generate_decisions(
    tickers=['AAPL', 'MSFT'],
    agent_signals=agent_signals,
    risk_analysis=risk_analysis,
    portfolio=portfolio,
    agent_weights=agent_weights
)

for ticker, decision in decisions.items():
    print(f"{ticker}: {decision.action} {decision.quantity} shares")
```

---

### Broker Integration

#### `AlpacaBroker`

Interface to Alpaca trading API (paper trading only).

**Initialization**:
```python
from src.broker.alpaca import AlpacaBroker

broker = AlpacaBroker()
```

**Methods**:

##### `sync_portfolio() -> Portfolio`

Sync portfolio from Alpaca.

**Returns**: Current portfolio state

**Example**:
```python
portfolio = broker.sync_portfolio()
print(f"Cash: ${portfolio.cash:.2f}")
print(f"Positions: {len(portfolio.positions)}")
```

##### `execute_decisions(decisions: Dict) -> Dict`

Execute trading decisions.

**Parameters**:
- `decisions`: Dictionary mapping ticker to decision

**Returns**: Execution results

**Example**:
```python
results = broker.execute_decisions(decisions)
for ticker, result in results.items():
    if result.get('success'):
        print(f"{ticker}: Order executed")
    else:
        print(f"{ticker}: Error - {result.get('error')}")
```

---

### Performance Tracking

#### `PerformanceTracker`

Tracks agent and portfolio performance.

**Initialization**:
```python
from src.performance.tracker import PerformanceTracker

tracker = PerformanceTracker()
```

**Methods**:

##### `record_trade(agent_key, ticker, action, quantity, price, date)`

Record a trade for performance tracking.

##### `calculate_weights_from_performance(min_weight, max_weight, smoothing_factor) -> Dict`

Calculate new agent weights based on performance.

**Returns**: Dictionary mapping agent_key to new weight

---

### Backtesting

#### `BacktestingEngine`

Backtest trading strategies on historical data.

**Initialization**:
```python
from src.backtesting.engine import BacktestingEngine

engine = BacktestingEngine()
```

**Methods**:

##### `run_backtest(start_date, end_date, initial_capital, tickers) -> BacktestResult`

Run a backtest.

**Parameters**:
- `start_date`: Backtest start date (YYYY-MM-DD)
- `end_date`: Backtest end date (YYYY-MM-DD)
- `initial_capital`: Starting capital
- `tickers`: List of tickers to backtest

**Returns**: `BacktestResult` object

**Example**:
```python
result = engine.run_backtest(
    start_date="2023-01-01",
    end_date="2023-12-31",
    initial_capital=100000.0,
    tickers=['AAPL', 'MSFT', 'GOOGL']
)

print(f"Total Return: {result.total_return_pct:.2f}%")
print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.max_drawdown:.2f}%")
```

---

## Data Models

### `Price`

Stock price data point.

**Fields**:
- `time`: str - Timestamp
- `open`: float - Opening price
- `high`: float - High price
- `low`: float - Low price
- `close`: float - Closing price
- `volume`: int - Trading volume

### `FinancialMetrics`

Financial metrics for a company.

**Fields**:
- `period`: str - Period date
- `pe_ratio`: float - Price-to-earnings ratio
- `pb_ratio`: float - Price-to-book ratio
- `debt_to_equity`: float - Debt-to-equity ratio
- `roe`: float - Return on equity
- `roa`: float - Return on assets
- `current_ratio`: float - Current ratio
- `quick_ratio`: float - Quick ratio

### `LineItem`

Financial statement line item.

**Fields**:
- `period`: str - Period date
- `revenue`: float - Revenue
- `net_income`: float - Net income
- `free_cash_flow`: float - Free cash flow
- `ebitda`: float - EBITDA
- `total_debt`: float - Total debt
- `cash_and_equivalents`: float - Cash and equivalents
- `shareholders_equity`: float - Shareholders' equity
- `total_assets`: float - Total assets
- `operating_income`: float - Operating income
- `gross_profit`: float - Gross profit

### `Portfolio`

Portfolio state.

**Fields**:
- `cash`: float - Available cash
- `margin_requirement`: float - Margin requirement (default 0.5)
- `margin_used`: float - Margin currently used
- `positions`: Dict[str, Position] - Current positions
- `realized_gains`: Dict - Realized gains tracking

**Methods**:
- `get_position(ticker) -> Position` - Get or create position
- `get_equity(current_prices) -> float` - Calculate total equity

### `Position`

Individual stock position.

**Fields**:
- `long`: int - Long shares
- `short`: int - Short shares
- `long_cost_basis`: float - Average cost for long position
- `short_cost_basis`: float - Average cost for short position
- `short_margin_used`: float - Margin used for short position

---

## Error Handling

All modules use structured logging and handle errors gracefully:

- **Agent errors**: Return neutral signals with low confidence
- **Data fetch errors**: Return empty lists, log warnings
- **Broker errors**: Log errors, return failure status
- **Risk calculation errors**: Use default values, log warnings

---

## Configuration

### Agent Weights

Configure in `config/agent_weights.json`:
```json
{
    "warren_buffett": 1.0,
    "ben_graham": 1.0,
    "peter_lynch": 1.0
}
```

### Environment Variables

See `SETUP.md` for complete list of environment variables.

---

## Examples

### Complete Trading Cycle

```python
from src.trading.pipeline import TradingPipeline

# Initialize pipeline
pipeline = TradingPipeline(parallel_agents=True, max_workers=8)

# Run weekly trading
results = pipeline.run_weekly_trading(
    tickers=['AAPL', 'MSFT', 'GOOGL', 'AMZN'],
    execute=True  # Execute trades
)

# Check results
print(f"Decisions made: {len(results['decisions'])}")
print(f"Portfolio value: ${results['portfolio']['cash']:.2f}")
```

### Custom Agent Analysis

```python
from src.agents.warren_buffett import WarrenBuffettAgent

agent = WarrenBuffettAgent(weight=1.5)

# Analyze single stock
signal = agent.analyze("AAPL", "2024-01-01", "2024-01-31")
print(f"Signal: {signal.signal}")
print(f"Confidence: {signal.confidence}%")
print(f"Reasoning: {signal.reasoning}")

# Analyze multiple stocks
signals = agent.analyze_multiple(
    ['AAPL', 'MSFT', 'GOOGL'],
    "2024-01-01",
    "2024-01-31"
)

for ticker, signal in signals.items():
    print(f"{ticker}: {signal.signal} ({signal.confidence}%)")
```

### Data Fetching

```python
from src.data.providers.aggregator import get_data_provider

provider = get_data_provider()

# Get prices
prices = provider.get_prices("AAPL", "2024-01-01", "2024-01-31")
for price in prices:
    print(f"{price.time}: ${price.close:.2f}")

# Get financial metrics
metrics = provider.get_financial_metrics("AAPL", "2024-01-31")
if metrics:
    m = metrics[0]
    print(f"P/E Ratio: {m.pe_ratio:.2f}")
    print(f"ROE: {m.roe:.2%}")
```

---

## Best Practices

1. **Always use dry run first**: Test with `execute=False` before executing trades
2. **Monitor logs**: Check logs for errors and warnings
3. **Use caching**: Enable Redis caching for better performance
4. **Parallel execution**: Use parallel agents for faster analysis
5. **Error handling**: Always check return values for errors
6. **Rate limits**: Be aware of API rate limits when fetching data

---

## Support

For more information:
- Architecture: See `docs/ARCHITECTURE.md`
- Deployment: See `docs/DEPLOYMENT.md`
- Setup: See `SETUP.md`

