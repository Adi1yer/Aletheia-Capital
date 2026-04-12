# Full-Universe Agent Data Gaps: Do You Need to Pay?

Short answer: **No. You can close the main agent data gaps for entire-market scans without paying for API keys**, by using free data sources and accepting some extra runtime or one-time engineering. Paying becomes useful if you want **speed** (e.g. finish in minutes instead of an hour) or **commercial use** without rate-limit hassles.

Below is the picture for **full US market universe** (~3,000–3,500 tickers after liquidity filters), one scan per week.

---

## Per-gap: free vs paid at full-universe scale

### 1. Insider transactions

| Approach | Cost | Full-universe notes |
|----------|------|----------------------|
| **SEC EDGAR bulk data** | **$0** | Quarterly ZIPs (Form 3/4/5), no API key, no per-request limit. Download → parse → index by ticker → serve from your DB/cache. One-time or weekly refresh. **No per-ticker API cost.** |
| **Finnhub free tier** | **$0** | 60 calls/min → 3,500 tickers ≈ **58 minutes** of insider-only fetches per run. Doable in one go or overnight. Daily limit not a hard cap at that size. |
| **Finnhub paid** | Paid | 300+ calls/min → full universe in ~12 min. Pay if you want speed or higher/commercial limits. |

**Recommendation for full universe:** Use **SEC bulk data** for $0 and no rate-limit ceiling; add a small pipeline (download → parse → store → query by ticker). Finnhub free is viable if you’re okay with ~1 hour of insider fetches per run.

---

### 2. Relative strength vs market (SPY/QQQ)

| Approach | Cost | Full-universe notes |
|----------|------|----------------------|
| **Yahoo (yfinance)** | **$0** | Fetch `SPY` and `QQQ` (and optionally `^VIX`) like any other ticker. **2–3 series per run, not per ticker.** Same provider you already use. |

No new API key or payment. Just add these symbols to the data you pull once per run and compute ticker return vs index return.

---

### 3. Macro context (Druckenmiller)

| Approach | Cost | Full-universe notes |
|----------|------|----------------------|
| **Yahoo (yfinance)** | **$0** | SPY, QQQ, ^VIX for “market” context. **Same 2–3 series per run.** |
| **FRED (St. Louis Fed)** | **$0** | Free API key, 2 req/sec. You need **2–5 series per run** (e.g. 10Y yield, Fed funds), not per ticker. Trivial. |

No payment needed for full-universe runs.

---

### 4. Dividend (Graham – one period already added)

| Approach | Cost | Full-universe notes |
|----------|------|----------------------|
| **Yahoo (yfinance)** | **$0** | Already using it; dividend-inclusive line items (e.g. `dividends_and_other_cash_distributions`) are per-ticker but come from the same Yahoo provider you use for prices/financials. **No new API.** |
| **Dividend history (multi-period)** | **$0** | If you want multiple periods, same Yahoo provider can often expose more history; or use SEC/10-K/10-Q. No extra paid API required for basic history. |

No new paid keys for dividends at full-universe scale.

---

### 5. Analyst recommendations (News Sentiment Analyst)

| Approach | Cost | Full-universe notes |
|----------|------|----------------------|
| **Finnhub free** | **$0** | 60 calls/min → 3,500 tickers ≈ **58 minutes** per run for analyst data alone. Theoretically within free tier. |
| **Alpha Vantage free** | **Not viable** | ~25 requests/day → cannot do 3,500 tickers. |
| **Finnhub (or other) paid** | Paid | Faster (e.g. 300/min) so analyst data completes in ~12 min. |

So: **you don’t have to pay** for analyst data if you accept ~1 hour of rate-limited Finnhub calls per full-universe run. Paying is for **speed** and possibly **terms of use** (e.g. commercial).

---

### 6. Volume (Sentiment Analyst)

Already in your pipeline; no extra API. **$0.**

---

## Total “cost” for one full-universe scan (free path)

| Data type | Source | “Cost” |
|-----------|--------|--------|
| Prices, fundamentals, line items, news | Yahoo (current) | $0 |
| Insider | SEC bulk **or** Finnhub free | $0 (SEC = no limit; Finnhub = ~58 min) |
| Relative strength / macro | Yahoo + optional FRED | $0 |
| Dividend | Yahoo (current) | $0 |
| Analyst recommendations | Finnhub free (optional) | $0, ~58 min if you want it |

So: **no paid API keys are required** to advance agent data gaps for entire-market scans. You can do it with:

- **SEC bulk** for insider (free, no rate limit; some one-time build).
- **Yahoo** for SPY/QQQ/VIX, dividends, and everything you already have.
- **FRED** (free key) for macro if you want rates/PMI.
- **Finnhub free** only if you want insider or analyst via API (slower: ~60/min).

---

## When paying helps

- **Speed:** Finish insider + analyst in minutes instead of ~1 hour (e.g. Finnhub or other paid tier).
- **Commercial use:** Some free tiers are “personal” or “non-commercial”; paid clears that.
- **Higher rate limits:** Fewer 429s and simpler retry logic.
- **Support / SLA:** If you need reliability guarantees.

---

## Practical order (all free)

1. **Insider:** Build a small SEC bulk pipeline (download → parse → store by ticker) and a provider that reads from that store. $0, no per-run API limit.
2. **Relative strength + macro:** Add SPY/QQQ (and ^VIX) to one fetch per run; optionally 2–5 FRED series. Pass into Sentiment, Technicals, Druckenmiller. $0.
3. **Analyst (optional):** Add Finnhub free for analyst recommendations; accept ~58 min for 3,500 tickers once per run, or skip until you want to pay for speed.

So: **you do not have to pay for API keys to make progress on agent data gaps for full-universe scans.** You can do it with free sources; paying is mainly for speed and commercial peace of mind.
