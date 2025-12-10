# Morning Report Architecture

**Last Updated:** 2025-12-08

---

## Overview

The Morning Report pipeline fetches financial data from multiple sources concurrently, processes it, and generates a consolidated report. This document describes the architecture, concurrent execution model, and key design decisions.

---

## 1. Concurrent Execution Model

### Design: Pragmatic Hybrid Approach

We chose a **concurrent sources** design that balances speed, cost, and complexity:

**Per Ticker:**
- Yahoo Quote, Yahoo AI, Google News, Vital Knowledge run **concurrently**
- Each source gets its own isolated browser session
- Macro News runs once (ticker-independent)

**Session Management:**
- `asyncio.Semaphore` limits concurrent browser sessions (default: 4)
- Each session is isolated - failures don't affect other sources
- Session creation uses Browserbase with configurable region/timeout

### Why This Design?

| Approach | Sessions/Ticker | Time/Ticker | Complexity | Cost |
|----------|----------------|-------------|------------|------|
| Sequential | 3-5 sequential | 9-10 min | Low | Low |
| **Concurrent Sources** | 3-5 concurrent | 2-4 min | Medium | Medium |
| Fully Concurrent | 8+ concurrent | 1 min | High | High |

We chose **Concurrent Sources** because:
- **3-4x faster** than sequential (2-4 min vs 9-10 min)
- **Cost-effective** - manageable session count
- **Reliable** - fewer moving parts than fully concurrent
- **Eliminates timeout risk** - all sources well under 10 min limit

---

## 2. System Components

### 2.1 Core Pipeline (`src/core/cli/run_morning_snapshot.py`)

```
main()
  │
  ├── Load configuration (.env, watchlist.json)
  ├── Initialize metrics tracking
  │
  ├── For each ticker (concurrent processing):
  │   ├── Yahoo Quote session
  │   ├── Yahoo AI session      ← All run concurrently
  │   ├── Google News session
  │   └── Vital Knowledge session
  │
  ├── Macro News session (once, independent)
  │
  ├── Combine results
  ├── Generate report (report_builder.py)
  └── Save outputs (snapshots, metrics, reports)
```

### 2.2 Source Modules (`src/skills/`)

Each source is a self-contained module:

| Source | File | Purpose |
|--------|------|---------|
| Yahoo Quote | `skills/yahoo/quote.py` | Stock price, volume, change |
| Yahoo AI | `skills/yahoo/research.py` | AI analysis summary |
| Google News | `skills/googlenews/research.py` | News articles per ticker |
| Vital Knowledge | `skills/vital_knowledge/research.py` | VK headlines |
| Macro News | `skills/vital_knowledge/macro_news.py` | Market-wide reports |
| MarketWatch | `skills/marketwatch/research.py` | Disabled (blocked by DataDome) |

### 2.3 Supporting Modules

| Module | Purpose |
|--------|---------|
| `core/stagehand_runner.py` | Session creation with region/timeout config |
| `core/retry_helpers.py` | Navigation and extraction retry logic |
| `core/cache.py` | XPath selector caching for token optimization |
| `core/report_builder.py` | Markdown report generation |

---

## 3. Session Configuration

### Browserbase Session Parameters

```python
# src/core/stagehand_runner.py
browserbase_session_create_params={
    "region": get_browserbase_region(),      # us-west-2
    "keepAlive": get_browserbase_keep_alive(), # true
    "timeout": get_browserbase_timeout(),    # 900 seconds
}
```

### Environment Variables

```bash
# .env
BROWSERBASE_REGION=us-west-2
BROWSERBASE_KEEP_ALIVE=true
BROWSERBASE_TIMEOUT=900          # seconds (not ms!)
MAX_CONCURRENT_BROWSERS=4
STAGEHAND_VERBOSE=0
```

---

## 4. Data Flow

### 4.1 Pipeline Execution Flow

```
[Startup]
    ↓
Load .env + watchlist.json
    ↓
Initialize semaphore (MAX_CONCURRENT_BROWSERS)
    ↓
[Per Ticker - Concurrent]
    ├─ Session 1: Yahoo Quote → YahooQuoteSnapshot
    ├─ Session 2: Yahoo AI → YahooAIAnalysis
    ├─ Session 3: Google News → GoogleNewsTopStories
    └─ Session 4: Vital Knowledge → VitalKnowledgeHeadlines
    ↓
[Independent]
    └─ Session N: Macro News → MacroNewsSummary
    ↓
Combine all results
    ↓
Generate markdown report
    ↓
Save to data/snapshots/, data/reports/, data/metrics/
```

### 4.2 Source Isolation Pattern

Each source runs in complete isolation:

```python
async def _run_source_with_session(source_name, ticker, fetch_func, sem, ...):
    async with sem:  # Acquire semaphore slot
        stagehand = None
        try:
            stagehand, page = await create_stagehand_session()
            result = await fetch_func(page, ticker)
            return result
        except Exception as e:
            await _log_error(source_name, ticker, e)
            return None  # Graceful degradation
        finally:
            if stagehand:
                await stagehand.close()
```

**Key Properties:**
- Each source gets its own browser session
- Failures are isolated - one source failing doesn't affect others
- Semaphore prevents resource exhaustion
- Graceful degradation returns partial results

---

## 5. Token Optimization

### 5.1 Observe → Cache → Extract Pattern

Used in Yahoo Quote to reduce token usage by ~22%:

```python
# First call: observe() to find XPath selector
if not selector_cache.get(CACHE_KEY):
    observations = await page.observe(instruction="Find the quote module")
    selector_cache.set(CACHE_KEY, observations[0].selector)

# Subsequent calls: use cached selector
cached_selector = selector_cache.get(CACHE_KEY)
if cached_selector:
    # Scoped extraction (fewer tokens)
    result = await page.extract(instruction=..., selector=cached_selector)
else:
    # Fallback: full page extraction
    result = await page.extract(instruction=...)
```

### 5.2 Results

| Ticker | Baseline Tokens | Phase 1 Tokens | Savings |
|--------|----------------|----------------|---------|
| NVDA | 28,685 | 22,413 | -22% |
| AMZN | 26,378 | 19,545 | -26% |
| MSFT | 36,269 | 29,837 | -18% |
| GOOGL | 27,641 | 21,182 | -23% |

---

## 6. Output Files

| Directory | Content |
|-----------|---------|
| `data/snapshots/` | Raw JSON data per source |
| `data/reports/` | Generated markdown reports |
| `data/metrics/` | Per-run metrics with token counts |
| `data/errors/` | Structured error logs for debugging |

---

## 7. Configuration

### 7.1 Source Toggles

```bash
# .env
ENABLE_YAHOO_QUOTE=true
ENABLE_YAHOO_ANALYSIS=true
ENABLE_GOOGLE_NEWS=true
ENABLE_VITAL_NEWS=true
ENABLE_MACRO_NEWS=true
ENABLE_MARKETWATCH=false  # Blocked by DataDome
```

### 7.2 Watchlist

```json
// config/watchlist.json
["AMZN", "NVDA", "MSFT", "GOOGL"]
```

---

## 8. Key Files Reference

| File | Purpose |
|------|---------|
| `src/core/cli/run_morning_snapshot.py` | Main pipeline orchestration |
| `src/core/stagehand_runner.py` | Session creation + config |
| `src/core/retry_helpers.py` | Retry logic for navigation/extraction |
| `src/core/report_builder.py` | Markdown report generation |
| `src/skills/*/` | Individual source modules |
| `.env` | Configuration (API keys, toggles) |
| `config/watchlist.json` | Tickers to process |

---

## 9. Performance Benchmarks

### Phase 1 Test Results (2025-12-08)

| Metric | Value |
|--------|-------|
| Total Sessions | 14 |
| Success Rate | 100% (14/14) |
| Wall Clock Duration | 820 seconds |
| Total Prompt Tokens | 1,084,984 |
| Total Completion Tokens | 10,344 |

### Comparison to Baseline

- **Wall clock time**: ~4x faster than sequential
- **Token savings**: 20-26% on Yahoo Quote (observe→cache→extract)
- **Reliability**: 100% success rate with retry logic

---

## 10. Future Improvements

1. **Intelligent model switching** - Use cheaper models for simple extractions
2. **Batch optimization** - Reduce per-session overhead
3. **Circuit breaker pattern** - Skip sources that fail repeatedly
4. **Screenshot on failure** - Visual debugging for extraction failures

