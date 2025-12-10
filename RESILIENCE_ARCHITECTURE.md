# Resilience Architecture

**Purpose:** Document the error handling, retry patterns, and graceful degradation philosophy used in the Morning Report pipeline.

**Last Updated:** 2025-12-08

---

## 1. Philosophy: Never Crash, Always Degrade Gracefully

The core principle is simple: **a failure in one source should never kill the entire pipeline.**

When scraping financial data from multiple sources (Yahoo Finance, Google News, Vital Knowledge, MarketWatch), failures are inevitable:
- Websites change their DOM structure
- Rate limits get triggered
- Network timeouts occur
- CAPTCHAs appear unexpectedly
- Server-side errors happen

Rather than crashing on the first error, we:
1. **Retry transient failures** with exponential backoff
2. **Isolate failures** so one broken source doesn't affect others
3. **Log everything** for post-mortem debugging
4. **Return partial results** when possible

---

## 2. Retry Helpers (`src/core/retry_helpers.py`)

We created a centralized retry module to standardize how all skills handle transient failures.

### 2.1 Core Retry Function

```python
async def _retry_async(
    func: Callable[..., Any],
    *args,
    max_retries: int = 2,
    base_delay: float = 1.0,
    retry_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    **kwargs,
) -> Any:
```

**How it works:**
- Attempt 0: Execute immediately (no delay)
- Attempt 1: Wait `base_delay` seconds (1s), then retry
- Attempt 2: Wait `base_delay * 2` seconds (2s), then retry
- After `max_retries`: Re-raise the exception

**Why exponential backoff?**
- Gives the server time to recover
- Avoids hammering a struggling endpoint
- Often resolves transient issues automatically

### 2.2 Navigation Retry

```python
async def navigate_with_retry(
    page,
    url: str,
    max_retries: int = 2,
    timeout: int = 30000,
    wait_until: str = "load",
) -> None:
```

**Use case:** Every `page.goto()` call in the codebase.

**Why retry navigation?**
- Network blips cause timeouts
- Page might not fully load on first try
- CDN/proxy issues are often transient

**Applied to all 6 skills:**
- `src/skills/yahoo/quote.py`
- `src/skills/yahoo/research.py`
- `src/skills/googlenews/research.py`
- `src/skills/vital_knowledge/research.py`
- `src/skills/vital_knowledge/macro_news.py`
- `src/skills/marketwatch/research.py`

### 2.3 Extraction Retry

```python
async def extract_with_retry(
    page,
    instruction: str,
    schema: Any,
    max_retries: int = 1,
    selector: Optional[str] = None,
) -> Any:
```

**Use case:** Targeted extractions where we've observed flakiness (primarily Vital Knowledge).

**Why only 1 retry for extractions?**
- Extractions use LLM tokens (OpenAI API calls)
- Retrying extraction = 2x token cost
- We only use this where it's worth the cost

**Applied selectively:**
- Vital Knowledge article extraction
- Vital Knowledge macro report extraction

---

## 3. Error Handling Patterns

### 3.1 The Scoped Extract Pattern (YahooQuote)

This pattern optimizes token usage while handling selector invalidation gracefully.

```python
async def _scoped_extract(page, instruction, schema, selector):
    if selector:
        try:
            # Try with cached selector (fewer tokens)
            return await page.extract(
                instruction=instruction,
                schema=schema,
                selector=selector,
            )
        except Exception:
            # Selector became invalid - clear cache
            selector_cache.delete(CACHE_KEY)

    # Fallback: full-page extract (more tokens, but works)
    return await page.extract(
        instruction=instruction,
        schema=schema,
    )
```

**Flow:**
1. Check if we have a cached XPath selector
2. Try extraction with that selector (uses ~20% fewer tokens)
3. If it fails, clear the cache and fall back to full-page extraction
4. Next run will re-discover the selector

**Why this pattern?**
- Yahoo Finance occasionally changes their DOM structure
- Cached selectors become stale
- Full-page extraction always works (just costs more tokens)
- Self-healing: bad cache gets cleared automatically

### 3.2 Per-Source Isolation

Each source runs in its own try/except block:

```python
# In run_morning_snapshot.py
async def _run_source_with_session(source_name, ticker, fetch_func, ...):
    try:
        stagehand, page = await create_stagehand_session()
        result = await fetch_func(page, ticker)
        return result
    except Exception as e:
        # Log the error, but don't crash
        await _log_error(source_name, ticker, e)
        return None  # Graceful degradation
    finally:
        await stagehand.close()
```

**What this means:**
- If YahooQuote fails for MSFT, YahooAI for MSFT still runs
- If GoogleNews fails entirely, VitalKnowledge still runs
- The pipeline completes with partial results

### 3.3 Batch Processing with Partial Failure

For VitalKnowledge, we process multiple reports in a single session:

```python
for report in reports:
    try:
        await click_report(report)
        for ticker in tickers:
            try:
                bullets = await extract_ticker_info(ticker)
                results[ticker].append(bullets)
            except Exception as e:
                print(f"[ERROR] Failed to extract {ticker}: {e}")
                # Continue to next ticker
    except Exception as e:
        print(f"[ERROR] Failed to process report: {e}")
        # Continue to next report
```

**Nested try/except ensures:**
- One bad report doesn't kill the batch
- One bad ticker extraction doesn't kill the report
- We get as much data as possible

---

## 4. Error Logging and Debugging

### 4.1 Error File Structure

Every error is logged to `data/errors/` with rich context:

```json
{
  "timestamp": "2025-12-08T21:37:59.112090",
  "component": "YahooQuote (src.skills.yahoo.quote)",
  "error_type": "RuntimeError",
  "error_message": "Server returned error: An unexpected error occurred",
  "context": {
    "ticker": "MSFT",
    "source": "YahooQuote",
    "function": "fetch_yahoo_quote"
  },
  "diagnostics": {
    "session_creation_duration_ms": 4167.91,
    "session_created": true,
    "page_object_valid": true,
    "page_accessible": true,
    "initial_url": "about:blank"
  },
  "traceback": "File \"quote.py\", line 101..."
}
```

### 4.2 How to Debug a Failure

**Step 1: Find the error file**
```bash
ls -la data/errors/ | grep "2025-12-08"
```

**Step 2: Read the error JSON**
Look for:
- `error_type`: What kind of failure?
- `error_message`: What went wrong?
- `context.ticker`: Which ticker failed?
- `traceback`: Which line of code?

**Step 3: Follow the traceback**
```
line 101, in fetch_yahoo_quote → snapshot = await _scoped_extract(
line 52, in _scoped_extract → return await page.extract(
```
Open the file, go to those lines, understand the flow.

**Step 4: Check diagnostics**
- `session_created: true` = Browserbase session worked
- `page_accessible: true` = Page object is valid
- If these are false, it's a session/infrastructure issue

**Step 5: Identify the source**
- Error in `stagehand/api.py` = Server-side Stagehand issue
- Error in your code = Logic bug
- `TimeoutError` = Network/page load issue
- `ValidationError` = Schema mismatch

---

## 5. Graceful Degradation in Practice

### 5.1 What Happens When Each Source Fails

| Source | On Failure | User Impact |
|--------|------------|-------------|
| YahooQuote | Return `None` | Missing price data for that ticker |
| YahooAI | Return `None` | No AI analysis for that ticker |
| GoogleNews | Return empty stories | No news articles for that ticker |
| VitalKnowledge | Return partial results | Some tickers may have fewer headlines |
| MacroNews | Return empty reports | No macro analysis (independent of tickers) |
| MarketWatch | Already disabled | N/A (blocked by DataDome) |

### 5.2 Pipeline Always Completes

Even with failures, the pipeline:
1. Writes whatever data it collected to `data/snapshots/`
2. Writes metrics to `data/metrics/`
3. Logs all errors to `data/errors/`
4. Exits with code 0 (success from orchestration perspective)

This means scheduled runs (cron jobs) don't need special failure handling.

---

## 6. Customer Impact and Efficiency

### 6.1 What We Optimized

| Optimization | Token Savings | Reliability Impact |
|--------------|---------------|-------------------|
| Observe→Cache→Extract | -22% on YahooQuote | Slightly more complex fallback path |
| navigate_with_retry | None (navigation doesn't use tokens) | Handles network blips automatically |
| extract_with_retry | Costs 2x on retry, but rare | Recovers from transient Stagehand errors |
| Per-source isolation | None | One failure doesn't kill pipeline |
| Cached selectors | -20-25% per extraction | Self-healing when cache becomes stale |

### 6.2 Before vs After

**Before (no retries, no isolation):**
- One network blip = entire pipeline crashes
- One bad selector = extraction fails, no recovery
- One Stagehand error = manual restart needed

**After:**
- Transient failures auto-recover (1-2s delay, then success)
- Bad selectors get cleared, fallback works
- Pipeline completes with partial results
- Full visibility into what failed and why

### 6.3 Reliability Numbers (Phase 1 Test)

```
Sessions: 14
Success: 14 (100%)
Errors: 0
Wall Clock: 820 seconds
```

Even with `charmap` codec errors in the logs, the retry logic handled them and extractions succeeded.

---

## 7. Key Files Reference

| File | Purpose |
|------|---------|
| `src/core/retry_helpers.py` | Centralized retry functions |
| `src/core/stagehand_runner.py` | Session config (region, keepAlive, timeout) |
| `src/skills/yahoo/quote.py` | Scoped extract pattern example |
| `src/core/cli/run_morning_snapshot.py` | Pipeline orchestration, per-source isolation |
| `data/errors/*.json` | Structured error logs for debugging |
| `data/metrics/*.json` | Per-run metrics including success/failure counts |

---

## 8. Guardrails for Failure Point Identification

When errors occur, we need to know exactly which stage failed. Guardrails are diagnostic checkpoints at each critical stage.

### 8.1 The Guardrail Stages

```
┌─────────────────────────────────────────────────────────────┐
│ Stage 1: Session Creation                                    │
│ ✅ Check: Did Browserbase session create?                    │
│ 📊 Capture: Session creation time, page object validity      │
│ 🚨 Failure Point: "session_creation"                        │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 2: Navigation                                          │
│ ✅ Check: Did page.goto() succeed?                          │
│ 📊 Capture: Target URL, actual URL, navigation time         │
│ 🚨 Failure Point: "navigation"                              │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 3: Page State Check                                    │
│ ✅ Check: Is page accessible? Can we read page properties?   │
│ 📊 Capture: Current URL, page title, ready state            │
│ 🚨 Failure Point: "page_state"                              │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 4: Extraction                                          │
│ ✅ Check: Did page.extract() start? How long did it take?   │
│ 📊 Capture: Start time, duration, error details             │
│ 🚨 Failure Point: "extraction"                              │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 What Each Failure Point Tells You

| Failure Point | What It Means | Likely Causes |
|--------------|---------------|---------------|
| **session_creation** | Browserbase session failed | API down, quota exceeded, config error |
| **navigation** | Page navigation failed | Website down, network issue, CAPTCHA |
| **page_state** | Page loaded but inaccessible | Browser crashed, dynamic content issue |
| **extraction** | AI extraction failed | OpenAI API issue, model timeout, page changed |

### 8.3 Example Error With Guardrails

**Before (without diagnostics):**
```json
{
  "error": "Server returned error: An unexpected error occurred",
  "ticker": "GOOGL"
}
```

**After (with guardrails):**
```json
{
  "error": "Server returned error: An unexpected error occurred",
  "ticker": "GOOGL",
  "failure_point": "extraction",
  "diagnostics": {
    "session_creation_duration_ms": 1200,
    "navigation_success": true,
    "navigation_duration_ms": 2150,
    "actual_url": "https://finance.yahoo.com/quote/GOOGL",
    "page_title": "GOOGL Stock Price...",
    "page_accessible": true,
    "extraction_duration_ms": 76000,
    "page_state_at_failure": {"page_accessible": false}
  }
}
```

**Analysis:** Navigation worked (2.1s), page loaded correctly, extraction started but failed after 76 seconds. Page became inaccessible during extraction → Stagehand/OpenAI server-side issue.

### 8.4 Current Implementation Status

Guardrails are implemented in:
- `fetch_yahoo_quote()` - Full guardrails with diagnostics
- Error logging - Captures `failure_point` and `diagnostics` fields

---

## 9. Future Improvements

1. **Wrap fallback extract in retry** - Currently if scoped extract fails AND fallback fails, we don't retry the fallback
2. **Circuit breaker pattern** - If a source fails 3x in a row, skip it for the rest of the run
3. **Alerting** - Send notification when error rate exceeds threshold
4. **Screenshot on failure** - Capture page state when extraction fails for visual debugging
5. **Roll out guardrails to all sources** - Currently only Yahoo Quote has full guardrails

---

## 10. Summary

The resilience architecture is built on three pillars:

1. **Retry with backoff** - Transient failures recover automatically
2. **Graceful degradation** - Partial results are better than no results
3. **Rich logging** - When things fail, we know exactly why

This approach means the pipeline runs reliably in production without constant babysitting, while giving operators full visibility into any issues that do occur.
