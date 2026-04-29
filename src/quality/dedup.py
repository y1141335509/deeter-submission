import time
from collections import OrderedDict


class Deduplicator:
    """
    Time-bounded deduplication by post ID.

    Uses an ordered dict as a sliding window: entries older than
    `window_seconds` are evicted on each check to bound memory growth.
    """

    def __init__(self, window_seconds: int = 3600):
        self.window = window_seconds
        self._seen: OrderedDict[str, float] = OrderedDict()

    def is_duplicate(self, post_id: str) -> bool:
        now = time.time()
        self._evict(now)
        if post_id in self._seen:
            return True
        self._seen[post_id] = now
        return False

    def _evict(self, now: float) -> None:
        cutoff = now - self.window
        while self._seen:
            oldest_id, oldest_ts = next(iter(self._seen.items()))
            if oldest_ts < cutoff:
                del self._seen[oldest_id]
            else:
                break

    @property
    def size(self) -> int:
        return len(self._seen)
