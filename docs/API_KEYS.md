# API Keys and Agent Data Gaps

To advance the agent data gaps (insider transactions, analyst recommendations), use a **Finnhub** API key. It’s free and supports the features we need.

## Finnhub (insider + analyst)

- **Sign up:** [https://finnhub.io/register](https://finnhub.io/register)
- **Get key:** Dashboard → API Key
- **Add to `.env`:**
  ```bash
  FINNHUB_API_KEY=your-finnhub-api-key
  ```
- **What it enables:**
  - **Insider transactions** – Used by value/management agents (e.g. Buffett, Graham, Burry, Munger, Ackman, Fisher, Fundamentals Analyst, Druckenmiller). When the key is set, the aggregator adds the Finnhub provider and agents receive a “Recent insider activity” summary in their prompts.
  - **Analyst recommendations** – Used by News Sentiment Analyst. When the key is set, the agent receives analyst recommendation trends (strongBuy, buy, hold, sell, strongSell) in its prompt.
- **Free tier:** 60 API calls per minute. For full-universe scans this means ~1 hour of rate-limited insider/analyst fetches per run, or use SEC bulk data for insider (no key) and Finnhub only for analyst.

## Alpaca (paper/live trading)

- **Required for** `--execute` (actual order execution).
- **Sign up:** [Alpaca](https://app.alpaca.markets/) → Paper Trading for testing.
- **Add to `.env`:**
  ```bash
  ALPACA_API_KEY=your-api-key-id
  ALPACA_SECRET_KEY=your-secret-key
  ALPACA_BASE_URL=https://paper-api.alpaca.markets/v2
  ```
- **See:** [docs/EXECUTION.md](EXECUTION.md) for paper → live migration.

## Other keys (optional)
- **DeepSeek** – LLM for scaling to large universes (see CLOUD_SCALING_ANALYSIS.md).
- **DEEPSEEK_API_KEY** in `.env` – Agents use DeepSeek when set; otherwise Ollama.

Once `FINNHUB_API_KEY` is set, restart the app (or run a new scan). No code changes needed; the aggregator picks up the key and adds the Finnhub provider automatically.

## Congressional trades (optional)

- **Congressional Trader agent** uses disclosed trades by US Congress members (STOCK Act).
- **Finnhub**: If `FINNHUB_API_KEY` is set, congressional data is attempted via Finnhub (if endpoint available).
- **FinBrain**: Set `CONGRESSIONAL_API_KEY` (FinBrain House Trades API) for additional coverage.
- Get key: [FinBrain](https://finbrain.tech/) or use Finnhub key for congressional when supported.

## Crypto (optional)

- **Crypto pipeline** (`--crypto`): Runs crypto agents on BTC, ETH, SOL, etc.
- **Enable**: Set `CRYPTO_ENABLED=true` in `.env` or it is set automatically when using `--crypto`.
- **CoinGecko**: Free tier works without a key; `COINGECKO_API_KEY` optional for higher limits.
