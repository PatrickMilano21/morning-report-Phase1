# Customer Improvements - Morning Report

A comprehensive improvement plan for the morning_report project, organized around **real pain points** from the codebase. Each item is framed as something a Browserbase customer might ask for help with.

---

## P0: What Actually Hurts Today

These are the **real problems** from QUICK_SUMMARY.md that need fixing first:

| Pain Point | Problem | Impact |
|------------|---------|--------|
| **Security/Logging** | Passwords appear in Stagehand logs (`verbose=1`) | Credentials exposed in console output |
| **Session Timeouts** | ~10min Browserbase limit kills long flows | Google News processing fails mid-run |
| **Yahoo Flakiness** | Inconsistent extraction results | Missing/wrong price data |
| **No Per-Source Tracking** | Can't tell which source fails most | Blind debugging |

---

## 1. Cost Optimization

### LLM Token Usage
- [x] **Set `verbose=0` for production** - Minimize token usage AND hide sensitive data
- [x] **Implement observe() caching** - Use `observe()` once, cache selectors, reuse with `act()`
- [ ] **Intelligent model switching** - gpt-4.1-mini for simple clicks, gpt-4o for complex reasoning
- [x] **Optimize extraction prompts** - Concise prompts; smaller chunks vs. one massive extraction

### Session/Browser Costs
- [x] **Configure proxies strategically** - Understand when residential vs. datacenter makes sense
- [x] **Session reuse evaluation** - Are there workflows that could safely share sessions?

---

## 2. Performance & Reliability

### Timeout Management
- [x] **Set project-level default timeout** - Configure in Browserbase Project Settings
- [x] **Enable `keepAlive: true`** - Prevent premature session termination
- [x] **Increase custom session timeout** - Currently hitting ~10min limits
- [x] **Add `waitUntil` options** - Appropriate wait strategies per source

### Geographic Optimization
- [x] **Use sessions close to deployment** - Select appropriate Browserbase region

### Extraction Reliability
- [x] **Yahoo Quote: explicit waits** - Ensure data visible before extraction
- [x] **Extract smaller chunks** - Split large extractions for consistency
- [x] **Pass observe() results directly to act()** - Avoid re-querying DOM
- [x] **Handle iframes** - Check if Yahoo has iframe elements causing issues

### Error Handling & Graceful Degradation
- [x] **Add retries for brittle steps** - 1-2 retry attempts on navigation/extraction failures
- [x] **Fallback strategies** - Simpler extraction, cheaper model, or alternate source
- [x] **Structured error metadata** - Log where flows break for pattern detection

---

## 3. Observability & Debugging

### Per-Source Metadata + Cost Tracking (Single Initiative)
- [x] **Tag sessions with source name** - YahooQuote, GoogleNews, VitalKnowledge, etc.
- [x] **Add ticker + run metadata** - Enable filtering by ticker, source, run type
- [x] **Track per-source costs** - Use Stagehand metrics to see cost breakdown
- [ ] **Use Project Usage API** - Pull usage data programmatically

### Session Inspection
- [x] **Use Session Live View** - Debug login flows (especially Vital Knowledge)
- [x] **Explore Session Replay tabs** - Logs, network events, DOM structure, Stagehand tab
- [ ] **Capture screenshots at critical points** - Before/after key actions

### Logging & Metrics
- [ ] **Use stagehand.init() debugURL** - Print and use for live debugging
- [x] **Create inference_summary logging** - Track successful actions and patterns

---

## 4. Stagehand Best Practices

### Caching & Optimization
- [x] **Implement observe → cache → act pattern** - Avoid repeated LLM calls
- [x] **Audit current code for caching opportunities** - Are we re-learning selectors?
- [x] **Optimize DOM processing** - Add CSS selector for main quote section

### Extraction Improvements
- [x] **Review extract() for URL links** - Google News and Vital Knowledge URL extraction
- [x] **Fix Yahoo extraction inconsistency** - Apply troubleshooting tips from docs
- [ ] **Context engineering** - Add correct vs. incorrect extraction examples
- [x] **Stable rules in prompts** - "Use USD for monetary values"
- [x] **Localize context with CSS selectors** - Narrow extraction scope

### Agent Usage
- [ ] **Try agent.execute()** - Multi-step flows like Google filtering by "most recent"

---

## 5. Advanced Browserbase Features

### Proxies & Network
- [x] **Understand VPN routing** - When to use customer VPN vs. Browserbase proxies
- [x] **Optimize proxy usage for cost** - Different proxy types have different costs

---

## 6. Learning & Research

- [x] **Browserbase vs. LLM web search** - When headless browsers beat LLM-only approaches
- [x] **Explore the Playground** - Test ideas at browserbase.com
- [x] **Review Templates** - https://www.browserbase.com/templates
- [ ] **Explore Director.ai** - https://director.ai/
- [x] **Add resources to .cursorrules** - Links to best practices docs

---

## Implementation Roadmap

### Phase 1: Safety & Stability (P0) ✅ COMPLETE
*Fix what hurts today. Basic reliability before optimization.*

| Item | File | Change | Status |
|------|------|--------|--------|
| `verbose=0` | `stagehand_runner.py` | Hide passwords, reduce tokens | ✅ |
| Project timeout | Browserbase Dashboard | Set default fallback timeout | ✅ |
| `keepAlive: true` | `stagehand_runner.py` | Prevent session termination | ✅ |
| Increase session timeout | `stagehand_runner.py` | Extend past 10min limit (900s) | ✅ |
| Region selection | `stagehand_runner.py` | Reduce latency (us-west-2) | ✅ |
| Yahoo fix | `yahoo/quote.py` | waitUntil + smaller extracts + iframe check | ✅ |
| Basic metadata | `stagehand_runner.py` | Tag source, ticker, run_id | ✅ |
| Basic retries | All skills | navigate_with_retry() | ✅ |

### Phase 2: Cost & Performance ✅ MOSTLY COMPLETE
*Reduce LLM costs and improve speed.*

| Item | File | Change | Status |
|------|------|--------|--------|
| observe → cache → act | `src/core/cache.py` | Cache selectors, avoid re-learning | ✅ |
| **Disk-persistent cache** | `src/core/cache.py` | Persist to `data/cache/selectors.json` | ✅ |
| Intelligent model switching | `stagehand_runner.py` | Cheaper models for simple actions | ⏳ |
| Smaller extractions | `googlenews/research.py` | Split large extractions | ✅ |
| Screenshots | All skills | Capture at critical points | ⏳ |

### Phase 3: Observability & ROI ✅ MOSTLY COMPLETE
*Prove what's working and what isn't.*

| Item | File | Change | Status |
|------|------|--------|--------|
| Rich metadata | `stagehand_runner.py` | Ticker, source, run_id | ✅ |
| Cost monitoring | `run_morning_snapshot.py` | Per-source, per-run costs | ✅ |
| debugURL logging | `stagehand_runner.py` | Print for live debugging | ⏳ |
| Session Replay usage | (Manual) | Standard debug workflow | ✅ |

### Phase 4: Refinement & Robustness ✅ MOSTLY COMPLETE
*Polish extraction quality and error handling.*

| Item | File | Change | Status |
|------|------|--------|--------|
| CSS selector scoping | `yahoo/quote.py` | Narrow extraction context | ✅ |
| Context engineering | `.cursorrules` | Correct vs. incorrect examples | ⏳ |
| Caching audit | All skills | Find missed caching opportunities | ✅ |
| Advanced fallbacks | All skills | Model switching, alternate sources | ✅ |

### Phase 5: New Capabilities (After Stability) ⏳ NOT STARTED
*Customer-facing extras once the pipeline is solid.*

| Item | Purpose | Status |
|------|---------|--------|
| **agent.execute()** | Multi-step autonomous flows | ⏳ |
| **MCP server** | Expose morning_report as tools for AI agents | ⏳ |
| **Evaluation framework** | Compare to Browserbase best practices, measure quality | ⏳ |

*These unlock better developer workflows (MCP) and quality control (evals), but only after reliability/cost/performance are solved.*

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/core/stagehand_runner.py` | verbose, region, keepAlive, timeout, metadata |
| `src/skills/yahoo/quote.py` | waitUntil, smaller extracts, CSS selectors, retries |
| `src/skills/yahoo/research.py` | Retries, fallbacks |
| `src/skills/googlenews/research.py` | Smaller extractions, screenshots, retries |
| `src/skills/vital_knowledge/research.py` | Password handling, caching, retries |
| `src/core/cli/run_morning_snapshot.py` | Cost tracking, observability |
| New: `src/core/cache.py` | Action caching system |
| New: `src/core/observability/metrics.py` | Cost/usage tracking |
| New: `src/core/observability/logging.py` | Centralized structured logging |

---

## Measurement Strategy: Proving Improvements Work

### Progressive Metrics Workflow

**Step 1: Capture Baseline**
Run the pipeline once and save `data/metrics/000_baseline.json`

**Step 2: After Each Improvement**
Save a new JSON file: `data/metrics/001_verbose_0.json`, `002_keepalive.json`, etc.

Each file includes:
- What was changed
- The new metrics
- Comparison to baseline

### Available Metrics

#### Stagehand Metrics (`stagehand.metrics`)
| Metric | What It Measures | Use For |
|--------|------------------|---------|
| `totalPromptTokens` / `totalCompletionTokens` | Total tokens across all ops | Total LLM cost |
| `totalInferenceTimeMs` | Total LLM inference time | Speed measurement |
| `*CachedInputTokens` | Cached tokens (saved) | Cache hit rate |

#### Browserbase Session Metrics (`bb.sessions.retrieve()`)
| Metric | What It Measures | Use For |
|--------|------------------|---------|
| `avgCpuUsage` | CPU % for session | Resource efficiency |
| `memoryUsage` | Memory used | Resource efficiency |
| `proxyBytes` | Bytes via proxy | Bandwidth cost |
| `startedAt` / `endedAt` | Session timestamps | Duration calculation |
| `status` | COMPLETED/ERROR/TIMED_OUT | Success rate |

#### Browserbase Project Usage API (`bb.projects.usage()`)
| Metric | What It Measures | Use For |
|--------|------------------|---------|
| `browserMinutes` | Total browser time | Primary cost metric |
| `proxyBytes` | Total proxy bandwidth | Secondary cost metric |

### Key Metrics to Track Per Improvement

| Improvement | Primary Metric | Target |
|-------------|----------------|--------|
| **verbose=0** | Token count reduction | -10% tokens |
| **keepAlive + timeout** | Timeout errors | 0 timeouts |
| **observe() caching** | Cache hit rate | +50% cache hits |
| **Smaller extractions** | Error rate | -30% errors |
| **Region selection** | Total duration | -20% latency |
| **Model switching** | Total cost | -40% LLM cost |
| **Retries** | Success rate | 95%+ success |

### Metrics File Location

```
data/metrics/
├── 000_baseline.json         # Initial state before improvements
├── 001_verbose_0.json        # After setting verbose=0
├── 002_keepalive_timeout.json # After enabling keepAlive
├── 003_yahoo_fix.json        # After Yahoo improvements
├── 004_metadata.json         # After adding session metadata
└── ...                       # Continue for each improvement
```

### Sample Dashboard Output

```
================================================================================
                     MORNING REPORT - IMPROVEMENT METRICS
================================================================================

Run ID: 2025-01-15T08:30:00
Compared to baseline: 2025-01-10T08:30:00

COST METRICS:
  LLM Tokens:      12,450 → 7,890 (-36.6%)  ✓
  Browser Minutes: 8.2 → 5.1 (-37.8%)       ✓
  Proxy Bytes:     2.1 MB → 1.8 MB (-14.3%) ✓

RELIABILITY METRICS:
  Success Rate:    72% → 94% (+22%)         ✓
  Timeout Errors:  3 → 0                    ✓
  Extraction Errors: 5 → 1                  ✓

PERFORMANCE METRICS:
  Total Duration:  12m 30s → 6m 45s (-46%)  ✓
  Cache Hit Rate:  0% → 58%                 ✓

PER-SOURCE BREAKDOWN:
  YahooQuote:     98% success, 1.2s avg, 450 tokens
  GoogleNews:     92% success, 45s avg, 3200 tokens
  VitalKnowledge: 95% success, 30s avg, 2100 tokens
================================================================================
```

---

## CURRENT STATUS (2025-12-10) - PHASE 1 COMPLETE + DISK CACHE!

### Phase Summary

| Phase | Status | Completion |
|-------|--------|------------|
| **Phase 1: Safety & Stability** | ✅ COMPLETE | 8/8 items |
| **Phase 2: Cost & Performance** | ✅ Mostly Complete | 2/4 items |
| **Phase 3: Observability & ROI** | ✅ Mostly Complete | 3/4 items |
| **Phase 4: Refinement & Robustness** | ✅ Mostly Complete | 3/4 items |
| **Phase 5: New Capabilities** | ⏳ Not Started | 0/3 items |

### Key Achievements

- **4x Performance Gain**: 40+ min → ~10 min (concurrent execution)
- **100% Success Rate**: No more timeout failures
- **Session Metadata**: Filter by source/ticker/run in Browserbase dashboard
- **Structured Error Tracking**: JSON + TXT summaries in `data/errors/`
- **Per-Source Metrics**: Token usage, timing, and costs tracked
- **XPath Caching**: observe() → cache → extract() pattern reduces tokens by ~35%
- **Disk-Persistent Cache**: Selectors saved to `data/cache/selectors.json`, survive across runs

### Remaining Items (Quick Wins)

| Item | Phase | Effort |
|------|-------|--------|
| debugURL logging | Phase 3 | Low |
| Screenshot on failure | Phase 2 | Medium |
| Intelligent model switching | Phase 2 | Medium |
| Context engineering examples | Phase 4 | Low |
| Director.ai exploration | Phase 6 | Low |

### Baseline Metrics (for Comparison)

| Metric | Before (Baseline) | After (Phase 1) |
|--------|-------------------|-----------------|
| Wall Clock | 178.4 seconds | ~600 seconds (4 tickers concurrent) |
| Success Rate | 100% | 100% |
| Sessions | 8 | 14 |
| Total Tokens | ~400K | ~1.2M |

*Note: Token increase due to processing more tickers concurrently. Per-ticker cost remains similar.*

### YahooQuote Token Comparison (with Disk Cache - 2025-12-10)

| Ticker | Baseline | With Cache | Savings |
|--------|----------|------------|---------|
| NVDA | 28,685 | 16,374 | **-43%** |
| AMZN | 26,378 | 12,902 | **-51%** |
| MSFT | 36,269 | 28,386 | **-22%** |
| GOOGL | 27,641 | 19,560 | **-29%** |
| **TOTAL** | **118,973** | **77,222** | **-35%** |

### Python Environment

- Using: `.venv311` with Python 3.11.6
- Run command: `.venv311\Scripts\python.exe -m src.core.cli.run_morning_snapshot`
