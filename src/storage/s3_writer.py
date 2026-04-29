import io
import logging
import time
from datetime import datetime, timezone
from typing import List

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.config import Config

from config.settings import Settings
from src.models.post import ProcessedPost

logger = logging.getLogger(__name__)

# Parquet schema — explicit types keep files predictable for downstream consumers
_POST_SCHEMA = pa.schema([
    pa.field("post_id", pa.string()),
    pa.field("subreddit", pa.string()),
    pa.field("title", pa.string()),
    pa.field("body", pa.string()),
    pa.field("score", pa.int32()),
    pa.field("upvote_ratio", pa.float32()),
    pa.field("num_comments", pa.int32()),
    pa.field("created_utc", pa.float64()),
    pa.field("url", pa.string()),
    pa.field("fetched_at", pa.float64()),
    pa.field("sentiment_compound", pa.float32()),
    pa.field("sentiment_positive", pa.float32()),
    pa.field("sentiment_negative", pa.float32()),
    pa.field("sentiment_neutral", pa.float32()),
    pa.field("tickers", pa.list_(pa.string())),
    pa.field("quality_score", pa.float32()),
    pa.field("processed_at", pa.float64()),
])

# Per-ticker mention schema for the signals layer
_MENTION_SCHEMA = pa.schema([
    pa.field("post_id", pa.string()),
    pa.field("ticker", pa.string()),
    pa.field("subreddit", pa.string()),
    pa.field("sentiment_compound", pa.float32()),
    pa.field("score", pa.int32()),
    pa.field("created_utc", pa.float64()),
    pa.field("processed_at", pa.float64()),
])


class S3Writer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.settings.s3_bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.settings.s3_bucket)
            logger.info(f"Created bucket: {self.settings.s3_bucket}")

    def write_batch(self, posts: List[ProcessedPost]) -> dict:
        """
        Write a batch of processed posts to S3 as Parquet.
        Returns write stats: bytes written, key paths.
        """
        if not posts:
            return {}

        ts = time.time()
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        partition = (
            f"year={dt.year}/month={dt.month:02d}/"
            f"day={dt.day:02d}/hour={dt.hour:02d}"
        )
        batch_id = f"{int(ts * 1000)}"

        posts_key = f"posts/{partition}/batch_{batch_id}.parquet"
        posts_bytes = self._posts_to_parquet(posts)
        self._put(posts_key, posts_bytes)

        mentions = self._explode_mentions(posts)
        mentions_key = None
        if mentions:
            mentions_key = f"mentions/{partition}/batch_{batch_id}.parquet"
            mentions_bytes = self._mentions_to_parquet(mentions)
            self._put(mentions_key, mentions_bytes)

        logger.info(
            f"Wrote batch | posts={len(posts)} post_key={posts_key} "
            f"mentions={len(mentions)} post_bytes={len(posts_bytes)}"
        )
        return {
            "posts_key": posts_key,
            "mentions_key": mentions_key,
            "num_posts": len(posts),
            "num_mentions": len(mentions),
            "posts_bytes": len(posts_bytes),
        }

    def _put(self, key: str, data: bytes) -> None:
        self.client.put_object(
            Bucket=self.settings.s3_bucket,
            Key=key,
            Body=data,
            ContentType="application/octet-stream",
        )

    def _posts_to_parquet(self, posts: List[ProcessedPost]) -> bytes:
        rows = [p.to_dict() for p in posts]
        table = pa.Table.from_pylist(rows, schema=_POST_SCHEMA)
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        return buf.getvalue()

    def _explode_mentions(self, posts: List[ProcessedPost]) -> List[dict]:
        """One row per (post, ticker) pair — optimised for per-ticker queries."""
        mentions = []
        for p in posts:
            for ticker in p.tickers:
                mentions.append({
                    "post_id": p.post_id,
                    "ticker": ticker,
                    "subreddit": p.subreddit,
                    "sentiment_compound": p.sentiment_compound,
                    "score": p.score,
                    "created_utc": p.created_utc,
                    "processed_at": p.processed_at,
                })
        return mentions

    def _mentions_to_parquet(self, mentions: List[dict]) -> bytes:
        table = pa.Table.from_pylist(mentions, schema=_MENTION_SCHEMA)
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        return buf.getvalue()
