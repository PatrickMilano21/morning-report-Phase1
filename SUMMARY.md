# Morning Snapshot - Project Summary

**Last Updated:** 2025-12-08

---

## What It Does

Morning Snapshot automates pre-market research by scraping financial data from multiple sources and generating a single, skimmable Markdown report. Instead of manually checking Yahoo Finance, Google News, and financial newsletters every morning, the pipeline does it automatically.

### Input
- A list of stock tickers (e.g., AAPL, MSFT, NVDA, GOOGL)

### Output
- **Morning Report**: A Markdown file with market overview, stock stats, sentiment, and key news bullets
- **JSON Snapshots**: Raw data from each source for further analysis
- **Metrics**: Performance data (timing, token usage, success rates)

---

## Data Sources

| Source | What It Extracts | How It Works |
|--------|-----------------|--------------|
| **Yahoo Finance Quote** | Price, volume, change, day range, extended hours | Navigate to quote page, extract structured data |
| **Yahoo Finance AI** | "Why is this stock moving?" analysis with bullets | Click AI analysis panel, extract summary + bullets |
| **Google News** | Top 5 news articles with summaries and sentiment | Search for ticker news, visit each article, generate summaries |
| **Vital Knowledge** | Ticker-specific headlines from professional reports | Login, navigate to reports, extract mentions of each ticker |
| **Macro News** | Market-wide macro summaries | Same as Vital Knowledge, but extracts overall market themes |

---

## How It Works

### Execution Flow

```
1. Load watchlist (config/watchlist.json)
          │
2. For each ticker, launch concurrent browser sessions:
          │
          ├── Yahoo Quote Session ────────┐
          ├── Yahoo AI Session ───────────┤
          ├── Google News Session ────────┼── All run in parallel
          └── (Vital Knowledge batched) ──┘
          │
3. Macro News Session (runs once, independent of tickers)
          │
4. Combine all results
          │
5. Generate Markdown report
          │
6. Save outputs: report, snapshots, metrics, errors
```

### Concurrency Model

- **4 concurrent browser sessions** (configurable via `MAX_CONCURRENT_BROWSERS`)
- Each source runs in **isolated browser session** - failures don't cascade
- **Semaphore-controlled** - prevents overloading Browserbase
- **~4x faster** than sequential execution (10 min vs 40+ min)

### Session Configuration

Sessions are created via Browserbase with:
- **Region**: `us-west-2` (closest to data sources)
- **Keep Alive**: `true` (prevents premature termination)
- **Timeout**: 15 minutes (900,000ms)

---

## Key Technical Decisions

### 1. Stagehand-First Approach
Uses Stagehand's AI-powered selectors (`page.extract()`, `page.act()`, `page.observe()`) instead of brittle CSS/XPath selectors. This makes the scraper resilient to minor DOM changes.

### 2. Token Optimization
- **XPath Caching**: First run uses `observe()` to find the quote section, caches the XPath, subsequent runs use the cached selector
- **Scoped Extraction**: Pass cached selector to `extract()` to reduce tokens by ~22%
- **Self-Healing**: If cached selector becomes invalid, automatically falls back to full-page extraction and clears cache

### 3. Graceful Degradation
- **Never crash on single failure**: If Yahoo Quote fails for MSFT, continue with other tickers
- **Return partial results**: Even if Google News crashes mid-run, return whatever articles were collected
- **Comprehensive error logging**: Every failure is logged with context for debugging

### 4. Retry Logic
- **Navigation retries**: All `page.goto()` calls wrapped with exponential backoff (up to 2 retries)
- **Extraction retries**: Targeted retries for Vital Knowledge (known to be flaky)
- **Automatic recovery**: Transient network issues resolve without manual intervention

---

## Output Files

### Generated Report
`data/reports/morning_snapshot_2025-12-08.md`:
```markdown
# Morning Snapshot — 2025-12-08

## Market Overview
[Brief macro summary from Vital Knowledge]

---

### NVDA
**Statistics:**
- Last Price: $142.50 (+2.34%)
- Volume: 45.2M (Avg: 38.1M)
- Day Range: $139.20 - $143.80

**Bullish** - Strong momentum on China chip news

**Key Points:**
- Trump administration approves H200 chip sales to China
- Analysts raise price targets citing AI demand
- ...
```

### Metrics Summary
`data/metrics/001_phase1.txt`:
```
============================================================
METRICS SUMMARY: PHASE1
============================================================

--- OVERVIEW ---
Wall Clock Duration: 604.6 seconds (10.1 min)
Sessions: 14
Success Rate: 100% (14 success, 0 errors)

--- LLM TOKENS ---
Prompt Tokens: 1,185,196
Completion Tokens: 12,340
Total Tokens: 1,197,536

--- QUALITY PER TICKER ---
  NVDA:
    GoogleNews Articles: 5
    Yahoo AI Bullets: 7
    VitalKnowledge Headlines: 5
  ...
```

### Error Summary
`data/errors/error_summary_2025-12-08.txt`:
```
============================================================
ERROR SUMMARY
============================================================

Total Errors: 7
Status: errors_occurred

Errors by Component:
  - MacroNews: 7 error(s)

Recent Errors:
  Component: MacroNews
  Error: UnicodeEncodeError: 'charmap' codec can't encode...
  Context: report_title=Vital Market Recap...
```

---

## Performance Characteristics

| Metric | Typical Value |
|--------|---------------|
| **Total Duration** | ~10 minutes (4 tickers) |
| **Sessions Created** | 14 |
| **Success Rate** | 100% |
| **LLM Tokens** | ~1.2M total |
| **Token Cost** | ~$0.60-1.20 (gpt-4.1-mini) |

### Per-Source Timing
- **Yahoo Quote**: 2-6 min per ticker
- **Yahoo AI**: 3-9 min per ticker
- **Google News**: 3-8 min per ticker
- **Vital Knowledge**: 5-6 min (batch for all tickers)
- **Macro News**: 2-3 min

---

## Error Handling Philosophy

### Core Principle: Never Crash, Always Degrade

```
If one source fails → Continue with others
If one ticker fails → Continue with remaining tickers
If extraction fails → Return partial data
If retry exhausted → Log error, move on
```

### Error Tracking
- **Auto-cleanup**: Old error files deleted when new run starts
- **Structured logging**: JSON files with error type, component, context, traceback
- **Human-readable summary**: TXT file with error counts and recent failures
- **Daily log**: JSONL file for historical tracking

---

## Files & Directories

```
morning_report/
├── config/
│   └── watchlist.json           # Tickers to track
├── data/
│   ├── reports/                 # Generated Markdown reports
│   ├── snapshots/               # Raw JSON from each source
│   ├── metrics/                 # Performance metrics (JSON + TXT)
│   └── errors/                  # Error logs (JSON + TXT)
├── src/
│   ├── core/
│   │   ├── cli/run_morning_snapshot.py  # Main entry point
│   │   ├── retry_helpers.py             # Retry with backoff
│   │   ├── stagehand_runner.py          # Session creation
│   │   ├── cache.py                     # XPath caching
│   │   ├── report_builder.py            # Markdown generation
│   │   └── observability/
│   │       ├── errors.py                # Error tracking
│   │       └── guardrails.py            # Diagnostics
│   └── skills/
│       ├── yahoo/quote.py               # Yahoo price data
│       ├── yahoo/research.py            # Yahoo AI analysis
│       ├── googlenews/research.py       # Google News
│       ├── vital_knowledge/research.py  # VK ticker headlines
│       └── vital_knowledge/macro_news.py # VK macro reports
└── .env                         # API keys and config
```

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| **Language** | Python 3.11 |
| **Browser Automation** | Stagehand (Python SDK) |
| **Browser Infrastructure** | Browserbase |
| **LLM** | OpenAI GPT-4.1-mini |
| **Data Validation** | Pydantic |
| **Concurrency** | asyncio |

---

## Known Limitations

1. **MarketWatch Disabled**: Blocked by DataDome CAPTCHA (requires Scale Plan)
2. **Charmap Encoding Errors**: Some Vital Knowledge reports contain special characters that cause encoding issues on Windows
3. **Session Duration**: Long-running extractions can approach Browserbase timeout limits
4. **No Real-Time Updates**: Designed for pre-market batch runs, not continuous monitoring

---

## Future Improvements

- [ ] Fix charmap encoding issues (switch to UTF-8 for all I/O)
- [ ] Add lightweight web UI for viewing reports
- [ ] Integrate with real portfolio (dynamic ticker list)
- [ ] Add screenshot capture on extraction failures
- [ ] Implement circuit breaker pattern (skip source after N consecutive failures)

---

## Quick Commands

```bash
# Run full pipeline
python -m src.core.cli.run_morning_snapshot

# Test individual sources
python -m src.skills.googlenews.research
python -m src.skills.vital_knowledge.research
python -m src.skills.vital_knowledge.macro_news

# View latest metrics
type data\metrics\001_phase1.txt

# View latest errors
type data\errors\error_summary_2025-12-08.txt
```
