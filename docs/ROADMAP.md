# AI Hedge Fund – Plan & Todo

High-level plan and ordered todo list. Work through sections 1 → 5; section 6 is exploratory.

---

## 1. Immediate fixes (if needed)

- **1.1** Audit logs for any remaining `error` / `warning` that should be downgraded or fixed (universe, LLM, broker, email).
- **1.2** Ensure `equity` in portfolio status is populated when broker is used (email showed Equity: $0; may need to pass through from Alpaca or compute from positions).
- **1.3** Confirm timestamp in emails is human-readable and correct (e.g. avoid raw ISO in subject; use "Week of YYYY-MM-DD" or similar).
- **1.4** Quick smoke test after any change: `--tickers MSFT --max-stocks 1 --execute --email-to <you>` and check email + no new errors.

---

## 2. Improvements

### 2.1 Tighten prompts (fewer parse fallbacks)

- **2.1.1** Add a shared instruction (e.g. in `prompt_helpers` or each agent) that DeepSeek must respond with **only** a single JSON object, no markdown, no code fences, no explanation outside the JSON. Optionally include a one-line example: `{"signal":"neutral","confidence":0,"reasoning":"..."}`.
- **2.1.2** Apply the same to the portfolio manager decision prompt (action, quantity, confidence, reasoning).
- **2.1.3** After changes, run a small universe (e.g. 5–10 tickers) and confirm "DeepSeek structured parse failed" INFO lines drop.

### 2.2 Improve weekly email quality (later pass)

Goal: make the email **prettier** and **more insightful** so it’s something people look forward to receiving every week.

- **2.2.1** **Richer snapshot**
  - Include: cash, equity, **positions** (symbol, side, qty, cost basis or market value), open orders, recent filled orders (last N).
  - Add a short "Decisions summary" with **reasoning** (e.g. first 1–2 sentences per decision) and link to top agent signals if useful.
- **2.2.2** **Past performance**
  - Use **scan cache**: load previous run(s) for the same universe (e.g. last week’s run_id).
  - Compute and show: week-over-week change in portfolio value, P&amp;L on closed/held positions, number of orders executed last week vs this week.
  - Optional: table of "Last week’s top decisions vs outcome" (e.g. bought X, current P&amp;L on X).
- **2.2.3** **AI-generated insights (what’s to come)**
  - Add a step in the pipeline (or in the email builder) that:
    - Takes: current decisions, portfolio, recent risk/agent summary (from this run).
    - Calls the same LLM (DeepSeek) with a short prompt: "In 2–3 sentences, summarize the portfolio’s current stance and one key risk or opportunity for the week ahead."
  - Append this as a "Weekly outlook" or "AI insight" section in both text and HTML email.
- **2.2.4** **Formatting and “prettier” design**
  - Human-friendly date (e.g. "Week of Feb 25, 2026").
  - Clear sections: Summary stats → Portfolio status → Top decisions (with reasoning) → Past performance → AI outlook → Execution summary.
  - Visual polish: light styling (green/red for buy/sell), responsive tables, layout that feels premium and exciting to open weekly.

---

## 3. Optimizing files

- **3.1** List and remove **unused** agents or duplicate logic (e.g. two agents that do the same thing under different names).
- **3.2** Remove **unused** dependencies from `pyproject.toml` (e.g. packages that were tried but not used in the current flow).
- **3.3** Remove **redundant** or obsolete scripts (e.g. one-off migration scripts, old entrypoints that are no longer used).
- **3.4** Consolidate **config**: single source of truth for feature flags (e.g. crypto on/off, email on/off) and paths (scan cache, config dir).
- **3.5** Trim **dead code** in data providers, brokers, or pipeline (unused branches, commented blocks, duplicate helpers).

---

## 4. Universe + cache (after 1–3 are in good shape)

- **4.1** **Expand universe**
  - Add a reliable source for more tickers (e.g. S&amp;P 500 + NASDAQ-100 from a stable URL or bundled CSV; or a paid API). Goal: support `--max-stocks 200` (or more) with a real list, not only the 10-name fallback.
- **4.2** **Cache policy**
  - Define "weekly run": one run per month/week identified by date or run_id.
  - **Store**: only outputs needed for TTM/historical analysis (e.g. run metadata, tickers, signals, decisions, execution results, portfolio snapshot). Avoid storing raw HTML or redundant copies.
- **4.3** **Prune old cache**
  - Keep last N weeks (e.g. 12) or last N runs per universe size; delete or archive older cache dirs so disk doesn’t grow unbounded.
- **4.4** **Use cache in email**
  - When building "past performance", read from this canonical weekly cache (same structure for every run).

---

## 5. Exploratory and other

- **5.1** **Crypto arm**
  - Document current crypto pipeline (if any): how to enable (`CRYPTO_ENABLED`), which assets, and how it fits with the weekly run (e.g. separate cron vs same run).
  - Optional: one small run with `--crypto` and confirm no regressions; document in `docs/`.
- **5.2** **Politician / congressional arm**
  - Same idea: document and, if useful, ensure it’s a first-class data source for agents (already partially there via congressional trader).
- **5.3** **Backtesting / replay**
  - Optional: script or mode to replay past cached runs (e.g. "what would have happened if we had traded last week’s signals") for evaluation only.
- **5.4** **Alerts**
  - Optional: besides weekly email, support critical alerts (e.g. broker errors, margin threshold) via same email stack or a simple webhook.

---

## Todo list (tracking)

| ID | Item | Status |
|----|------|--------|
| 1 | Immediate: Audit errors/warnings; fix critical gaps | Completed |
| 2 | Improve: Tighten agent/PM prompts for JSON-only DeepSeek | Completed |
| 3 | Improve: Redesign weekly email – richer content, AI insights, past performance | Pending |
| 4 | Optimize: Remove unused code, redundant files, non-essential deps | Pending |
| 5 | Universe + cache: Expand universe; cache only weekly runs; prune old | Completed |
| 6 | Exploratory: Crypto arm, other ideas | Pending |

Update this table and the in-repo todo list as items are completed.
