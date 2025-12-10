# Recent Updates - Morning Report Optimization

**Last Updated:** 2025-12-08

---

## Phase 1 Complete ✅

All Phase 1 items have been implemented and tested successfully.

### Phase 1 Test Results (2025-12-08)

| Metric | Value |
|--------|-------|
| Sessions | 14 |
| Success Rate | 100% (14/14) |
| Wall Clock Duration | 820 seconds |
| Total Prompt Tokens | 1,084,984 |
| Total Completion Tokens | 10,344 |

### Per-Ticker Quality Metrics

| Ticker | GoogleNews | GN Bullets | YahooAI | VK Headlines |
|--------|------------|------------|---------|--------------|
| AMZN   | 5 articles | 4          | 4       | 3            |
| NVDA   | 5 articles | 4          | 6       | 5            |
| MSFT   | 5 articles | 0          | 4       | 5            |
| GOOGL  | 5 articles | 4          | 3       | 5            |

---

## What We Accomplished

### 1. YahooQuote Observe→Cache→Extract Pattern ✅

Implemented a warm-up pattern that reduces YahooQuote tokens by ~22%:

- **File:** `src/skills/yahoo/quote.py`
- **Pattern:** One observe() call caches XPath selector, subsequent tickers skip observe() and go straight to scoped extract()
- **Key insight:** `selector_cache` lives in Python memory, not Browserbase session, so cached selectors work across sessions

**Results (YahooQuote only - fair comparison):**
| Ticker | Baseline | Phase1 | Savings |
|--------|----------|--------|---------|
| NVDA | 28,685 | 22,413 | -22% |
| AMZN | 26,378 | 19,545 | -26% |
| MSFT | 36,269 | 29,837 | -18% |
| GOOGL | 27,641 | 21,182 | -23% |

### 2. verbose=0 via env var ✅

- **File:** `src/core/stagehand_runner.py:22-27`
- **Implementation:** `verbose=get_stagehand_verbose()` helper function
- **Action:** Set `STAGEHAND_VERBOSE=0` in `.env` for quiet mode

### 3. Per-Source Metrics Tracking ✅

- Session IDs tracked per source
- LLM tokens (prompt + completion) tracked per source
- Timing tracked per source

### 4. Region / keepAlive / Timeout ✅ (NEW)

- **File:** `src/core/stagehand_runner.py:8-19, 74-78`
- **Implementation:** Added helper functions and `browserbase_session_create_params`
```python
browserbase_session_create_params={
    "region": get_browserbase_region(),      # us-west-2
    "keepAlive": get_browserbase_keep_alive(), # true
    "timeout": get_browserbase_timeout(),    # 900 seconds
}
```
- **Note:** Browserbase timeout is in SECONDS (not ms). Max allowed: 21600 seconds (6 hours)

### 5. Standardized Retry Helpers ✅ (NEW)

- **File:** `src/core/retry_helpers.py` (NEW module)
- **Functions:**
  - `navigate_with_retry(page, url, max_retries=2, timeout=30000)` - For all navigation
  - `extract_with_retry(page, instruction, schema, max_retries=1)` - For flaky extractions
- **Applied to all 6 skills:**
  - `src/skills/yahoo/quote.py` (removed local helper, uses shared)
  - `src/skills/yahoo/research.py`
  - `src/skills/googlenews/research.py`
  - `src/skills/vital_knowledge/research.py` (nav + extract retries)
  - `src/skills/vital_knowledge/macro_news.py` (nav + extract retries)
  - `src/skills/marketwatch/research.py`

### 6. Per-Article Metrics Tracking ✅ (NEW)

- **File:** `src/core/cli/run_morning_snapshot.py`
- **Implementation:** Article metadata tracked alongside token metrics
- **GoogleNews:** headline, url, source, sentiment, has_summary for each article
- **YahooAI:** bullet_count per ticker
- **VitalKnowledge:** headlines with full text per ticker
- **MacroNews:** report_count, bullet_count, sources
- **Output:** `data/metrics/001_phase1.json`

---

## Phase 1 Status - ALL COMPLETE ✅

| Item | Status | Notes |
|------|--------|-------|
| `verbose=0` | ✅ Done | Set via env var |
| Yahoo fix (observe→cache→extract) | ✅ Done | -22% tokens |
| Basic metadata | ✅ Done | Session IDs tracked |
| Region selection | ✅ Done | Via browserbase_session_create_params |
| keepAlive + timeout | ✅ Done | timeout=900 seconds |
| Standardized retry helpers | ✅ Done | All 6 skills use shared module |
| Per-article metrics | ✅ Done | Full article tracking in metrics |

---

## Key Files

| File | Purpose |
|------|---------|
| `src/core/stagehand_runner.py` | Stagehand/Browserbase config + session params |
| `src/core/retry_helpers.py` | **NEW** - Shared retry helpers for all skills |
| `src/skills/yahoo/quote.py` | YahooQuote with observe→cache→extract |
| `src/core/cache.py` | Selector cache (Python memory) |
| `src/core/cli/run_morning_snapshot.py` | Main pipeline with warm-up + per-article metrics |
| `data/metrics/000_baseline.json` | Baseline metrics |
| `data/metrics/001_phase1.json` | Phase1 metrics (with all improvements) |
| `Customer Improvements.md` | Full roadmap |

---

## Known Issues (Non-Blocking)

1. **charmap codec errors** - Windows-specific encoding issue with Unicode characters in VK reports. Retry logic handles these.
2. **Protocol error (Page.handleJavaScriptDialog)** - Playwright/Browserbase dialog handling issue, non-blocking.
3. **MacroNews report_count=0** - Due to encoding errors, but extractions still succeed for VitalKnowledge.

---

## Metrics Note

**Only compare YahooQuote tokens between runs.** VitalKnowledge and GoogleNews have variable page counts, so total tokens vary unfairly.

---

## Next Steps - Phase 2: Cost & Performance

Phase 1 is complete. Ready to move to Phase 2:

1. **Intelligent model switching** - Use faster/cheaper models for simpler extractions
2. **Smaller extractions** - Reduce extraction scope where possible
3. **Screenshots at critical points** - Debug flaky extractions
4. **Batch token optimization** - Reduce per-session overhead

---

## Commands

```bash
# Run with metrics capture (step 2 = Phase 2 baseline)
.venv311\Scripts\python.exe -m src.core.cli.run_morning_snapshot --step 2 --name phase2

# Quick import tests
.venv311\Scripts\python.exe -c "from src.skills.yahoo.quote import fetch_yahoo_quote; print('yahoo/quote OK')"
.venv311\Scripts\python.exe -c "from src.core.retry_helpers import navigate_with_retry; print('retry_helpers OK')"
```
