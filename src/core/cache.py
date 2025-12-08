"""
Simple in-memory cache for selectors and other reusable data.
"""
from typing import Optional, Dict, Any


class SelectorCache:
    """
    In-memory cache for XPath selectors from observe().
    Allows reuse across multiple tickers without re-observing.
    """

    def __init__(self):
        self._cache: Dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        """Get cached selector or None if not found."""
        return self._cache.get(key)

    def set(self, key: str, selector: str) -> None:
        """Cache a selector."""
        self._cache[key] = selector

    def delete(self, key: str) -> None:
        """Remove a selector from cache."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached selectors."""
        self._cache.clear()


# Global singleton instance
selector_cache = SelectorCache()
