# Morning Snapshot

A Stagehand-first Python application that automates pre-market research by aggregating financial data from multiple sources into a single, skimmable Markdown report.

## Quick Start

```bash
# 1. Clone and setup
git clone <repository-url>
cd morning_report
python -m venv .venv311
.venv311\Scripts\activate  # Windows
pip install -e .

# 2. Configure .env (see Configuration section)

# 3. Run
python -m src.core.cli.run_morning_snapshot
```

## Overview

Morning Snapshot pulls quotes, AI analysis, and headlines from multiple financial sources for a watchlist of tickers, then generates a consolidated report with:

- **Market Overview**: Brief macro market summary from Vital Knowledge
- **Per-Ticker Statistics**: Price, volume, day range, extended hours data
- **Sentiment Analysis**: Bullish/bearish assessment with brief explanation
- **Key Points**: Concise bullet points combining news from all sources

## Features

- **Multi-Source Aggregation**: Yahoo Finance, Google News, Vital Knowledge
- **Concurrent Processing**: Multiple browser sessions run in parallel (4x faster)
- **Graceful Degradation**: Continues processing even when individual sources fail
- **Retry Logic**: Automatic retries with exponential backoff for transient failures
- **Session Isolation**: Each source runs in its own browser session
- **Token Optimization**: XPath selector caching reduces LLM token usage by ~22%
- **Comprehensive Metrics**: Per-run JSON and human-readable TXT summaries
- **Error Tracking**: Structured JSON error logs with auto-cleanup

## Requirements

- Python 3.11+
- Browserbase account with API key
- OpenAI API key (for Stagehand)
- Vital Knowledge account credentials

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# Required
BROWSERBASE_API_KEY=your_browserbase_api_key
BROWSERBASE_PROJECT_ID=your_project_id
OPENAI_API_KEY=your_openai_api_key
Vital_login=your_vital_username
Vital_password=your_vital_password

# Optional - Session Configuration
BROWSERBASE_REGION=us-west-2
BROWSERBASE_KEEP_ALIVE=true
BROWSERBASE_TIMEOUT=900000
MAX_CONCURRENT_BROWSERS=4

# Optional - Feature Flags (default: true)
ENABLE_YAHOO_QUOTE=true
ENABLE_YAHOO_ANALYSIS=true
ENABLE_GOOGLE_NEWS=true
ENABLE_VITAL_NEWS=true
ENABLE_MACRO_NEWS=true
ENABLE_MARKETWATCH=false  # Blocked by DataDome

# Optional - Stagehand
STAGEHAND_MODEL_NAME=gpt-4.1-mini
STAGEHAND_VERBOSE=0
```

### Watchlist

Edit `config/watchlist.json`:

```json
["AAPL", "GOOGL", "MSFT", "NVDA"]
```

## Output Files

### Reports
- `data/reports/morning_snapshot_YYYY-MM-DD.md` - Consolidated Markdown report

### Snapshots
- `data/snapshots/yahoo_snapshot_YYYY-MM-DD.json`
- `data/snapshots/googlenews_snapshot_YYYY-MM-DD.json`
- `data/snapshots/vital_knowledge_snapshot_YYYY-MM-DD.json`
- `data/snapshots/macro_news_snapshot_YYYY-MM-DD.json`

### Metrics
- `data/metrics/001_phase1.json` - Detailed metrics (timing, tokens, quality)
- `data/metrics/001_phase1.txt` - Human-readable summary

### Errors
- `data/errors/error_summary_YYYY-MM-DD.txt` - Error summary
- `data/errors/error_summary_YYYY-MM-DD.json` - Structured error data
- `data/errors/errors_YYYY-MM-DD.jsonl` - Daily error log

## Data Sources

| Source | Data | Status |
|--------|------|--------|
| Yahoo Finance Quote | Price, volume, day range, extended hours | Active |
| Yahoo Finance AI | "Why is this stock moving?" analysis | Active |
| Google News | Top 5 news articles with summaries | Active |
| Vital Knowledge | Ticker-specific headlines from reports | Active |
| Macro News | Market-wide macro summaries | Active |
| MarketWatch | Top stories | Disabled (DataDome) |

## Project Structure

```
morning_report/
├── config/
│   └── watchlist.json              # Ticker symbols
├── data/
│   ├── reports/                    # Generated Markdown reports
│   ├── snapshots/                  # Individual JSON snapshots
│   ├── metrics/                    # Per-run metrics (JSON + TXT)
│   └── errors/                     # Structured error logs
├── src/
│   ├── core/
│   │   ├── cli/
│   │   │   └── run_morning_snapshot.py  # Main entry point
│   │   ├── retry_helpers.py             # Retry logic
│   │   ├── report_builder.py            # Report generation
│   │   ├── stagehand_runner.py          # Session management
│   │   ├── cache.py                     # XPath selector caching
│   │   └── observability/
│   │       ├── errors.py                # Error tracking
│   │       └── guardrails.py            # Diagnostic checkpoints
│   └── skills/
│       ├── yahoo/                  # Yahoo Finance (quote + AI)
│       ├── googlenews/             # Google News
│       ├── vital_knowledge/        # Vital Knowledge + Macro
│       └── marketwatch/            # MarketWatch (disabled)
├── README.md                       # This file
├── SUMMARY.md                      # Project summary
├── ARCHITECTURE.md                 # Technical architecture
├── RESILIENCE_ARCHITECTURE.md      # Error handling patterns
├── TESTING.md                      # Testing guide
└── OBSERVABILITY.md                # Metrics and logging
```

## Documentation

| Document | Purpose |
|----------|---------|
| [SUMMARY.md](SUMMARY.md) | High-level project overview |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Concurrent execution model, session management |
| [RESILIENCE_ARCHITECTURE.md](RESILIENCE_ARCHITECTURE.md) | Error handling, retry patterns, graceful degradation |
| [TESTING.md](TESTING.md) | Testing framework and guidelines |
| [OBSERVABILITY.md](OBSERVABILITY.md) | Metrics, logging, debugging |
| [Customer Improvements.md](Customer%20Improvements.md) | Improvement roadmap |

## Testing Individual Sources

```bash
# Test Google News
python -m src.skills.googlenews.research

# Test Vital Knowledge
python -m src.skills.vital_knowledge.research

# Test Macro News
python -m src.skills.vital_knowledge.macro_news
```

## Troubleshooting

### Browser Session Timeouts
- Reduce `max_stories` in Google News (default: 5)
- Increase `BROWSERBASE_TIMEOUT` in .env

### Missing Data
- Check `.env` configuration
- Verify Vital Knowledge credentials
- Review `data/errors/` for failure details

### CAPTCHA Issues
- MarketWatch requires advanced stealth mode (Scale Plan)
- Keep `ENABLE_MARKETWATCH=false` unless configured

## Performance

Typical run (4 tickers):
- **Duration**: ~10 minutes
- **Sessions**: 14
- **LLM Tokens**: ~1.2M total
- **Success Rate**: 100%

## License

[Add your license here]

---

*Built with [Stagehand](https://github.com/browserbase/stagehand-python), [Browserbase](https://browserbase.com), and Python.*
