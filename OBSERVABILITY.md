# Observability Guide

**Last Updated:** 2025-12-08

---

## Overview

Observability for the Morning Report pipeline includes structured logging, metrics collection, and error tracking. This document describes the current implementation and future improvements.

---

## 1. Current State

### What We Have

| Feature | Status | Location |
|---------|--------|----------|
| Per-source metrics | Implemented | `data/metrics/*.json` |
| Per-article tracking | Implemented | Metrics JSON files |
| Error logging | Implemented | `data/errors/*.json` |
| Structured error files | Implemented | JSON with context |
| Console output | Basic print statements | Throughout code |

### Current Metrics Output

```json
// data/metrics/001_phase1.json
{
  "run_name": "phase1",
  "timestamp": "2025-12-08T16:00:00Z",
  "timing": {
    "wall_clock_seconds": 820,
    "per_source": {
      "YahooQuote": {
        "NVDA": {
          "duration_seconds": 45.2,
          "session_id": "abc123",
          "llm_tokens": {"prompt": 22413, "completion": 156}
        }
      }
    }
  }
}
```

---

## 2. Current Error Logging

### Error File Structure

When an error occurs, a JSON file is created in `data/errors/`:

```json
// data/errors/error_2025-12-08_16-37-59_YahooQuote.json
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

### How to Debug

1. **Find error files:**
   ```bash
   dir data\errors\*2025-12-08*
   ```

2. **Read the JSON:**
   - `error_type` - What kind of failure
   - `error_message` - What went wrong
   - `context.ticker` - Which ticker
   - `traceback` - Stack trace

3. **Check diagnostics:**
   - `session_created: true` → Browserbase worked
   - `page_accessible: true` → Page object valid
   - If false → Infrastructure issue

---

## 3. Observability Flow

### Current Implementation

```
Pipeline Execution
    │
    ├── Start: Print "[Starting pipeline...]"
    │
    ├── Per Source:
    │   ├── Print "[TICKER] Source: Starting..."
    │   ├── Track timing (start_time = time.time())
    │   ├── Execute fetch function
    │   ├── Print "[TICKER] Source: OK" or "[ERROR] ..."
    │   └── Record metrics (duration, tokens, session_id)
    │
    ├── On Error:
    │   ├── Print error to console
    │   ├── Write structured JSON to data/errors/
    │   └── Continue with other sources (graceful degradation)
    │
    └── Finish:
        ├── Write metrics to data/metrics/
        └── Print summary
```

---

## 4. Per-Article Metrics Tracking

### What's Tracked

**GoogleNews:**
```json
{
  "type": "articles",
  "count": 5,
  "articles": [
    {
      "headline": "NVIDIA Stock Surges...",
      "url": "https://...",
      "source": "Reuters",
      "sentiment": "positive",
      "has_summary": true
    }
  ]
}
```

**YahooAI:**
```json
{
  "type": "analysis",
  "bullet_count": 4
}
```

**VitalKnowledge:**
```json
{
  "type": "headlines",
  "count": 5,
  "headlines": [
    {"headline": "...", "sentiment": "bullish"}
  ]
}
```

**MacroNews:**
```json
{
  "type": "macro_reports",
  "report_count": 3,
  "bullet_count": 12,
  "sources": ["Morning Report", "Market Update"]
}
```

---

## 5. Future Improvements

### 5.1 Structured Logging Module

Replace print statements with structured JSON logging:

```python
# Future: src/core/observability/logger.py
from src.core.observability.logger import get_logger

logger = get_logger("cli")

logger.info(
    "Starting source",
    ticker="AAPL",
    source="YahooQuote",
)

logger.error(
    "Source failed",
    ticker="AAPL",
    source="YahooQuote",
    error=exception,
    duration_seconds=27.3,
)
```

**Output:**
```json
{
  "timestamp": "2025-12-08T11:24:47.123Z",
  "level": "INFO",
  "message": "Starting source",
  "context": {"ticker": "AAPL", "source": "YahooQuote"}
}
```

### 5.2 Metrics Collection Module

Centralized metrics with automatic aggregation:

```python
# Future: src/core/observability/metrics.py
metrics = get_metrics_collector()

run_id = metrics.start_run(ticker_count=4)
ticker_metrics = metrics.start_ticker("AAPL")

metrics.record_source(
    ticker_metrics,
    source_name="YahooQuote",
    success=True,
    duration=27.3,
    data_points=10,
)

metrics.finish_run()  # Writes to data/metrics/
```

### 5.3 Enhanced Error Tracking

```python
# Future: src/core/observability/errors.py
error_tracker.record_error(
    error=exception,
    context={"ticker": "AAPL", "source": "YahooQuote"},
    level="error",
)

# Aggregates errors, provides summary:
summary = error_tracker.get_error_summary()
# {
#   "total_errors": 2,
#   "error_types": {"TimeoutError": 1, "RuntimeError": 1}
# }
```

---

## 6. Directory Structure

### Current

```
data/
├── snapshots/           # Raw JSON data
│   └── yahoo_snapshot_2025-12-08.json
├── reports/             # Generated markdown
│   └── morning_snapshot_2025-12-08.md
├── metrics/             # Run metrics
│   ├── 000_baseline.json
│   └── 001_phase1.json
└── errors/              # Error logs
    └── error_2025-12-08_16-37-59_YahooQuote.json
```

### Future (with observability module)

```
data/
├── logs/                # Structured JSON logs
│   └── morning_report_2025-12-08.log
├── metrics/             # Run metrics
│   ├── latest_metrics.json
│   └── metrics_2025-12-08_11-24-47.json
└── errors/              # Error logs
    ├── errors_2025-12-08.jsonl
    └── error_2025-12-08_...json
```

---

## 7. Metrics Comparison

### Baseline vs Phase 1

To compare metrics between runs:

```python
# Compare YahooQuote tokens (fair comparison)
baseline = json.load(open("data/metrics/000_baseline.json"))
phase1 = json.load(open("data/metrics/001_phase1.json"))

# Note: Only compare YahooQuote tokens
# VitalKnowledge/GoogleNews vary with page content
```

| Metric | Baseline | Phase 1 | Change |
|--------|----------|---------|--------|
| YahooQuote tokens | 119,973 | 92,977 | -22% |
| Wall clock (sec) | 720 | 820 | +14% (more VK reports) |
| Success rate | 100% | 100% | Same |

---

## 8. Key Points

**What's Working:**
- Per-source metrics with session IDs
- Per-article tracking for quality analysis
- Structured error files with diagnostics
- Token usage tracking per source

**What's Missing:**
- Structured logging (still using print)
- Log aggregation
- Real-time monitoring
- Alerting on failures

**Next Steps:**
1. Replace print statements with structured logger
2. Add observability module (`src/core/observability/`)
3. Implement log aggregation
4. Add health monitoring

---

## 9. Commands

```bash
# View recent errors
dir data\errors\*2025-12-08*

# Compare metrics
type data\metrics\001_phase1.json

# Check latest run
type data\metrics\latest_metrics.json

# Run with metrics capture
.venv311\Scripts\python.exe -m src.core.cli.run_morning_snapshot --step 2 --name phase2
```

