import time
from collections import defaultdict, deque
from typing import Dict, List


class SignalAggregator:
    """
    Maintains rolling sentiment windows per ticker.

    Stores (timestamp, sentiment_compound) tuples in a deque per ticker.
    Windows: 5min, 1hr, 24hr.
    """

    WINDOWS = {
        "5m": 300,
        "1h": 3600,
        "24h": 86400,
    }

    def __init__(self):
        self._data: Dict[str, deque] = defaultdict(deque)

    def update(self, ticker: str, compound: float, ts: float = None) -> None:
        if ts is None:
            ts = time.time()
        self._data[ticker].append((ts, compound))

    def get_signal(self, ticker: str) -> Dict[str, float]:
        """Return average sentiment for each window. None if no data in window."""
        now = time.time()
        entries = list(self._data[ticker])
        result = {}
        for label, seconds in self.WINDOWS.items():
            cutoff = now - seconds
            window_values = [s for t, s in entries if t >= cutoff]
            result[f"sentiment_{label}"] = (
                round(sum(window_values) / len(window_values), 4)
                if window_values else None
            )
            result[f"mentions_{label}"] = len(window_values)
        return result

    def top_tickers(self, window: str = "1h", n: int = 10) -> List[dict]:
        """Return top N tickers by mention count in the given window."""
        now = time.time()
        seconds = self.WINDOWS[window]
        cutoff = now - seconds

        counts = []
        for ticker, entries in self._data.items():
            mentions = [s for t, s in entries if t >= cutoff]
            if mentions:
                counts.append({
                    "ticker": ticker,
                    "mentions": len(mentions),
                    "avg_sentiment": round(sum(mentions) / len(mentions), 4),
                })
        return sorted(counts, key=lambda x: x["mentions"], reverse=True)[:n]

    def evict_old(self) -> None:
        """Remove entries older than the largest window to bound memory."""
        cutoff = time.time() - self.WINDOWS["24h"]
        for ticker in list(self._data.keys()):
            d = self._data[ticker]
            while d and d[0][0] < cutoff:
                d.popleft()
            if not d:
                del self._data[ticker]
