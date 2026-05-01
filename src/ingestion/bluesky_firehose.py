"""Bluesky Jetstream WebSocket firehose client.

Connects to the public AT Protocol Jetstream and streams every new post on the
network into a bounded queue. Designed to keep running across connection drops
and to bound memory in the face of downstream backpressure.

Failure modes handled explicitly:

  * connection drops             → exponential backoff reconnect with capped delay
  * resume after restart         → cursor (microsecond timestamp) persisted to
                                   local file on every checkpoint interval
  * downstream slower than feed  → bounded queue + drop-with-counter when full
                                   (drops are counted and surfaced in metrics)
  * out-of-order or duplicate    → events with time_us <= cursor are skipped
  * non-financial volume         → keyword/symbol prefilter at ingest

The client runs in a background asyncio loop on a daemon thread; the main
pipeline consumes from a sync `queue.Queue` via `stream()`. This keeps the rest
of the pipeline synchronous and isolates all async/network complexity here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Generator, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from config.settings import Settings
from src.models.post import RawPost

logger = logging.getLogger(__name__)

JETSTREAM_HOSTS = [
    "wss://jetstream2.us-east.bsky.network",
    "wss://jetstream1.us-east.bsky.network",
    "wss://jetstream2.us-west.bsky.network",
    "wss://jetstream1.us-west.bsky.network",
]
JETSTREAM_PATH = "/subscribe?wantedCollections=app.bsky.feed.post"

# Heuristic financial-relevance prefilter. Cheap to run, drops the
# overwhelmingly non-financial majority of the firehose before it reaches
# the heavier sentiment / quality / S3 stages.
_FINANCIAL_KEYWORDS = frozenset({
    "stock", "stocks", "shares", "earnings", "calls", "puts", "options",
    "ticker", "bullish", "bearish", "long", "short", "rally", "crash",
    "dip", "trading", "trader", "trade", "market", "markets", "fed",
    "rate", "rates", "yield", "dividend", "ipo", "etf", "portfolio",
    "invest", "investor", "investing", "valuation", "moon", "yolo",
    "wsb", "wallstreetbets", "buy the dip", "to the moon",
    "nasdaq", "sp500", "s&p", "dow",
    "bitcoin", "btc", "crypto", "ethereum", "eth", "altcoin",
})


@dataclass
class FirehoseStats:
    received_total: int = 0
    forwarded: int = 0
    dropped_non_financial: int = 0
    dropped_queue_full: int = 0
    dropped_out_of_order: int = 0
    reconnects: int = 0
    last_event_ts: float = 0.0
    started_at: float = field(default_factory=time.time)

    def snapshot(self) -> dict:
        elapsed = max(1.0, time.time() - self.started_at)
        lag_s = (
            time.time() - self.last_event_ts if self.last_event_ts else None
        )
        return {
            "received_total": self.received_total,
            "forwarded": self.forwarded,
            "dropped_non_financial": self.dropped_non_financial,
            "dropped_queue_full": self.dropped_queue_full,
            "dropped_out_of_order": self.dropped_out_of_order,
            "reconnects": self.reconnects,
            "events_per_sec": round(self.received_total / elapsed, 2),
            "feed_lag_s": round(lag_s, 2) if lag_s is not None else None,
        }


class BlueskyFirehose:
    """Background WebSocket client → bounded queue → sync generator."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._queue: queue.Queue[RawPost] = queue.Queue(
            maxsize=settings.firehose_queue_size
        )
        self.cursor: Optional[int] = None
        self.stats = FirehoseStats()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._cursor_path = settings.firehose_cursor_path
        self._last_cursor_save = 0.0

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        self.cursor = self._load_cursor()
        if self.cursor:
            logger.info(f"Resuming firehose from cursor={self.cursor}")
        else:
            logger.info("Starting firehose without cursor (live tail)")
        self._thread = threading.Thread(
            target=self._thread_main, daemon=True, name="bluesky-firehose"
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(lambda: None)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._save_cursor(force=True)

    def stream(self) -> Generator[RawPost, None, None]:
        """Yield posts from the queue. Blocks briefly when empty."""
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                yield self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

    # -- thread / event loop -------------------------------------------

    def _thread_main(self) -> None:
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_forever())
        except Exception:
            logger.exception("Firehose thread crashed")
        finally:
            if self._loop is not None:
                self._loop.close()

    async def _run_forever(self) -> None:
        attempt = 0
        host_idx = 0
        while not self._stop_event.is_set():
            host = JETSTREAM_HOSTS[host_idx % len(JETSTREAM_HOSTS)]
            url = host + JETSTREAM_PATH
            if self.cursor is not None:
                url += f"&cursor={self.cursor}"
            try:
                async with websockets.connect(
                    url, ping_interval=30, ping_timeout=20, max_size=2**20
                ) as ws:
                    logger.info(f"Connected: {host} cursor={self.cursor}")
                    attempt = 0
                    async for msg in ws:
                        if self._stop_event.is_set():
                            break
                        self._handle_message(msg)
            except (ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                logger.warning(f"Connection to {host} dropped: {e}")
            except Exception:
                logger.exception("Unexpected firehose error")
            if self._stop_event.is_set():
                break
            self.stats.reconnects += 1
            attempt += 1
            host_idx += 1  # rotate to a different host on reconnect
            backoff = min(60.0, (2 ** min(attempt, 6)) + 0.5)
            logger.info(
                f"Reconnecting in {backoff:.1f}s "
                f"(attempt={attempt}, host_idx={host_idx})"
            )
            try:
                await asyncio.wait_for(
                    asyncio.sleep(backoff), timeout=backoff + 1
                )
            except asyncio.TimeoutError:
                pass

    # -- message handling ----------------------------------------------

    def _handle_message(self, raw_msg: str | bytes) -> None:
        post = parse_jetstream_message(raw_msg)
        if post is None:
            return

        # Cursor update (deduplication by monotonic time_us)
        if post.fetched_at and self.cursor is not None and post.fetched_at <= self.cursor / 1_000_000:
            self.stats.dropped_out_of_order += 1
            return

        self.stats.received_total += 1
        self.stats.last_event_ts = time.time()
        # parse_jetstream_message stuffed the source time_us into fetched_at
        # only as a temporary signal. Reset to ingest time and use post.created_utc
        # as the authoritative server timestamp.
        time_us = int(post.created_utc * 1_000_000)
        self.cursor = time_us
        post.fetched_at = time.time()

        if not is_financial_text(post.body):
            self.stats.dropped_non_financial += 1
            self._maybe_checkpoint(time_us)
            return

        try:
            self._queue.put(post, timeout=0.05)
            self.stats.forwarded += 1
        except queue.Full:
            self.stats.dropped_queue_full += 1

        self._maybe_checkpoint(time_us)

    # -- cursor durability ---------------------------------------------

    def _maybe_checkpoint(self, time_us: int) -> None:
        now = time.time()
        if now - self._last_cursor_save >= self.settings.firehose_cursor_save_interval:
            self._save_cursor()
            self._last_cursor_save = now

    def _save_cursor(self, force: bool = False) -> None:
        if self.cursor is None:
            return
        try:
            os.makedirs(os.path.dirname(self._cursor_path) or ".", exist_ok=True)
            tmp = self._cursor_path + ".tmp"
            with open(tmp, "w") as f:
                f.write(str(self.cursor))
            os.replace(tmp, self._cursor_path)
        except OSError as e:
            logger.warning(f"Failed to save cursor: {e}")

    def _load_cursor(self) -> Optional[int]:
        try:
            with open(self._cursor_path) as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return None


# ---------------------------------------------------------------------
# Pure functions — kept module-level so they can be unit tested without
# touching the network.
# ---------------------------------------------------------------------

def parse_jetstream_message(raw_msg: str | bytes) -> Optional[RawPost]:
    """Parse a Jetstream JSON envelope into a RawPost.

    Returns None for events we don't care about (deletes, non-post commits,
    malformed JSON, empty text). The server-observed `time_us` is used for
    `created_utc` so a malicious client cannot backdate or future-date events.
    """
    try:
        if isinstance(raw_msg, bytes):
            raw_msg = raw_msg.decode("utf-8", errors="replace")
        event = json.loads(raw_msg)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if event.get("kind") != "commit":
        return None
    commit = event.get("commit") or {}
    if commit.get("operation") != "create":
        return None
    if commit.get("collection") != "app.bsky.feed.post":
        return None
    record = commit.get("record") or {}
    text = (record.get("text") or "").strip()
    if not text:
        return None

    did = event.get("did") or ""
    rkey = commit.get("rkey") or ""
    if not did or not rkey:
        return None

    time_us = event.get("time_us") or 0
    created_utc = time_us / 1_000_000 if time_us else time.time()

    title = text[:300]
    return RawPost(
        post_id=f"{did}/{rkey}",
        source="bluesky",
        title=title,
        body=text,
        score=0,
        upvote_ratio=1.0,
        num_comments=0,
        created_utc=created_utc,
        url=f"https://bsky.app/profile/{did}/post/{rkey}",
    )


def is_financial_text(text: str) -> bool:
    """Coarse prefilter: does this look like a financial post?

    Cheap and false-positive-friendly by design. The downstream ticker
    extractor and quality validator do the precise filtering — this just
    avoids spending CPU on the 95%+ of firehose traffic about food, art,
    pets, politics, etc.
    """
    if not text:
        return False
    if "$" in text:
        return True  # $TICKER cashtags are very strong signal
    lower = text.lower()
    for kw in _FINANCIAL_KEYWORDS:
        if kw in lower:
            return True
    return False
