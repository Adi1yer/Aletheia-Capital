# Scaling Guide: Ticker Universe and Runtime

## Runtime Expectations

| Tickers | Agents | Combinations | Ollama (local) | DeepSeek (cloud) |
|---------|--------|--------------|---------------|-----------------|
| 2       | 21     | 42           | ~15 min       | ~3–5 min        |
| 10      | 21     | 210          | ~1–1.5 hr     | ~10–15 min      |
| 20      | 21     | 420          | ~2–3 hr       | ~15–25 min      |
| 50      | 21     | 1,050        | ~5–8 hr       | ~30–45 min      |
| 100     | 21     | 2,100        | ~10+ hr       | ~1–1.5 hr       |
| 500+    | 21     | 10,500+      | Not feasible  | ~3–6 hr         |

## Scaling Options

### Option A: Ollama (Local, 2–20 Tickers)

Default. No API key needed. Good for testing and small universes.

```bash
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL,NVDA,TSLA
# Or 20 tickers
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL,NVDA,TSLA,... 
```

### Option B: DeepSeek (Cloud, 20+ Tickers)

Add `DEEPSEEK_API_KEY` to `.env`. When set, all agents use DeepSeek instead of Ollama.

1. Get key from [platform.deepseek.com](https://platform.deepseek.com).
2. Add to `.env`:
   ```bash
   DEEPSEEK_API_KEY=your-deepseek-api-key
   ```
3. Run larger universe:
   ```bash
   poetry run python src/main.py --universe --max-stocks 100
   ```

See [CLOUD_SCALING_ANALYSIS.md](../CLOUD_SCALING_ANALYSIS.md) for full market (3,500 stocks) estimates.

## DeepSeek API cost (how much to load)

Pricing is per token ([Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)):

| Type | Price per 1M tokens |
|------|----------------------|
| Input (cache miss) | $0.28 |
| Input (cache hit)  | $0.028 |
| Output            | $0.42 |

One weekly run uses roughly **22 agents × N tickers** analyses plus **N** portfolio-manager calls. Per ticker: ~50–60K input tokens and ~8K output tokens (order of magnitude).

| Tickers per run | Est. cost per run | Est. per month (4 runs) |
|-----------------|-------------------|--------------------------|
| 20  | ~$0.40–0.60 | ~$2–2.50 |
| 50  | ~$1.00–1.50 | ~$5–6 |
| 100 | ~$2.00–3.00 | ~$10–12 |
| 200 | ~$4.00–6.00 | ~$18–24 |

**Recommendation:** Start with **$15–25** loaded. That covers multiple weeks at 50–100 tickers, or a few runs at 200 tickers, with buffer. Top up based on usage; you can check balance and usage on the [DeepSeek platform](https://platform.deepseek.com).
