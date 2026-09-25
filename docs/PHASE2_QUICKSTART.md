# Phase 2: VRP Edge Quick Start

**Status**: Infrastructure complete (PR #3) — awaiting market IV data

---

## What's Ready

✅ **CsvIVProvider**: Drop-in real market IV from CSV  
✅ **PolygonIVProvider stub**: Ready for API key + implementation  
✅ **SPY Total Return**: Benchmark now uses ^SPXTR (fixes ~2% dividend gap)  
✅ **Bake-off harness**: Compare edge-gated vs always-on strategies  
✅ **Tests**: All passing (IV provider + integration smoke test)  
✅ **Docs**: Roadmap updated, whitepaper status noted  

---

## How to Validate VRP Edge

### Option 1: Drop In Market IV CSV

**Step 1**: Get or generate market IV data in CSV format:
```csv
date,symbol,atm_iv,iv_rank
2020-01-02,AAPL,0.2500,0.45
2020-01-02,MSFT,0.1800,0.32
2020-01-03,AAPL,0.2600,0.48
2020-01-03,MSFT,0.1900,0.35
```

**Field definitions**:
- `date`: YYYY-MM-DD
- `symbol`: Ticker (uppercase)
- `atm_iv`: At-the-money implied volatility as **decimal** (0.25 = 25% annualized vol)
- `iv_rank`: IV rank 0.0-1.0 (optional, can be empty)

**Step 2**: Run bake-off to compare edge-gated vs always-on:
```bash
scripts/run_vrp_bakeoff.py \
  --iv-csv data/market_iv.csv \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --universe bluechip \
  --min-vrp 0.10 \
  --out docs/backtest_results/wheel_hybrid/bakeoff_2020_2024
```

**Step 3**: Review results:
```bash
cat docs/backtest_results/wheel_hybrid/bakeoff_2020_2024/bakeoff_2020-01-01_2024-12-31.json
```

Look for:
- `comparison.abs_return_delta_pct`: How much edge-gated beat always-on (total return)
- `comparison.excess_vs_spy_delta_pct`: How much edge-gated beat always-on (excess vs SPY)
- Gate stats: `writes_allowed`, `writes_blocked_vrp`, block rate

**Success criteria**: Edge-gated beats always-on by **≥2% annually** excess vs SPY

**If edge NOT detected**: Project will be terminated or pivoted per EDGE_VRP_ROADMAP.md

---

### Option 2: Generate Synthetic IV (Research-Only)

**For testing infrastructure only** (do NOT claim edge):
```bash
scripts/build_iv_fixture_from_synthetic.py \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --tickers AAPL MSFT GOOGL SPY \
  --premium-bump 0.15 \
  --out data/synthetic_iv_2020_2024.csv
```

Then run bake-off with `--iv-csv data/synthetic_iv_2020_2024.csv`

⚠️ **Warning**: Synthetic IV uses realized vol + premium bump. NOT market IV. Results are labeled `research_only_synthetic_iv` and must NOT be used for edge validation or beat-SPY claims.

---

### Option 3: Polygon.io API (Future)

**Requirements**:
1. Subscribe to [Polygon.io](https://polygon.io) (Starter $399/mo or Advanced $999/mo)
2. Set environment variable:
   ```bash
   export POLYGON_API_KEY="your_api_key_here"
   ```
3. Complete `src/backtesting/wheel_hybrid/iv_provider.py` → `PolygonIVProvider._fetch_from_api()`:
   - GET `https://api.polygon.io/v3/snapshot/options/{symbol}`
   - Parse option chain for ATM strike
   - Extract `implied_volatility` field
   - Calculate IV rank from historical data
4. Run bake-off (provider auto-fetches + caches to `data/iv_cache/`)

**Cache layout**:
```
data/iv_cache/
  AAPL/
    2020-01-02.json
    2020-01-03.json
  MSFT/
    2020-01-02.json
```

Cache is gitignored and persists for offline replay.

---

## Understanding Bake-Off Results

### Comparison Table

```
Metric                          Legacy (Off)         Gated (On)          Delta
----------------------------------------------------------------------------------
Absolute Return                 +125.50%             +138.20%            +12.70%
Excess vs SPY                   +10.30%              +23.00%             +12.70%
Max Drawdown                    -18.50%              -16.20%             +2.30%
Sharpe Ratio                    1.45                 1.62                +0.17
Alpha (annual)                  +2.50%               +5.80%              +3.30%
Premium Collected               $3,250.00            $2,850.00           -$400.00
```

**What to look for**:
- **Excess vs SPY Delta**: Edge-gated should beat legacy by ≥2% (main success metric)
- **Gate block rate**: 20-40% typical (edge blocks writes when VRP too low)
- **Premium collected**: May be LOWER for gated (fewer writes = better selectivity)
- **Sharpe/Sortino**: Risk-adjusted return should improve

### Gate Statistics

```
Gate Statistics:
  Writes allowed:       450
  Blocked (low VRP):    180
  Blocked (low IV rank): 20
  Blocked (no IV):       5
  Block rate:           31.3%
```

**Interpretation**:
- Block rate 20-40%: Healthy selectivity (edge working)
- Block rate >60%: May be too conservative (threshold too high)
- Block rate <10%: Weak filter (threshold too low or IV always rich)

---

## Next Steps After Bake-Off

### If Edge Detected (≥2% beat)
1. **Document results**: Save bake-off JSON + table
2. **Walk-forward test**: Train on 2015-2019, test on 2020-2024 (out-of-sample)
3. **New paper track**: Launch `vrp-wheel-v1` (Alpaca paper, $10k NAV)
4. **Run 6-12 months**: Compare to SPY + legacy `wheel-10k-paper-v1`
5. **If paper track succeeds**: Move to Phase 4 (production risk/ops)

### If NO Edge Detected (<2% beat)
1. **Kill criteria met**: Terminate project or pivot per roadmap
2. **Pivot options**:
   - Pure equity quant (drop options entirely)
   - Tail hedging only (buy OTM puts, no overwriting)
   - Delta-one replication (synthetic forwards)

---

## Key Files

| File | Purpose |
|------|---------|
| `src/backtesting/wheel_hybrid/iv_provider.py` | CsvIVProvider, PolygonIVProvider |
| `scripts/run_vrp_bakeoff.py` | Bake-off harness (edge on vs off) |
| `scripts/build_iv_fixture_from_synthetic.py` | Generate synthetic IV (testing only) |
| `tests/test_iv_providers.py` | Unit tests + smoke test |
| `docs/EDGE_VRP_ROADMAP.md` | Full Phase 2 roadmap + kill criteria |
| `docs/WHITEPAPER_WHEEL_HYBRID.md` | Strategy thesis + Phase 2 status |

---

## FAQ

**Q: What IV tenor should I use?**  
A: 21-day (3 weeks) is standard. Matches typical CC/CSP DTE range.

**Q: What if some symbols are missing IV data?**  
A: CsvIVProvider returns `None` → EdgeGate blocks writes (fail-closed). Symbol skipped that day.

**Q: Can I use different VRP thresholds?**  
A: Yes! Try `--min-vrp 0.05` (5%), `--min-vrp 0.15` (15%), `--min-vrp 0.20` (20%) and compare.

**Q: What about IV rank filter?**  
A: Optional. Add `--min-iv-rank 0.40` to require IV above 40th percentile.

**Q: Should I enable regime detection?**  
A: Optional Phase 2 feature. Add `--enable-regime` to test HARVEST_VRP / HOLD_DELTA / DEFENSIVE states.

**Q: How do I compare to SPY total return?**  
A: Bake-off automatically uses `^SPXTR` (SPY total return index) or falls back to SPY price-only if unavailable. Benchmark is logged in results.

---

## Support

For questions or issues:
- Open GitHub issue on [Adi1yer/Aletheia-Capital](https://github.com/Adi1yer/Aletheia-Capital)
- Review [EDGE_VRP_ROADMAP.md](EDGE_VRP_ROADMAP.md) for full methodology
- Check [WHITEPAPER_WHEEL_HYBRID.md](WHITEPAPER_WHEEL_HYBRID.md) for strategy thesis
