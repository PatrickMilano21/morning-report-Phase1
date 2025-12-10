# Testing Guide

**Last Updated:** 2025-12-08

---

## Overview

This document covers testing strategies, test organization, and how to run tests for the Morning Report pipeline.

---

## 1. Testing Philosophy

### Manual Testing (Current Approach)

You can test manually using environment toggles:

```bash
# .env toggles
ENABLE_YAHOO_QUOTE=true
ENABLE_YAHOO_ANALYSIS=false
ENABLE_GOOGLE_NEWS=false
ENABLE_VITAL_NEWS=false

# Minimal watchlist
# config/watchlist.json: ["AAPL"]

# Run manually
.venv311\Scripts\python.exe -m src.core.cli.run_morning_snapshot
```

**This works for:**
- Quick development iteration
- Testing specific sources in isolation
- Debugging failing sources

**But lacks:**
- Automated regression detection
- Consistent test conditions
- CI/CD integration

### Automated Testing (Recommended Addition)

A proper testing framework adds:
- **Repeatability** - Same conditions every run
- **Regression detection** - Catches breaking changes
- **Documentation** - Tests show expected behavior
- **CI/CD integration** - Automated checks before deploy

---

## 2. The Testing Pyramid

```
                    ┌─────────────────────┐
                    │   E2E Tests         │  ← Few, slow, expensive
                    │   (Full Pipeline)   │     Real browser sessions
                    └─────────────────────┘
                           ▲
                           │
                    ┌─────────────────────┐
                    │ Integration Tests   │  ← Medium, fast, mocked
                    │ (Source Modules)    │     Mock Stagehand pages
                    └─────────────────────┘
                           ▲
                           │
          ┌────────────────┴────────────────┐
          │                                 │
┌─────────────────────┐         ┌─────────────────────┐
│ Unit Tests          │         │ Unit Tests          │
│ (Pydantic Models)   │         │ (Report Builder)    │  ← Many, instant
│ • Validation        │         │ • Formatting        │
│ • Type safety       │         │ • Sentiment logic   │
└─────────────────────┘         └─────────────────────┘
```

---

## 3. Test Types

### 3.1 Unit Tests (Fast, Free)

Test individual functions and models without dependencies.

**What to test:**
- Pydantic model validation
- Report builder formatting
- Sentiment determination logic

**Example: Testing Pydantic Models**

```python
# tests/unit/test_yahoo_quote_model.py
import pytest
from src.skills.yahoo.quote import YahooQuoteSnapshot

def test_yahoo_quote_valid_data():
    """Test model accepts valid quote data."""
    data = {
        "ticker": "AAPL",
        "lastPrice": 280.35,
        "changePct": -1.34,
        "volume": 12242935
    }
    quote = YahooQuoteSnapshot(**data)
    assert quote.ticker == "AAPL"
    assert quote.last_price == 280.35

def test_yahoo_quote_missing_required_field():
    """Test model requires ticker field."""
    data = {"lastPrice": 280.35}
    with pytest.raises(ValidationError):
        YahooQuoteSnapshot(**data)
```

**Example: Testing Report Builder**

```python
# tests/unit/test_report_builder.py
def test_determine_sentiment_bullish():
    """Test sentiment with bullish data."""
    quote = YahooQuoteSnapshot(ticker="AAPL", change_pct=2.5)
    analysis = YahooAIAnalysis(ticker="AAPL", summary="Strong earnings")

    sentiment, summary = _determine_sentiment(quote, analysis)
    assert "Bullish" in sentiment
```

### 3.2 Integration Tests (Fast, Free)

Test source modules with mocked page objects.

**What to test:**
- Extraction logic
- Error handling
- Data transformation

**Example: Mocked Source Test**

```python
# tests/integration/test_yahoo_quote.py
import pytest
from unittest.mock import AsyncMock
from src.skills.yahoo.quote import fetch_yahoo_quote

@pytest.mark.asyncio
async def test_fetch_yahoo_quote_success():
    """Test quote extraction with mocked page."""
    mock_page = AsyncMock()
    mock_page.extract.return_value = YahooQuoteSnapshot(
        ticker="AAPL",
        last_price=280.35,
        change_pct=-1.34
    )

    result = await fetch_yahoo_quote(mock_page, "AAPL")

    mock_page.goto.assert_called()
    assert result.ticker == "AAPL"
    assert result.last_price == 280.35

@pytest.mark.asyncio
async def test_fetch_yahoo_quote_handles_error():
    """Test error handling."""
    mock_page = AsyncMock()
    mock_page.extract.side_effect = Exception("Extraction failed")

    with pytest.raises(Exception):
        await fetch_yahoo_quote(mock_page, "AAPL")
```

### 3.3 E2E Tests (Slow, Costs Money)

Test the full pipeline with real browser sessions.

**What to test:**
- Complete pipeline execution
- Output file generation
- Multi-source integration

**Example: Full Pipeline Test**

```python
# tests/e2e/test_full_pipeline.py
import pytest
import os
from pathlib import Path
from src.core.cli.run_morning_snapshot import main

@pytest.mark.asyncio
@pytest.mark.e2e
async def test_minimal_pipeline():
    """E2E test with minimal config."""
    # Set minimal config
    os.environ["ENABLE_YAHOO_QUOTE"] = "true"
    os.environ["ENABLE_YAHOO_ANALYSIS"] = "false"
    os.environ["ENABLE_GOOGLE_NEWS"] = "false"
    os.environ["ENABLE_VITAL_NEWS"] = "false"
    os.environ["MAX_CONCURRENT_BROWSERS"] = "1"

    # Run pipeline
    await main()

    # Verify outputs
    snapshot_files = list(Path("data/snapshots").glob("*.json"))
    assert len(snapshot_files) > 0, "Snapshot file should exist"
```

---

## 4. Why Pydantic Validation Matters

Stagehand's AI extraction can return unexpected formats:

**Without validation:**
```python
# AI returns string instead of number
{"lastPrice": "280.35", "changePct": "-1.34%"}

# Your code crashes later:
price_change = quote.change_pct * 2  # Can't multiply string!
```

**With Pydantic validation:**
```python
# Validation catches the error immediately:
ValidationError: changePct - Input should be a valid number
```

**Key benefits:**
- Catch errors at extraction, not report generation
- Type safety for financial calculations
- Self-documenting data requirements

---

## 5. Test Directory Structure

```
morning_report/
├── src/                          # Application code
│   └── ...
│
├── tests/                        # All tests go here
│   ├── __init__.py
│   │
│   ├── unit/                     # Fast unit tests
│   │   ├── __init__.py
│   │   ├── test_yahoo_quote_model.py
│   │   ├── test_report_builder.py
│   │   └── test_sentiment_logic.py
│   │
│   ├── integration/              # Mocked integration tests
│   │   ├── __init__.py
│   │   ├── test_yahoo_quote.py
│   │   ├── test_yahoo_analysis.py
│   │   └── test_google_news.py
│   │
│   └── e2e/                      # Full pipeline tests
│       ├── __init__.py
│       └── test_full_pipeline.py
│
└── pytest.ini                    # pytest configuration
```

---

## 6. Running Tests

### Prerequisites

```bash
pip install pytest pytest-asyncio
```

### Commands

```bash
# Run all tests
pytest

# Run only unit tests (fast)
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run E2E tests (slow, uses Browserbase)
pytest tests/e2e/ -v

# Skip E2E tests
pytest -m "not e2e"

# Verbose output with print statements
pytest tests/e2e/test_full_pipeline.py -v -s

# Stop on first failure
pytest -x
```

### pytest.ini Configuration

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
markers =
    e2e: marks tests as end-to-end (deselect with '-m "not e2e"')
asyncio_mode = auto
```

---

## 7. When to Run Which Tests

| Scenario | Tests to Run | Time |
|----------|--------------|------|
| During development | Unit tests only | < 1 second |
| Before committing | Unit + Integration | < 10 seconds |
| Before deployment | All tests including E2E | 2-5 minutes |
| Website layout change | Integration for that source | < 5 seconds |

---

## 8. Common Issues & Solutions

### Module Not Found Error

```
ModuleNotFoundError: No module named 'src'
```

**Solution:** Run pytest from project root:
```bash
cd /path/to/morning_report
pytest tests/
```

### Missing Environment Variables

```
RuntimeError: BROWSERBASE_API_KEY not set
```

**Solution:** Ensure `.env` file exists with all required keys.

### pytest-asyncio Not Installed

```
RuntimeError: This event loop is already running
```

**Solution:**
```bash
pip install pytest-asyncio
```

---

## 9. Test Coverage Targets

| Module | Test Type | Coverage Goal |
|--------|-----------|---------------|
| Pydantic models | Unit | All validation rules |
| Report builder | Unit | Formatting + sentiment logic |
| Source modules | Integration | Success + error paths |
| Full pipeline | E2E | 1-2 smoke tests |

---

## 10. Summary

**Test Types:**
- **Unit tests** (instant, free) - Validate models and logic
- **Integration tests** (fast, free) - Test extraction with mocks
- **E2E tests** (slow, costs $) - Verify full pipeline

**Key Principles:**
- Tests go in `tests/` directory (separate from `src/`)
- Use `@pytest.mark.e2e` to mark slow tests
- Skip E2E in fast development cycles: `pytest -m "not e2e"`
- Pydantic validation catches bad data early

**Quick Start:**
```bash
# Create test structure
mkdir -p tests/unit tests/integration tests/e2e
touch tests/__init__.py

# Install pytest
pip install pytest pytest-asyncio

# Run tests
pytest tests/unit/ -v
```

