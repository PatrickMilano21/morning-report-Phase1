"""
Yahoo Finance quote extraction using observe() -> cache -> extract() pattern.
"""
from typing import Optional

from src.core.cache import selector_cache
from src.core.retry_helpers import navigate_with_retry
from .schemas import YahooQuotePrices, YahooQuoteVolume, YahooQuoteSnapshot

CACHE_KEY = "yahoo_quote_main_container"


async def _get_or_discover_selector(page, cache_key: str) -> Optional[str]:
    """
    Get cached selector or discover via observe().
    Returns XPath selector or None if discovery fails.
    """
    selector = selector_cache.get(cache_key)

    if selector:
        return selector

    # Discover selector via observe()
    regions = await page.observe(
        "find the entire quote page section containing the stock price, change, previous close, volume, and statistics table"
    )

    if regions:
        selector = regions[0].selector
        selector_cache.set(cache_key, selector)
        return selector

    return None


async def _scoped_extract(page, instruction: str, schema, selector: Optional[str]):
    """
    Extract with scoped selector, falling back to full-page if needed.
    """
    if selector:
        try:
            return await page.extract(
                instruction=instruction,
                schema=schema,
                selector=selector,
            )
        except Exception:
            # Selector invalid - clear cache for next run
            selector_cache.delete(CACHE_KEY)

    # Fallback: full-page extract
    return await page.extract(
        instruction=instruction,
        schema=schema,
    )


async def fetch_yahoo_quote_prices(page, ticker: str) -> YahooQuotePrices:
    """
    Extract price data from Yahoo Finance quote page.
    Uses cached selector when available.
    """
    url = f"https://finance.yahoo.com/quote/{ticker}"
    await navigate_with_retry(page, url, max_retries=2, timeout=30000)

    selector = await _get_or_discover_selector(page, CACHE_KEY)

    return await _scoped_extract(
        page=page,
        instruction="Extract only: current price, absolute change, percentage change, previous close.",
        schema=YahooQuotePrices,
        selector=selector,
    )


async def fetch_yahoo_quote_volume(page, ticker: str) -> YahooQuoteVolume:
    """
    Extract volume data from Yahoo Finance quote page.
    Assumes page already navigated. Uses cached selector.
    """
    selector = await _get_or_discover_selector(page, CACHE_KEY)

    return await _scoped_extract(
        page=page,
        instruction="Extract only: current volume, average daily volume.",
        schema=YahooQuoteVolume,
        selector=selector,
    )


async def fetch_yahoo_quote(page, ticker: str) -> YahooQuoteSnapshot:
    """
    Legacy function for backwards compatibility.
    Extracts full quote snapshot using the new pattern.
    """
    url = f"https://finance.yahoo.com/quote/{ticker}"
    await navigate_with_retry(page, url, max_retries=2, timeout=30000)

    selector = await _get_or_discover_selector(page, CACHE_KEY)

    snapshot = await _scoped_extract(
        page=page,
        instruction="Extract: current price, change, previous close, open, day range, volume, avg volume.",
        schema=YahooQuoteSnapshot,
        selector=selector,
    )

    snapshot.ticker = ticker.upper()
    return snapshot
