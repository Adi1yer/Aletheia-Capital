# Full US Market Trading & Daily Updates

## Overview

The system now supports:
- **Full US Stock Market Universe**: Trade across all US-listed stocks (with liquidity filtering)
- **Weekly Trading**: Automated weekly trading cycle
- **Daily Updates**: Market information and portfolio status updates

## Full Market Trading

### Run Weekly Trading on Full US Market

```bash
# Dry run (no trades executed)
poetry run python src/main.py --universe --max-stocks 5000

# Execute trades (paper trading)
poetry run python src/main.py --universe --max-stocks 5000 --execute
```

### Options

- `--universe`: Use full US stock market (instead of specific tickers)
- `--max-stocks`: Maximum number of stocks to include (default: 5000)
- `--execute`: Execute trades (default: dry run)
- `--agents`: Filter to specific agents (optional)

### Liquidity Filtering

The system automatically filters stocks by:
- **Minimum Market Cap**: $50M (configurable)
- **Minimum Volume**: 100k shares/day average
- **Price**: Excludes penny stocks (< $1)
- **Exchange**: Excludes OTC stocks (configurable)

### Custom Tickers (Still Supported)

```bash
# Trade specific tickers
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL --execute
```

## Pipeline smoke check (optional)

Dry-run the stock trading pipeline for a couple of tickers (no orders):

```bash
poetry run python scripts/pipeline_smoke_check.py
poetry run python scripts/pipeline_smoke_check.py --tickers MSFT,AAPL
```

## Scheduling

### Weekly Trading (Cron)

Add to crontab for weekly trading (e.g., every Monday at 9 AM):

```bash
# Edit crontab
crontab -e

# Add this line (adjust path and time as needed)
0 9 * * 1 cd /path/to/ai-hedge-fund-production && poetry run python src/main.py --universe --max-stocks 5000 --execute
```

## Performance Considerations

### Large Universe Processing

- **Batch Processing**: Stocks are processed in batches of 100 to avoid memory issues
- **Caching**: All data is cached for 24 hours to reduce API calls
- **Progress Tracking**: Logs show batch progress for large universes

### Recommended Settings

- **Small Universe**: `--max-stocks 500` (faster, focused)
- **Medium Universe**: `--max-stocks 2000` (balanced)
- **Large Universe**: `--max-stocks 5000` (comprehensive, slower)

### Time Estimates

- **500 stocks**: ~30-60 minutes
- **2000 stocks**: ~2-4 hours
- **5000 stocks**: ~5-10 hours

*Times vary based on API rate limits and LLM response times*

## Configuration

### Adjust Liquidity Filters

Edit `src/data/universe.py`:

```python
universe = StockUniverse(
    min_market_cap=100_000_000,  # $100M minimum
    min_volume=500_000,  # 500k shares
    exclude_otc=True,
    exclude_penny_stocks=True,
    min_price=5.0,  # $5 minimum
)
```

## Data Requirements

The system automatically fetches:
- **Price Data**: Historical prices (3 months)
- **Financial Metrics**: P/E, P/B, ROE, etc.
- **Financial Statements**: Revenue, income, cash flow, debt, equity
- **Market Data**: Market cap, volume, etc.

All data is cached for 24 hours to minimize API calls.

## Example Workflow

1. **Monday Morning**: Run weekly trading
   ```bash
   poetry run python src/main.py --universe --max-stocks 2000 --execute
   ```

2. **Review**: Check `logs/` and `data/scan_cache` after weekly runs

## Notes

- **Paper Trading**: All trades are executed in Alpaca paper trading (no real money)
- **Rate Limits**: Yahoo Finance has rate limits; caching helps mitigate this
- **LLM Costs**: Using free LLM APIs (DeepSeek, Groq) minimizes costs
- **Data Quality**: Some stocks may have incomplete data; system handles gracefully

