import logging
import time
from dataclasses import dataclass, field
from typing import List, Protocol

from config.settings import Settings
from src.ingestion.bluesky_firehose import BlueskyFirehose
from src.ingestion.demo_stream import DemoStream
from src.models.post import ProcessedPost, RawPost
from src.processing import sentiment, ticker_extractor
from src.quality.dedup import Deduplicator
from src.quality.validator import validate
from src.signals.aggregator import SignalAggregator
from src.storage.s3_writer import S3Writer

logger = logging.getLogger(__name__)


class IngestionSource(Protocol):
    def start(self) -> None: ...
    def stop(self, timeout: float = ...) -> None: ...
    def stream(self): ...


@dataclass
class PipelineMetrics:
    ingested: int = 0
    duplicates: int = 0
    invalid: int = 0
    processed: int = 0
    written: int = 0
    processing_latencies_ms: List[float] = field(default_factory=list)
    write_latencies_ms: List[float] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)

    def snapshot(self) -> dict:
        elapsed = time.time() - self.start_time
        recent_proc = self.processing_latencies_ms[-200:]
        recent_write = self.write_latencies_ms[-50:]
        quality_rate = (
            self.processed / max(1, self.ingested - self.duplicates)
        )
        return {
            "elapsed_s": round(elapsed, 1),
            "ingested": self.ingested,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "processed": self.processed,
            "written": self.written,
            "throughput_per_min": round(self.processed / max(1, elapsed) * 60, 1),
            "quality_pass_rate": round(quality_rate, 3),
            "p50_proc_ms": round(_percentile(recent_proc, 50), 2),
            "p99_proc_ms": round(_percentile(recent_proc, 99), 2),
            "avg_write_ms": round(sum(recent_write) / len(recent_write), 2) if recent_write else 0,
        }


def _percentile(data: List[float], pct: int) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * pct / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def _process_post(raw: RawPost, quality_threshold: float = 0.5) -> tuple:
    """Score, extract tickers, validate. Returns (ProcessedPost | None, QualityReport)."""
    scores = sentiment.score(raw.title + " " + raw.body)
    tickers = ticker_extractor.extract(raw.title + " " + raw.body)

    post = ProcessedPost(
        post_id=raw.post_id,
        source=raw.source,
        title=raw.title,
        body=raw.body,
        score=raw.score,
        upvote_ratio=raw.upvote_ratio,
        num_comments=raw.num_comments,
        created_utc=raw.created_utc,
        url=raw.url,
        fetched_at=raw.fetched_at,
        sentiment_compound=scores.compound,
        sentiment_positive=scores.positive,
        sentiment_negative=scores.negative,
        sentiment_neutral=scores.neutral,
        tickers=tickers,
        quality_score=0.0,
    )

    report = validate(post)
    post.quality_score = report.quality_score

    if not report.is_valid or report.quality_score < quality_threshold:
        return None, report
    return post, report


def build_source(settings: Settings) -> IngestionSource:
    """Choose the ingestion source. Demo mode for offline / CI; Bluesky
    Jetstream for live runs."""
    if settings.demo_mode:
        return DemoStream(settings)
    return BlueskyFirehose(settings)


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.source: IngestionSource = build_source(settings)
        self.dedup = Deduplicator(settings.dedup_window_seconds)
        self.writer = S3Writer(settings)
        self.aggregator = SignalAggregator()
        self.metrics = PipelineMetrics()
        self._batch: List[ProcessedPost] = []
        self._last_flush = time.time()

    def run(self) -> None:
        mode = "demo" if self.settings.demo_mode else "live-bluesky"
        logger.info(f"Pipeline starting (mode={mode})")
        self.source.start()
        try:
            for raw in self.source.stream():
                self._handle(raw)
        except KeyboardInterrupt:
            logger.info("Shutdown signal received — flushing final batch")
        finally:
            self.source.stop()
            self._flush()
            self._print_summary()

    def _handle(self, raw: RawPost) -> None:
        self.metrics.ingested += 1

        if self.dedup.is_duplicate(raw.post_id):
            self.metrics.duplicates += 1
            return

        t0 = time.monotonic()
        post, report = _process_post(raw)
        elapsed_ms = (time.monotonic() - t0) * 1000
        self.metrics.processing_latencies_ms.append(elapsed_ms)

        if post is None:
            self.metrics.invalid += 1
            if report.issues:
                logger.debug(f"Dropped {raw.post_id}: {report.issues}")
            return

        self._batch.append(post)
        self.metrics.processed += 1

        for ticker in post.tickers:
            self.aggregator.update(ticker, post.sentiment_compound, post.created_utc)

        if self._should_flush():
            self._flush()
            self._log_metrics()

    def _should_flush(self) -> bool:
        return (
            len(self._batch) >= self.settings.batch_size
            or time.time() - self._last_flush >= self.settings.batch_timeout_seconds
        )

    def _flush(self) -> None:
        if not self._batch:
            return
        t0 = time.monotonic()
        self.writer.write_batch(self._batch)
        elapsed_ms = (time.monotonic() - t0) * 1000
        self.metrics.write_latencies_ms.append(elapsed_ms)
        self.metrics.written += len(self._batch)
        self._batch = []
        self._last_flush = time.time()
        self.aggregator.evict_old()

    def _log_metrics(self) -> None:
        snap = self.metrics.snapshot()
        logger.info(
            f"[pipeline] elapsed={snap['elapsed_s']}s "
            f"ingested={snap['ingested']} "
            f"processed={snap['processed']} "
            f"written={snap['written']} "
            f"dups={snap['duplicates']} "
            f"quality={snap['quality_pass_rate']:.1%} "
            f"throughput={snap['throughput_per_min']}/min "
            f"p50={snap['p50_proc_ms']}ms p99={snap['p99_proc_ms']}ms"
        )

        # Surface firehose-level metrics when running live
        if isinstance(self.source, BlueskyFirehose):
            fs = self.source.stats.snapshot()
            logger.info(
                f"[firehose] received={fs['received_total']} "
                f"forwarded={fs['forwarded']} "
                f"non_fin={fs['dropped_non_financial']} "
                f"queue_full={fs['dropped_queue_full']} "
                f"reconnects={fs['reconnects']} "
                f"rate={fs['events_per_sec']}/s "
                f"lag={fs['feed_lag_s']}s"
            )

    def _print_summary(self) -> None:
        snap = self.metrics.snapshot()
        top = self.aggregator.top_tickers("1h", n=5)
        print("\n=== Pipeline Summary ===")
        for k, v in snap.items():
            print(f"  {k}: {v}")
        print("\n  Top tickers (1h):")
        for t in top:
            print(f"    {t['ticker']}: {t['mentions']} mentions, avg_sentiment={t['avg_sentiment']}")
        print("========================\n")
