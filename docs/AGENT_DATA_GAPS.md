# Agent Data Gaps and How to Fix Them

This document lists, per agent, what each is **supposed to interpret** (from their prompts and style) versus **what data they actually get**, and what’s missing. Then it gives **concrete steps and suggestions** so every agent has the inputs they need.

---

## Summary Table

| Gap | Affected agents | Severity |
|-----|-----------------|----------|
| **Insider transactions** | All value/quality/management-focused agents (see below) | High – prompt themes like "management conviction" |
| **Volume in prompt** | Sentiment Analyst | Medium – prompt asks for volume, data not passed |
| **Dividend (current + history)** | Ben Graham | Medium – "dividend history" in criteria |
| **Analyst ratings / recommendations** | News Sentiment Analyst | Medium – "analyst coverage and recommendations" |
| **Relative strength vs market** | Sentiment Analyst, Technicals Analyst | Medium – need index (SPY/QQQ) data |
| **Macro data** | Stanley Druckenmiller | Medium – "macro trends and major market themes" |
| **Company news** | Sentiment Analyst (optional) | Low – could reinforce sentiment |

---

## Per-Agent: What They Get vs What They’re Supposed to Use

### 1. Warren Buffett
- **Gets:** Financial metrics, line items (revenue, net income, FCF, debt, equity), market cap.
- **Prompt emphasizes:** Moat, earnings growth, ROE, low debt, **management quality and shareholder-friendly policies**, valuation.
- **Missing:** **Insider trades** (as a proxy for management conviction and alignment). No management or governance data.

### 2. Aswath Damodaran
- **Gets:** Metrics, line items, market cap, prices.
- **Prompt emphasizes:** Valuation (DCF, multiples), risk-adjusted returns.
- **Missing:** **Insider** (optional for conviction). Otherwise well covered.

### 3. Ben Graham
- **Gets:** Metrics, line items (debt, cash, equity, net income, assets), market cap, current price.
- **Prompt emphasizes:** Margin of safety, P/B, current ratio, **consistent earnings and dividend history**.
- **Missing:** **Dividend data** (not requested in `get_line_items`; Graham doesn’t get `dividends_and_other_cash_distributions`). **Dividend history** would require multiple periods or a dedicated dividend history API. **Insider** (optional).

### 4. Bill Ackman
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** Quality, **strong shareholder-friendly management**, activism.
- **Missing:** **Insider** (management conviction). Optional: news (for activism/catalysts).

### 5. Cathie Wood
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** Innovation, disruption, long-term growth.
- **Missing:** **Insider** (optional). Otherwise adequate.

### 6. Charlie Munger
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** **Strong management with integrity**, quality, valuation.
- **Missing:** **Insider** (management alignment).

### 7. Michael Burry
- **Gets:** Metrics, line items, market cap, prices.
- **Prompt emphasizes:** Deep value, contrarian, balance sheet, **fundamental analysis over market sentiment**.
- **Missing:** **Insider** (strong contrarian signal when insiders buy). Optional: news for sentiment context.

### 8. Mohnish Pabrai
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** Clone investing, quality, margin of safety.
- **Missing:** **Insider** (optional).

### 9. Peter Lynch
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** GARP, PEG, earnings/revenue growth.
- **Missing:** **Insider** (optional). **Dividend** not requested (could add for yield context).

### 10. Phil Fisher
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** **Superior management**, growth, 15-point checklist.
- **Missing:** **Insider** (management conviction).

### 11. Rakesh Jhunjhunwala
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** Growth, **strong management and execution**.
- **Missing:** **Insider** (conviction).

### 12. Stanley Druckenmiller
- **Gets:** Metrics, line items, market cap, prices (momentum).
- **Prompt emphasizes:** **Macro trends and major market themes**, momentum, risk management.
- **Missing:** **Macro data** (rates, indices, sector/theme performance). We only have single-name data. **Insider** (optional).

### 13. Valuation Analyst
- **Gets:** Metrics, line items, market cap, prices.
- **Prompt emphasizes:** DCF, multiples, fair value.
- **Missing:** **Insider** (optional). Otherwise well covered.

### 14. Sentiment Analyst
- **Gets:** Metrics, prices (momentum, **volatility**), market cap. Does **not** pass volume or news to the prompt.
- **Prompt emphasizes:** **Investor sentiment (price momentum, volume)**, **relative strength vs market**, contrarian signals, fear/greed.
- **Missing:** **Volume** (we have it in the price series but don’t include avg_volume / recent_volume in the prompt). **Index data** (SPY/QQQ) to compute relative strength vs market. **Analyst sentiment** (no analyst data). Optional: **company news** to enrich sentiment.

### 15. Fundamentals Analyst
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** Balance sheet, profitability, growth, quality.
- **Missing:** **Insider** (optional). **Prices** (optional for trend). Otherwise adequate.

### 16. Technicals Analyst
- **Gets:** Prices only (OHLCV, SMA 20/50, momentum, **volume ratio**). Volume is passed.
- **Prompt emphasizes:** Trends, volume, **relative strength indicators**.
- **Missing:** **Relative strength vs market** (we don’t have index data; "relative strength" in prompt is partly satisfied by our momentum stats but not vs benchmark). Optional: index series for SPY/QQQ.

### 17. Growth Analyst
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** Revenue/earnings growth, quality of growth.
- **Missing:** **Insider** (optional). Otherwise adequate.

### 18. News Sentiment Analyst
- **Gets:** Metrics, **company news** (Yahoo), prices, market cap.
- **Prompt emphasizes:** Company news sentiment, **analyst coverage and recommendations**, media perception, news impact.
- **Missing:** **Analyst ratings / price targets / recommendations** (we have no data source for this). News is now provided.

### 19. Aditya Iyer
- **Gets:** Metrics, line items, market cap, prices (for momentum).
- **Prompt emphasizes:** Value, growth, quality, **technical indicators**, **sentiment and market positioning**.
- **Missing:** **Insider**. Richer **technical** context (e.g. volume, volatility) and explicit **sentiment** (news or analyst) would help.

### 20. Chamath Palihapitiya
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** Disruption, **strong management**, conviction.
- **Missing:** **Insider** (management conviction).

### 21. Ron Baron
- **Gets:** Metrics, line items, market cap.
- **Prompt emphasizes:** Long-term growth, **strong management**, 10x potential.
- **Missing:** **Insider** (conviction).

---

## Steps and Suggestions to Give Agents What They Need

### Step 1: Add insider data (highest impact)

- **What:** Implement a provider that returns insider transactions (e.g. Finnhub) and add it to the aggregator. Have every agent that mentions "management," "conviction," or "shareholder" call `get_insider_trades(ticker, end_date, start_date, limit=20)` and include a short summary in the prompt (e.g. "Recent insider activity: …").
- **Agents to wire:** Warren Buffett, Ben Graham, Bill Ackman, Charlie Munger, Michael Burry, Phil Fisher, Rakesh Jhunjhunwala, Stanley Druckenmiller, Valuation Analyst, Fundamentals Analyst, Growth Analyst, Aditya Iyer, Chamath Palihapitiya, Ron Baron. (Mohnish Pabrai, Peter Lynch, Cathie Wood, Aswath Damodaran can be added optionally.)
- **How:** See `docs/DATA_SOURCES.md` (Finnhub provider, aggregator, then add 2–3 lines in each agent’s `analyze()` to fetch and format insider data).

### Step 2: Pass volume into Sentiment Analyst

- **What:** Sentiment Analyst already has price series (with volume). Compute `avg_volume` and `recent_volume` (e.g. last 5–10 days) and add them to `analysis_data` and to the human prompt (e.g. "Avg Volume (20d): X, Recent Volume: Y, Volume Ratio: Z").
- **Why:** Prompt explicitly asks for "investor sentiment (price momentum, volume)." Right now the model never sees volume.

### Step 3: Add dividend data for Ben Graham (and optional others)

- **What:**  
  - Request **one period’s dividend** in Graham’s `get_line_items`: add `"dividends_and_other_cash_distributions"` to the line_items list so he at least sees current-period payout.  
  - For **dividend history** (multiple years), either: (a) request multiple periods of line items (e.g. `limit=4` and pass last 4 quarters/years), or (b) add a small dividend-history API (e.g. Yahoo or a provider that exposes historical dividends) and a `get_dividend_history(ticker, start_date, end_date)` on the data provider; then have Graham (and optionally Peter Lynch) consume it in the prompt.
- **Why:** Graham’s criteria include "consistent earnings and dividend history."

### Step 4: Relative strength vs market (Sentiment + Technicals)

- **What:** Fetch benchmark prices (e.g. SPY and/or QQQ) for the same `start_date`–`end_date` as the ticker. Compute ticker return vs benchmark return over the window and pass "Return vs SPY: +X%" (or vs QQQ) into the Sentiment Analyst and Technicals Analyst prompts.
- **How:** Use the same `get_prices("SPY", start_date, end_date)` (and QQQ) from the existing data provider; compute period return for ticker and for SPY/QQQ; add one line to the prompt. No new provider required if Yahoo already gives index ETFs.

### Step 5: Analyst recommendations (News Sentiment Analyst)

- **What:** The prompt asks for "analyst coverage and recommendations." Options:  
  - **A)** Add a data source that provides analyst ratings/price targets (e.g. Finnhub, Alpha Vantage, or another provider with an "analyst recommendations" or "price target" endpoint), add `get_analyst_recommendations(ticker)` (or similar) to the provider interface, and have News Sentiment Analyst call it and add a short "Analyst summary: …" to the prompt.  
  - **B)** If you don’t add a source, soften the prompt to say "where available, consider analyst coverage" and rely on company news only until you have data.
- **Recommendation:** Implement (A) when you have an API; otherwise (B) avoids implying we have data we don’t.

### Step 6: Macro data (Stanley Druckenmiller)

- **What:** To truly support "macro trends and major market themes," the agent needs macro or market context: e.g. risk-free rate, index returns (SPY/QQQ), sector or theme performance, or volatility index (VIX).  
- **How:** Fetch SPY/QQQ (and optionally VIX) via the same price provider; pass to Druckenmiller only: e.g. "SPY return (period): X%, QQQ return: Y%, Risk environment: …" so the LLM can reason about macro/market context. A dedicated macro provider (rates, PMIs) can be added later.

### Step 7: Optional: News for Sentiment Analyst

- **What:** Have Sentiment Analyst call `get_company_news(ticker, end_date, start_date, limit=5)` and append a short "Recent headlines: …" to the prompt.  
- **Why:** Enriches "market psychology" and "sentiment-driven opportunities" with actual news flow.

### Step 8: Optional: Richer technical/sentiment for Aditya Iyer

- **What:** Aditya Iyer’s prompt mentions "technical indicators" and "sentiment and market positioning." He already gets price and price_change. Optionally add: volume (avg/recent), volatility (e.g. 20d), and a one-line news or insider summary so the multi-factor agent has a bit of technical and sentiment context without duplicating full Technicals or Sentiment logic.

---

## Implementation Priority

| Priority | Action | Agents helped |
|----------|--------|----------------|
| 1 | Add insider provider + wire insider summary into 14 value/quality/management agents | Buffett, Graham, Ackman, Munger, Burry, Fisher, Jhunjhunwala, Baron, Phil Fisher, Ron Baron, Chamath, Aditya Iyer, Valuation, Fundamentals, Growth, Druckenmiller |
| 2 | Pass volume into Sentiment Analyst prompt | Sentiment Analyst |
| 3 | Add dividend (one period + optional history) for Graham | Ben Graham (and optionally Lynch) |
| 4 | Add SPY/QQQ return vs ticker return (relative strength) | Sentiment Analyst, Technicals Analyst |
| 5 | Add analyst recommendations API + wire to News Sentiment | News Sentiment Analyst |
| 6 | Add macro context (SPY/QQQ/VIX) for Druckenmiller | Stanley Druckenmiller |
| 7 | Optional: news in Sentiment Analyst; richer technical/sentiment for Aditya Iyer | Sentiment Analyst, Aditya Iyer |

After Step 1 and 2, every agent either has the data their prompt implies or the doc above explicitly calls out what’s still optional (e.g. analyst data, macro). Implementing Steps 1–4 will remove the main gaps; 5–6 improve News Sentiment and Druckenmiller specifically; 7 is optional polish.
