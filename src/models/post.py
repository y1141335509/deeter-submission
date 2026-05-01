from dataclasses import dataclass, field
from typing import List
import time


@dataclass
class RawPost:
    post_id: str
    source: str  # platform/community identifier (e.g. "bluesky", "demo")
    title: str
    body: str
    score: int
    upvote_ratio: float
    num_comments: int
    created_utc: float
    url: str
    fetched_at: float = field(default_factory=time.time)


@dataclass
class SentimentScores:
    compound: float   # -1.0 (most negative) to +1.0 (most positive)
    positive: float
    negative: float
    neutral: float


@dataclass
class QualityReport:
    is_valid: bool
    issues: List[str]
    quality_score: float  # 0.0 to 1.0


@dataclass
class ProcessedPost:
    post_id: str
    source: str
    title: str
    body: str
    score: int
    upvote_ratio: float
    num_comments: int
    created_utc: float
    url: str
    fetched_at: float
    sentiment_compound: float
    sentiment_positive: float
    sentiment_negative: float
    sentiment_neutral: float
    tickers: List[str]
    quality_score: float
    processed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "source": self.source,
            "title": self.title,
            "body": self.body,
            "score": self.score,
            "upvote_ratio": self.upvote_ratio,
            "num_comments": self.num_comments,
            "created_utc": self.created_utc,
            "url": self.url,
            "fetched_at": self.fetched_at,
            "sentiment_compound": self.sentiment_compound,
            "sentiment_positive": self.sentiment_positive,
            "sentiment_negative": self.sentiment_negative,
            "sentiment_neutral": self.sentiment_neutral,
            "tickers": self.tickers,
            "quality_score": self.quality_score,
            "processed_at": self.processed_at,
        }
