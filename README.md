# AI Hedge Fund - Production System

A production-ready AI-powered hedge fund trading system using multiple specialized agents.

## Features

- **Multi-Agent System**: 21 specialized investment agents (Warren Buffett, Ben Graham, Peter Lynch, etc.)
- **Free Data Sources**: Yahoo Finance with caching support
- **Free LLM Integration**: Multi-model support (DeepSeek, Groq, Ollama)
- **Risk Management**: Volatility and correlation-adjusted position limits
- **Portfolio Management**: Intelligent trade execution within risk constraints
- **Weekly Trading**: Automated weekly rebalancing and opportunity detection
- **Paper Trading**: Alpaca integration (paper trading only, enforced)
- **Performance Tracking**: Dynamic agent weight adjustment based on performance
- **Parallel Execution**: Fast parallel agent analysis and data fetching
- **Redis Caching**: Optional distributed caching for better performance
- **Comprehensive Testing**: Unit tests, integration tests, and backtesting validation
- **Full Documentation**: API docs, architecture guide, and deployment instructions

## Setup

See **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)** for full setup (Python 3.11+, Poetry, Ollama or cloud API, .env). Quick path: `poetry install` → `cp .env.example .env` → add Alpaca (and optional LLM) keys → `poetry run python src/main.py --tickers AAPL,MSFT,GOOGL`.

## Project Structure

```
ai-hedge-fund-production/
├── src/
│   ├── agents/          # Investment agent implementations (21 agents)
│   ├── data/            # Data providers and caching (memory + Redis)
│   ├── llm/             # LLM integration layer
│   ├── broker/          # Broker API integration (Alpaca)
│   ├── risk/            # Risk management
│   ├── portfolio/       # Portfolio management
│   ├── trading/         # Trading pipeline (with parallel execution)
│   ├── performance/     # Performance tracking
│   ├── backtesting/     # Backtesting engine
│   └── utils/           # Utilities and helpers
├── config/              # Configuration files
├── docs/                # Documentation (API, Architecture, Deployment)
├── logs/                # Log files
└── tests/               # Comprehensive test suite
```

## Quick Start

### 1. Install Dependencies
```bash
poetry install
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your Alpaca API keys
```

### 3. Run Weekly Trading
```bash
# Dry run (no trades executed)
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL

# Execute trades
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL --execute

# Full market trading
poetry run python src/main.py --universe --max-stocks 2000 --execute
```

### 4. Get Daily Updates
```bash
poetry run python src/daily_update.py
```

## Configuration

See `config/` directory for agent configurations, weights, and trading parameters.

## Documentation

- **Getting started**: `docs/GETTING_STARTED.md` - Setup and first run (start here)
- **Doc index**: `docs/README.md` - List of all documentation
- **API Reference**: `docs/API.md` - Complete API documentation
- **Architecture**: `docs/ARCHITECTURE.md` - System architecture and design
- **Deployment**: `docs/DEPLOYMENT.md` - Deployment guide for various environments
- **Data sources**: `docs/DATA_SOURCES.md` - Data providers and insider-trading workarounds
- **Enhancements**: `docs/ENHANCEMENTS.md` - Recent improvements and features

## Testing

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=src --cov-report=html

# Run specific test file
poetry run pytest tests/test_agents.py
```

## Performance Features

- **Parallel Agent Execution**: Agents run in parallel for faster analysis
- **Parallel Data Fetching**: Data fetched in parallel for large universes
- **Redis Caching**: Optional distributed caching (falls back to memory cache)
- **Batch Processing**: Efficient processing of large stock universes

## Disclaimer

This system is for educational and research purposes. Past performance does not guarantee future results.

