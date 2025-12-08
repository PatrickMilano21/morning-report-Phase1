# src/skills/yahoo/test_scoped_screenshot.py
"""
Test script for observe() → cache → extract() pattern.
Tests scoped extraction with cached XPath selectors.
"""

import asyncio
import os
from src.core.stagehand_runner import create_stagehand_session
from src.core.cache import selector_cache
from src.skills.yahoo.quote import (
    fetch_yahoo_quote_prices,
    fetch_yahoo_quote_volume,
)


async def test_single_ticker():
    """
    Test observe → cache → extract on a single ticker.
    Verifies all fields are extracted correctly.
    """
    stagehand, page = await create_stagehand_session()

    # Ensure output directory exists
    os.makedirs('data/debug', exist_ok=True)

    try:
        # Clear cache to test fresh discovery
        selector_cache.clear()
        print("[Test] Cleared selector cache")

        ticker = "AAPL"
        print(f"\n{'='*60}")
        print(f"Testing observe -> cache -> extract for {ticker}")
        print("="*60)

        # Extract prices (this will observe and cache selector)
        print("\n[1] Extracting prices (will observe first)...")
        prices = await fetch_yahoo_quote_prices(page, ticker)

        print(f"\n  PRICES:")
        print(f"    last_price:     {prices.last_price}")
        print(f"    change_abs:     {prices.change_abs}")
        print(f"    change_pct:     {prices.change_pct}")
        print(f"    previous_close: {prices.previous_close}")

        # Check what selector was cached
        cached = selector_cache.get("yahoo_quote_main_container")
        if cached:
            print(f"\n  Cached selector: {cached[:100]}...")
        else:
            print("\n  WARNING: No selector was cached!")

        # Extract volume (should use cached selector)
        print("\n[2] Extracting volume (should use cache)...")
        volume = await fetch_yahoo_quote_volume(page, ticker)

        print(f"\n  VOLUME:")
        print(f"    volume:     {volume.volume}")
        print(f"    avg_volume: {volume.avg_volume}")

        # Summary
        print(f"\n{'='*60}")
        print("EXTRACTION SUMMARY")
        print("="*60)

        missing = []
        if prices.last_price is None:
            missing.append("last_price")
        if prices.change_abs is None:
            missing.append("change_abs")
        if prices.change_pct is None:
            missing.append("change_pct")
        if prices.previous_close is None:
            missing.append("previous_close")
        if volume.volume is None:
            missing.append("volume")
        if volume.avg_volume is None:
            missing.append("avg_volume")

        if missing:
            print(f"  MISSING FIELDS: {', '.join(missing)}")
            print("  -> The observe selector may be too narrow")
        else:
            print("  All fields extracted successfully!")

        print(f"\n{'='*60}")
        print("[Test] DONE - Check Browserbase replay for token counts")
        print("  - observe() call (expensive, one-time)")
        print("  - extract() calls (cheap, reusable)")
        print("="*60)

    finally:
        await stagehand.close()


CACHE_KEY = "yahoo_quote_main_container"


async def test_multi_ticker():
    """
    Test observe -> cache -> extract across multiple tickers.
    Verifies cache is reused after first ticker.
    """
    stagehand, page = await create_stagehand_session()

    try:
        selector_cache.clear()
        tickers = ["AAPL", "MSFT", "GOOGL"]
        results = []

        for i, ticker in enumerate(tickers):
            print(f"\n[{i+1}/{len(tickers)}] Processing {ticker}...")

            # Check if cache exists before this ticker
            had_cache = selector_cache.get(CACHE_KEY) is not None

            try:
                prices = await fetch_yahoo_quote_prices(page, ticker)
                volume = await fetch_yahoo_quote_volume(page, ticker)

                results.append({
                    "ticker": ticker,
                    "used_cache": had_cache,
                    "prices": prices,
                    "volume": volume,
                })

                print(f"  {ticker}: ${prices.last_price} ({prices.change_pct}%)")
                print(f"  Cache {'HIT' if had_cache else 'MISS (observed)'}")

            except Exception as e:
                print(f"  ERROR: {e}")
                results.append({"ticker": ticker, "error": str(e)})

        # Summary
        print(f"\n{'='*60}")
        print("MULTI-TICKER SUMMARY")
        print("="*60)
        for r in results:
            if "error" in r:
                print(f"  {r['ticker']}: FAILED - {r['error']}")
            else:
                cache_status = "cache HIT" if r['used_cache'] else "observe()"
                print(f"  {r['ticker']}: ${r['prices'].last_price} [{cache_status}]")

    finally:
        await stagehand.close()


if __name__ == "__main__":
    # Run multi-ticker test
    asyncio.run(test_multi_ticker())
