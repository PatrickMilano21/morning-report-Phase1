# E2E Tests Directory

This directory contains end-to-end tests that run the full pipeline with real browser sessions.

## Structure

```
tests/
├── unit/           # Fast unit tests (no browser sessions)
├── integration/    # Integration tests (mocked browser sessions)
└── e2e/           # ✨ E2E tests (real Browserbase sessions)
    └── test_full_pipeline.py
```

## Running E2E Tests

```bash
# Run all E2E tests
pytest tests/e2e/

# Run specific E2E test
pytest tests/e2e/test_full_pipeline.py

# Skip E2E tests (for fast test runs)
pytest -m "not e2e"
```

## Note

E2E tests use real Browserbase sessions and will consume API credits. Run them:
- Before deploying to production
- When making significant changes
- In CI/CD pipelines (with API keys configured)

