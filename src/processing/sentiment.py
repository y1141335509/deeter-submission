from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from src.models.post import SentimentScores

_MAX_TEXT_LENGTH = 2000  # VADER degrades past this; truncate to keep latency stable

_analyzer = SentimentIntensityAnalyzer()


def score(text: str) -> SentimentScores:
    clean = text.strip()[:_MAX_TEXT_LENGTH] if text else ""
    scores = _analyzer.polarity_scores(clean)
    return SentimentScores(
        compound=scores["compound"],
        positive=scores["pos"],
        negative=scores["neg"],
        neutral=scores["neu"],
    )
