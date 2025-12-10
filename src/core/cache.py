"""
Persistent cache for selectors - saves to disk as JSON.
"""
import json
from pathlib import Path
from typing import Optional, Dict

CACHE_FILE = Path("data/cache/selectors.json")


class SelectorCache:
    """
    Persistent cache for XPath selectors from observe().
    Saves to disk so selectors survive across runs.
    """

    def __init__(self):
        self._cache: Dict[str, str] = {}
        self._load()

    def _load(self):
        """Load cache from disk."""
        if CACHE_FILE.exists():
            try:
                self._cache = json.loads(CACHE_FILE.read_text())
                print(f"[Cache] Loaded {len(self._cache)} cached selectors")
            except (json.JSONDecodeError, IOError):
                self._cache = {}

    def _save(self):
        """Save cache to disk."""
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(self._cache, indent=2))

    def get(self, key: str) -> Optional[str]:
        """Get cached selector or None if not found."""
        return self._cache.get(key)

    def set(self, key: str, selector: str) -> None:
        """Cache a selector and persist to disk."""
        self._cache[key] = selector
        self._save()
        print(f"[Cache] Saved selector for '{key}'")

    def delete(self, key: str) -> None:
        """Remove a selector from cache."""
        if key in self._cache:
            del self._cache[key]
            self._save()

    def clear(self) -> None:
        """Clear all cached selectors."""
        self._cache.clear()
        self._save()


# Global singleton instance
selector_cache = SelectorCache()
