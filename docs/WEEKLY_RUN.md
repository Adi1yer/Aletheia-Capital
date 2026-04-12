# Weekly Run: Scan, Trade, Cache, Email

This doc describes the **single weekly process** and how to set it up.

## What one run does

Each `python src/main.py ...` run does everything in order:

1. **Sync from Alpaca** – Cash, positions, open orders (so decisions respect your live state).
2. **Refresh market data** – Prices, fundamentals, news, etc. for the chosen universe/tickers.
3. **Run agents** – All agents analyze and produce signals (uses DeepSeek if `DEEPSEEK_API_KEY` is set, else Ollama).
4. **Risk & decisions** – Position limits and portfolio manager produce final buy/sell/hold per ticker.
5. **Execute on Alpaca** – If `--execute` is passed, orders are placed (paper or live per your keys).
6. **Cache the run** – Full run (signals, decisions, risk, portfolio) is saved under `data/scan_cache/` for later analysis.
7. **Send email** – If `--email` or `--email-to` is set and SMTP is configured, a summary is sent.

So you do **not** need two steps (scan then trade). One weekly command does scan + agents + trade + cache + optional email.

---

## 1. Get a DeepSeek API key (recommended for universe runs)

- **Why:** For 50+ tickers, Ollama is too slow. With `DEEPSEEK_API_KEY` set, agents use DeepSeek and runs stay feasible (see `docs/SCALING.md`).
- **Get key:** https://platform.deepseek.com
- **Add to `.env`:**
  ```bash
  DEEPSEEK_API_KEY=your-deepseek-api-key
  ```

---

## 2. Configure email (for weekly updates to you)

Email is sent **after** the run if SMTP is configured and you pass `--email` or `--email-to`.

**Option A – Gmail (app password)**

1. In Gmail: Account → Security → 2-Step Verification (enable if needed) → App passwords. Create an app password for “Mail”.
2. In `.env`:
   ```bash
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   SENDER_EMAIL=your.gmail@gmail.com
   SENDER_PASSWORD=your-16-char-app-password
   ```
3. Run with:
   ```bash
   --email-to aditya.iyer@gmail.com
   ```
   Or set in `.env`: `RECIPIENT_EMAIL=aditya.iyer@gmail.com` and use `--email`.

**Option B – Other SMTP**

Set `SMTP_SERVER`, `SMTP_PORT`, `SENDER_EMAIL`, `SENDER_PASSWORD` in `.env` for your provider, then use `--email-to aditya.iyer@gmail.com` when running.

---

## 3. Weekly command examples

**Ticker list (e.g. 10–20 names), execute + email:**

```bash
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL,NVDA,TSLA,AMZN,META --execute --email-to aditya.iyer@gmail.com
```

**Universe (e.g. top 100 by market cap), execute + email:**

```bash
poetry run python src/main.py --universe --max-stocks 100 --execute --email-to aditya.iyer@gmail.com
```

**Using the wrapper script (logs to `logs/weekly_scan_*.log`):**

```bash
./scripts/run_weekly_scan.sh --universe --max-stocks 100 --execute --email-to aditya.iyer@gmail.com
```

---

## 4. Schedule weekly (cron)

Run once per week (e.g. Sunday 6 PM) from the project directory.

```bash
crontab -e
```

Add (replace `/path/to/ai-hedge-fund-production` with your project path):

```cron
# Weekly: scan universe, execute trades, cache run, email aditya.iyer@gmail.com
0 18 * * 0 cd /path/to/ai-hedge-fund-production && ./scripts/run_weekly_scan.sh --universe --max-stocks 100 --execute --email-to aditya.iyer@gmail.com
```

Or with a fixed ticker list:

```cron
0 18 * * 0 cd /path/to/ai-hedge-fund-production && ./scripts/run_weekly_scan.sh --tickers AAPL,MSFT,GOOGL,NVDA,TSLA --execute --email-to aditya.iyer@gmail.com
```

Ensure the script is executable: `chmod +x scripts/run_weekly_scan.sh`.

---

## 5. Checklist before going weekly

| Step | Done |
|------|------|
| DeepSeek API key in `.env` (for larger universes) | |
| Alpaca keys in `.env` (paper or live) | |
| SMTP settings in `.env` (Gmail or other) | |
| One test run with `--execute --email-to aditya.iyer@gmail.com` | |
| Cron (or other scheduler) set for weekly | |

---

## 6. Where things are stored

- **Run cache:** `data/scan_cache/<run_id>/` (signals, decisions, risk, portfolio before/after).
- **Agent weights:** `config/agent_weights.json` (updated after each run from performance).
- **Logs:** `logs/weekly_scan_*.log` when using `run_weekly_scan.sh`.

After every weekly run you get: Alpaca orders (if `--execute`), cached run data, and an email to aditya.iyer@gmail.com if email is configured and `--email-to` or `--email` is used.
