import time
from src.signals.aggregator import SignalAggregator


class TestSignalAggregator:
    def test_update_and_retrieve(self):
        agg = SignalAggregator()
        agg.update("AAPL", 0.5)
        sig = agg.get_signal("AAPL")
        assert sig["sentiment_5m"] == 0.5
        assert sig["mentions_5m"] == 1

    def test_average_over_multiple_updates(self):
        agg = SignalAggregator()
        agg.update("TSLA", 1.0)
        agg.update("TSLA", 0.0)
        sig = agg.get_signal("TSLA")
        assert sig["sentiment_5m"] == 0.5

    def test_unknown_ticker_returns_none(self):
        agg = SignalAggregator()
        sig = agg.get_signal("ZZZZ")
        assert sig["sentiment_5m"] is None
        assert sig["mentions_5m"] == 0

    def test_old_entry_excluded_from_window(self):
        agg = SignalAggregator()
        old_ts = time.time() - 400  # older than 5m window
        agg.update("GME", 1.0, ts=old_ts)
        agg.update("GME", -0.5)  # recent
        sig = agg.get_signal("GME")
        assert sig["mentions_5m"] == 1
        assert sig["sentiment_5m"] == -0.5

    def test_top_tickers_sorted_by_mentions(self):
        agg = SignalAggregator()
        for _ in range(3):
            agg.update("NVDA", 0.8)
        agg.update("AMD", 0.3)
        top = agg.top_tickers("5m", n=2)
        assert top[0]["ticker"] == "NVDA"
        assert top[0]["mentions"] == 3

    def test_evict_old_removes_stale_data(self):
        agg = SignalAggregator()
        old_ts = time.time() - 90000  # older than 24h
        agg.update("BB", 0.1, ts=old_ts)
        agg.evict_old()
        assert "BB" not in agg._data
