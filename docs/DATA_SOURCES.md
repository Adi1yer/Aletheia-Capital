# Data Sources and Agent Inputs

This document describes what data the system uses, what is missing, and how to close gaps so agents can operate with high confidence.

---

## What Agents Get Today

| Data | Source | Used by | Notes |
|------|--------|--------|--------|
| **Prices** (OHLCV) | Yahoo Finance (yfinance) | All agents, risk, portfolio | Cached (memory or Redis). |
| **Financial metrics** (P/E, ROE, growth, etc.) | Yahoo Finance | All agents | Cached. |
| **Line items** (revenue, FCF, balance sheet, etc.) | Yahoo Finance | Agents that need statements | Cached. |
| **Company news** | Yahoo Finance (yfinance) | News Sentiment Analyst | Implemented on Yahoo provider; list of recent headlines/summaries. |
| **Insider transactions** | **None** | **No agent** | Not currently pulled. See below. |

So: **we are not pulling insider data anywhere.** The data layer has a `get_insider_trades()` API and an `InsiderTrade` model, but the only provider (Yahoo) does not implement it and returns an empty list. No agent calls `get_insider_trades()` yet, so even after adding a provider, you’d want at least one agent to use the data.

---

## Why Insider Data Matters

Insider buying/selling (Form 4 filings: officers, directors, 10%+ holders) can signal conviction or risk. Agents that consider it can:

- Favor names with recent insider buying or reduced selling.
- Downgrade or avoid names with heavy insider selling.
- Combine insider flow with fundamentals and news for higher-confidence signals.

Without insider data, agents rely only on prices, fundamentals, and news.

---

## Workarounds for Insider Data

### 1. Add a provider that returns insider trades (recommended)

Implement a second provider that fills `get_insider_trades()` and add it to the aggregator. The aggregator already calls the first provider that returns non-empty data, so once a provider returns real trades, all callers get them.

**Option A: Finnhub (free tier)**  
- [Finnhub](https://finnhub.io/) has an [Insider Transactions](https://finnhub.io/docs/api/insider-transactions) endpoint.  
- Free tier: 60 calls/minute; good for moderate universe sizes.  
- Add `FinnhubProvider` that maps their response to our `InsiderTrade` model and implement `get_insider_trades(ticker, end_date, start_date, limit)`.  
- Set `FINNHUB_API_KEY` in `.env` and append `FinnhubProvider()` to `DataAggregator.providers` (e.g. after Yahoo).  
- Then have one or more agents call `data_provider.get_insider_trades(ticker, end_date, start_date, limit=20)` and include a short summary in the prompt (e.g. “Last N insider transactions: …”).

**Option B: SEC EDGAR (free, no key)**  
- SEC publishes [Insider Transactions Data Sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) (Forms 3/4/5): bulk files, updated periodically.  
- You can either: (1) periodically download and parse the bulk data and expose it via a small “SEC insider” service that your provider calls, or (2) use a third-party API that wraps EDGAR (e.g. SEC API, sec-api.io) if you’re okay with a paid/key-based option.  
- A custom `SECInsiderProvider` could load a preprocessed cache (e.g. by ticker/date) and implement `get_insider_trades()` from that cache.

**Option C: Polygon.io**  
- [Polygon](https://polygon.io/) has insider transaction data; paid plans.  
- Add a `PolygonProvider` with `get_insider_trades()` if you already use Polygon for other data.

### 2. Wire agents to use insider data once a provider exists

- In any agent that should consider insider activity (e.g. Fundamentals Analyst, a dedicated “Insider / Conviction” agent, or a value/quality agent), in `analyze()`:
  - Call `data_provider.get_insider_trades(ticker, end_date, start_date, limit=20)`.
  - If the list is non-empty, summarize it in a short string (e.g. “Last 20 insider transactions: …”) and add that to the context you send to the LLM (e.g. in the “Additional data” or “Insider activity” section of the prompt).
- That way, when you add Finnhub (or SEC or Polygon), those agents automatically start using insider data without further pipeline changes.

### 3. Optional: cache insider data

- Insider filings don’t change every minute. You can cache by `(ticker, start_date, end_date)` in the same way you cache prices/metrics (e.g. in `MemoryCache`/`RedisCache`) to reduce API calls and stay within Finnhub (or other) rate limits.

---

## Summary

| Gap | Status | What to do |
|-----|--------|------------|
| **Insider transactions** | Not pulled; no provider implements it | Add a provider (e.g. Finnhub) that implements `get_insider_trades()` and add it to the aggregator; then have at least one agent call it and pass a summary into the LLM. |
| **Company news** | Previously unimplemented on Yahoo | Implemented: Yahoo provider now returns company news from yfinance so the News Sentiment Analyst gets real headlines/summaries. |

After you add an insider provider and wire one or more agents to use `get_insider_trades()`, those agents will have access to both news and insider data, improving the chance of higher-confidence analysis.
