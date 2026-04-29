from src.processing import sentiment, ticker_extractor


class TestSentiment:
    def test_positive_text(self):
        result = sentiment.score("NVDA is amazing, huge gains, excellent stock!")
        assert result.compound > 0.3

    def test_negative_text(self):
        result = sentiment.score("This stock is a disaster, losing everything, complete crash")
        assert result.compound < -0.3

    def test_neutral_text(self):
        result = sentiment.score("Earnings call scheduled for next Tuesday at 4pm")
        assert -0.2 <= result.compound <= 0.2

    def test_empty_text(self):
        result = sentiment.score("")
        assert result.compound == 0.0

    def test_scores_sum_to_one(self):
        result = sentiment.score("Buying more AAPL calls today")
        total = round(result.positive + result.negative + result.neutral, 1)
        assert total == 1.0

    def test_truncates_long_text(self):
        # Should not raise even with very long input
        long_text = "TSLA " * 10000
        result = sentiment.score(long_text)
        assert -1.0 <= result.compound <= 1.0


class TestTickerExtractor:
    def test_dollar_sign_ticker(self):
        tickers = ticker_extractor.extract("Buying $AAPL and $TSLA today")
        assert "AAPL" in tickers
        assert "TSLA" in tickers

    def test_caps_ticker(self):
        tickers = ticker_extractor.extract("SPY puts printing hard this week")
        assert "SPY" in tickers

    def test_filters_blacklisted_words(self):
        tickers = ticker_extractor.extract("THE CEO said WE ARE going to MOON")
        assert "THE" not in tickers
        assert "CEO" not in tickers
        assert "ARE" not in tickers

    def test_deduplicates(self):
        tickers = ticker_extractor.extract("$NVDA NVDA $NVDA is the best stock NVDA")
        assert tickers.count("NVDA") == 1

    def test_returns_sorted(self):
        tickers = ticker_extractor.extract("$TSLA and $AAPL and $NVDA")
        assert tickers == sorted(tickers)

    def test_empty_text(self):
        assert ticker_extractor.extract("") == []

    def test_unknown_ticker_ignored(self):
        tickers = ticker_extractor.extract("$ZZZZ is a fake ticker")
        assert "ZZZZ" not in tickers
