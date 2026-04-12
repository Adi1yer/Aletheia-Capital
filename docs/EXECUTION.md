# Trading Execution Guide

## Paper Trading Setup

1. **Sign up** at [Alpaca](https://app.alpaca.markets/) and create a Paper Trading account.
2. **Get API keys**: Dashboard → API Keys → Generate new key.
3. **Add to `.env`** (copy from `.env.example`):
   ```bash
   ALPACA_API_KEY=your-paper-api-key-id
   ALPACA_SECRET_KEY=your-paper-secret-key
   ALPACA_BASE_URL=https://paper-api.alpaca.markets/v2
   ```
4. **Test execution**:
   ```bash
   poetry run python src/main.py --tickers AAPL,MSFT --execute
   ```
5. **Verify** orders in Alpaca Dashboard → Paper Trading → Orders.

## Paper → Live Migration

When ready for real money:

1. **Create Live Account** at Alpaca (minimum $2,000 for real money).
2. **Get Live API keys** from the Live Trading section.
3. **Update `.env`**:
   ```bash
   ALPACA_API_KEY=your-live-api-key-id
   ALPACA_SECRET_KEY=your-live-secret-key
   ALPACA_BASE_URL=https://api.alpaca.markets/v2
   ```
4. **Update broker** for live: Edit `src/broker/alpaca.py` to use live endpoint when `ALPACA_BASE_URL` contains `api.alpaca.markets` (not `paper-api`). Currently the broker hardcodes paper; add a `paper: bool` setting if you want to toggle.
5. **Start small**: Run with `--tickers` (5-10 stocks) before `--universe`.
6. **Monitor**: Check Alpaca Dashboard and scan cache for execution results.

## Dry Run (Default)

Without `--execute`, the pipeline generates decisions but does not place orders. Use this to validate signals and risk limits before enabling execution.

If Alpaca keys are set, the pipeline still syncs your **live cash and positions** from the broker at the start of each run (even in dry run). So dry-run decisions respect your actual account state; only order submission is skipped.

## How the portfolio manager uses your account

- **Cash**: Fetched from Alpaca at the start of each run via `broker.sync_portfolio()`. Used to cap buy size (e.g. `max_buy = cash // price`) and in equity for margin/short limits.
- **Positions**: Current long/short positions from Alpaca. Used to allow sell/cover only up to existing size, and to compute portfolio value for risk limits.
- **Orders**: **Open (pending) orders are now used.** The pipeline fetches open orders from Alpaca and passes them to the portfolio manager. Recommended buy size is reduced by any pending buy quantity for that symbol (so we don’t recommend buying 30 more when 10 are already on order). Sell is capped by (current long − pending sell). Once orders fill, the next run’s sync sees the updated positions, so position weight is reflected automatically.
