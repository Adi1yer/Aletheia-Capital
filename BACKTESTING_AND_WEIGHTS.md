# Backtesting & Dynamic Agent Weight Adjustment

## Overview

The system now includes:
- **Backtesting Engine**: Test strategies on historical data
- **Performance Tracking**: Track agent returns over time
- **Dynamic Weight Adjustment**: Automatically adjust agent weights based on performance

## How Agent Weights Work

### Current System

1. **Initial Weights**: All agents start with weight 1.0 (equal weighting)
2. **Weight Usage**: Weights multiply agent confidence scores when aggregating signals
   - Higher weight = agent's opinion counts more
   - Lower weight = agent's opinion counts less
3. **Signal Aggregation**: 
   - Bullish signals: `bullish_score += confidence * weight`
   - Bearish signals: `bearish_score += confidence * weight`
   - Final decision based on weighted scores

### Dynamic Weight Adjustment

After each trading cycle, the system:

1. **Tracks Performance**: 
   - Compares agent signals from previous cycle to actual price movements
   - Calculates return contribution for each agent
   - Agents with correct signals (bullish when price went up, bearish when price went down) get positive returns
   - Agents with incorrect signals get negative returns

2. **Calculates New Weights**:
   - Agents with higher average returns get higher weights (up to 3.0x)
   - Agents with lower average returns get lower weights (down to 0.1x)
   - Smooth adjustment (20% per cycle) to avoid sudden changes

3. **Updates Automatically**:
   - Weights saved to `config/agent_weights.json`
   - Applied in next trading cycle
   - Performance data stored in `data/performance/`

### Weight Calculation Formula

```
normalized_return = (agent_return - min_return) / (max_return - min_return)
target_weight = 0.1 + (normalized_return * 2.9)  # Range: 0.1 to 3.0
new_weight = current_weight + (target_weight - current_weight) * 0.2  # 20% adjustment
```

## Backtesting Engine

### Run Backtest

```bash
# Backtest specific tickers
poetry run python src/backtest.py --tickers AAPL,MSFT,GOOGL --start-date 2023-01-01 --end-date 2024-01-01

# Backtest full universe
poetry run python src/backtest.py --universe --max-stocks 500 --start-date 2023-01-01 --end-date 2024-01-01

# Save results
poetry run python src/backtest.py --tickers AAPL,MSFT --start-date 2023-01-01 --end-date 2024-01-01 --output backtest_results.json
```

### What Backtesting Does

1. **Simulates Trading**: Runs your strategy on historical data
2. **Tracks Performance**: 
   - Total return
   - Sharpe ratio
   - Max drawdown
   - Win/loss ratio
   - Agent performance
3. **Agent Analysis**: Shows which agents performed best during the period

### Backtest Results Include

- **Total Return**: Overall strategy return
- **Sharpe Ratio**: Risk-adjusted return metric
- **Max Drawdown**: Worst peak-to-trough decline
- **Trade Statistics**: Win rate, total trades
- **Agent Performance**: Individual agent returns and win rates
- **Equity Curve**: Portfolio value over time

## Performance Tracking

### How It Works

1. **Between Cycles**: 
   - System stores agent signals and prices from each trading cycle
   - Next cycle compares current prices to previous prices
   - Calculates returns based on signal accuracy

2. **Return Calculation**:
   - If agent was bullish and price went up → positive return
   - If agent was bearish and price went down → positive return
   - If agent was wrong → negative return
   - Return weighted by agent's confidence

3. **Accumulation**:
   - Returns accumulated over multiple cycles
   - Average return calculated for each agent
   - Used to determine new weights

### Performance Data Storage

- Location: `data/performance/agent_performance.json`
- Contains: Trade history, returns, win rates for each agent
- Persists: Data saved between runs

## Automatic Weight Updates

### When Weights Update

- **After Each Trading Cycle**: System automatically calculates and updates weights
- **Gradual Adjustment**: 20% adjustment per cycle (smoothing factor)
- **Min/Max Limits**: Weights clamped between 0.1 and 3.0

### Viewing Current Weights

```bash
# Check config file
cat config/agent_weights.json

# Weights are automatically updated after each trading cycle
```

### Manual Weight Override

You can manually set weights in `config/agent_weights.json`:
```json
{
  "warren_buffett": 2.5,
  "cathie_wood": 0.5,
  ...
}
```

The system will still adjust these over time based on performance.

## Example Workflow

1. **Week 1**: All agents have weight 1.0
2. **Week 1 Trading**: System makes decisions, tracks signals
3. **Week 2**: 
   - System calculates returns from Week 1 signals
   - Warren Buffett agent had +5% average return
   - Cathie Wood agent had -2% average return
   - Weights adjust: Buffett → 1.2, Wood → 0.9
4. **Week 2 Trading**: Buffett's signals now count 1.2x, Wood's count 0.9x
5. **Repeat**: Weights continue adjusting based on performance

## Benefits

1. **Self-Improving**: System learns which agents perform best
2. **Adaptive**: Weights adjust to market conditions
3. **Data-Driven**: Based on actual returns, not assumptions
4. **Gradual**: Smooth adjustments prevent over-reaction

## Configuration

### Adjust Weight Parameters

Edit `src/trading/pipeline.py` in `_update_agent_weights()`:

```python
new_weights = self.performance_tracker.calculate_weights_from_performance(
    min_weight=0.1,      # Minimum weight (default: 0.1)
    max_weight=3.0,      # Maximum weight (default: 3.0)
    smoothing_factor=0.2,  # Adjustment speed (default: 0.2 = 20% per cycle)
)
```

- **Lower smoothing_factor**: Slower adjustment (more stable)
- **Higher smoothing_factor**: Faster adjustment (more responsive)

## Notes

- **First Cycle**: No previous data, so weights stay at 1.0
- **Minimum Trades**: Agents need some trade history before weights adjust significantly
- **Performance Persists**: Performance data saved between runs
- **Backtesting**: Use backtesting to test weight adjustment strategies before live trading

