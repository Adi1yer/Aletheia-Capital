# System Architecture

## Overview

The AI Hedge Fund Production System is a multi-agent trading platform that uses specialized AI agents to analyze stocks and make trading decisions. The system is designed for production use with paper trading capabilities.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Trading Pipeline                          │
│  (Orchestrates weekly trading cycles)                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   Agents     │ │     Risk     │ │  Portfolio   │
│  (21 AI)     │ │  Management  │ │  Management  │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │
       └────────────────┼────────────────┘
                        │
                        ▼
              ┌─────────────────┐
              │  Data Providers  │
              │  (Yahoo Finance) │
              └────────┬────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   Memory     │ │    Redis     │ │   Alpaca     │
│    Cache     │ │    Cache     │ │   Broker     │
└──────────────┘ └──────────────┘ └──────────────┘
```

## Component Details

### 1. Trading Pipeline (`src/trading/pipeline.py`)

**Purpose**: Orchestrates the weekly trading cycle

**Key Responsibilities**:
- Sync portfolio from broker
- Refresh market data
- Run all agents in parallel
- Calculate risk limits
- Generate trading decisions
- Execute trades (if enabled)
- Track performance
- Update agent weights

**Features**:
- Parallel agent execution (configurable)
- Batch processing for large stock universes
- Performance tracking and weight adjustment

### 2. Investment Agents (`src/agents/`)

**Purpose**: Specialized AI agents that analyze stocks

**Architecture**:
- All agents inherit from `BaseAgent`
- Each agent implements `analyze()` method
- Agents use LLMs for analysis
- Output standardized `AgentSignal` objects

**Agent Types**:
- **Value Investors**: Warren Buffett, Ben Graham, Charlie Munger
- **Growth Investors**: Peter Lynch, Phil Fisher, Cathie Wood
- **Activist Investors**: Bill Ackman, Michael Burry
- **Analytical Agents**: Valuation, Fundamentals, Technicals, Sentiment

**Key Features**:
- Parallel execution support
- Batch processing for large universes
- Error handling with neutral fallback signals

### 3. Data Layer (`src/data/`)

**Purpose**: Fetch and cache financial data

**Components**:
- **Providers**: Yahoo Finance (primary), extensible for others
- **Aggregator**: Combines multiple providers with fallback
- **Cache**: Memory cache (default) or Redis (optional)

**Data Types**:
- Stock prices (historical)
- Financial metrics (P/E, P/B, ROE, etc.)
- Line items (revenue, net income, cash flow, etc.)
- Insider trades
- Company news

**Caching Strategy**:
- 24-hour TTL for all cached data
- Automatic cache invalidation
- Redis support for distributed systems

### 4. Risk Management (`src/risk/manager.py`)

**Purpose**: Calculate position limits based on risk metrics

**Risk Factors**:
- **Volatility**: Higher volatility = lower position limits
- **Correlation**: High correlation with existing positions = reduced limits
- **Portfolio Value**: Limits scale with portfolio size

**Position Limit Calculation**:
1. Calculate volatility-adjusted base limit
2. Apply correlation multiplier
3. Ensure sufficient cash available
4. Return remaining position limit

### 5. Portfolio Management (`src/portfolio/manager.py`)

**Purpose**: Aggregate agent signals and generate trading decisions

**Process**:
1. Aggregate signals from all agents (weighted by agent weights)
2. Calculate weighted scores for each ticker
3. Generate buy/sell/hold decisions
4. Respect risk limits
5. Optimize position sizing

**Decision Generation**:
- Buy: Strong positive signal, sufficient cash, within risk limits
- Sell: Strong negative signal, existing position
- Hold: Neutral signal or insufficient confidence

### 6. Broker Integration (`src/broker/alpaca.py`)

**Purpose**: Execute trades via Alpaca API

**Features**:
- Paper trading only (enforced)
- Portfolio synchronization
- Order execution
- Position tracking

**Safety**:
- Explicitly configured for paper trading endpoint
- No real money can be used

### 7. Performance Tracking (`src/performance/`)

**Purpose**: Track agent and portfolio performance

**Components**:
- **PerformanceTracker**: Tracks individual agent performance
- **CyclePerformanceTracker**: Tracks cycle-to-cycle performance

**Metrics**:
- Returns (absolute and percentage)
- Win rates
- Sharpe ratio
- Maximum drawdown

**Weight Adjustment**:
- Automatically adjusts agent weights based on performance
- Smooth transitions (configurable smoothing factor)
- Min/max weight bounds

### 8. Backtesting Engine (`src/backtesting/engine.py`)

**Purpose**: Test strategies on historical data

**Features**:
- Historical data simulation
- Performance metrics calculation
- Agent performance analysis
- Equity curve generation

## Data Flow

### Weekly Trading Cycle

1. **Portfolio Sync**: Get current positions from Alpaca
2. **Data Refresh**: Fetch latest market data (cached when possible)
3. **Agent Analysis**: All agents analyze tickers in parallel
4. **Risk Calculation**: Calculate position limits for each ticker
5. **Decision Generation**: Aggregate signals and generate decisions
6. **Trade Execution**: Execute trades (if enabled)
7. **Performance Tracking**: Record cycle performance
8. **Weight Update**: Adjust agent weights based on performance

### Daily Update Cycle

1. **Portfolio Status**: Current positions and values
2. **Market Summary**: Market indices and trends
3. **Holdings Analysis**: Detailed position analysis
4. **Agent Status**: Current agent weights and performance

## Performance Optimizations

### Parallel Execution
- Agents run in parallel using ThreadPoolExecutor
- Data fetching parallelized for large universes
- Configurable worker count

### Caching
- 24-hour TTL for all financial data
- Memory cache (default) or Redis (optional)
- Reduces API calls significantly

### Batch Processing
- Large stock universes processed in batches
- Prevents memory issues
- Progress logging for monitoring

## Configuration

### Agent Weights (`config/agent_weights.json`)
- Controls influence of each agent
- Automatically adjusted based on performance
- Can be manually tuned

### Environment Variables (`.env`)
- API keys (Alpaca, LLM providers)
- Cache configuration
- Email settings

## Extensibility

### Adding New Agents
1. Create agent class inheriting from `BaseAgent`
2. Implement `analyze()` method
3. Register in `src/agents/initialize.py`
4. Add weight to `config/agent_weights.json`

### Adding New Data Providers
1. Implement `DataProvider` interface
2. Add to `DataAggregator.providers` list
3. Automatic fallback support

### Adding New Risk Metrics
1. Extend `RiskManager` class
2. Add new calculation methods
3. Integrate into position limit calculation

## Security Considerations

- Paper trading only (enforced at code level)
- API keys stored in environment variables
- No sensitive data in logs
- Error handling prevents system crashes

## Monitoring and Logging

- Structured logging with `structlog`
- Performance metrics tracked
- Error tracking and reporting
- Daily update reports

## Deployment Considerations

- Can run on local machine or cloud
- Redis optional (falls back to memory cache)
- No database required (file-based config)
- Stateless design (except cache)

