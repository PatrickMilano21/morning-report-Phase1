# tests/e2e/test_full_pipeline.py

import pytest
import asyncio
import os
import json
from pathlib import Path
from datetime import date

from src.core.cli.run_morning_snapshot import main


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_minimal_pipeline():
    """E2E test: Run full pipeline with minimal sources (Yahoo Quote only)."""

    # Save original environment
    env_keys = [
        "ENABLE_YAHOO_QUOTE", "ENABLE_YAHOO_ANALYSIS", "ENABLE_GOOGLE_NEWS",
        "ENABLE_VITAL_NEWS", "ENABLE_MACRO_NEWS", "ENABLE_MARKETWATCH",
        "MAX_CONCURRENT_BROWSERS"
    ]
    original_env = {key: os.environ.get(key) for key in env_keys}

    try:
        # Set up minimal test environment
        os.environ["ENABLE_YAHOO_QUOTE"] = "true"
        os.environ["ENABLE_YAHOO_ANALYSIS"] = "false"
        os.environ["ENABLE_GOOGLE_NEWS"] = "false"
        os.environ["ENABLE_VITAL_NEWS"] = "false"
        os.environ["ENABLE_MACRO_NEWS"] = "false"
        os.environ["ENABLE_MARKETWATCH"] = "false"
        os.environ["MAX_CONCURRENT_BROWSERS"] = "1"

        # Backup and set minimal watchlist
        watchlist_file = Path("config/watchlist.json")
        original_watchlist = watchlist_file.read_text() if watchlist_file.exists() else None
        watchlist_file.write_text('["AAPL"]')

        try:
            # Run the pipeline
            await main()

            # Verify snapshot file created
            today = date.today().isoformat()
            snapshot_file = Path(f"data/snapshots/yahoo_snapshot_{today}.json")
            assert snapshot_file.exists(), "Yahoo snapshot file should exist"

            # Verify snapshot content
            snapshot_data = json.loads(snapshot_file.read_text())
            assert snapshot_data["as_of"] == today
            assert len(snapshot_data["tickers"]) == 1
            assert snapshot_data["tickers"][0]["ticker"] == "AAPL"
            assert snapshot_data["tickers"][0]["quote"] is not None, "Quote data should exist"

            # Verify report file created
            report_file = Path(f"data/reports/morning_snapshot_{today}.md")
            assert report_file.exists(), "Report file should exist"

            # Verify report content
            report_text = report_file.read_text()
            assert "AAPL" in report_text, "Report should contain ticker"

        finally:
            # Restore original watchlist
            if original_watchlist:
                watchlist_file.write_text(original_watchlist)

    finally:
        # Restore original environment
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
