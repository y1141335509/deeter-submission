# Design Notes

## Problem framing

The objective is to turn high-volume, noisy social text into a structured,
trustworthy signal that ML models can train on. The challenge is not just
ingestion — it's that raw social data is messy (deleted posts, spam, non-financial
content, duplicate submissions, deceptive timestamps), and a model trained on
corrupt inputs will learn the wrong patterns. Data quality is as important as
throughput.

## Project history: Reddit (v1) → Bluesky firehose (v2)

The first commit of this project ingested Reddit via the PRAW library. PRAW is
convenient — `subreddit.stream.submissions()` yields posts in a `for` loop —
but it hides the entire connection layer. The code didn't show any reasoning
about reconnects, backpressure, sequence gaps, cursor durability, or
resumability across restarts, because PRAW handled all of those invisibly.

For a role explicitly framed around "real-time systems" and "ingestion
pipelines from external providers", that opacity was the wrong signal.

The pivot to Bluesky's Jetstream firehose was driven by three concerns:

1. **Real WebSocket handling.** Jetstream is a public WebSocket, no SDK in
   between, so the code now contains the actual connection lifecycle:
   reconnect with exponential backoff, host rotation across regions, cursor
   persistence, gap detection. These are the questions a senior engineer
   would ask in an interview, and they're now visible in code.

2. **Real distribution of inputs.** v1's demo mode used a fixed pool of 20
   templates. The DuckDB analysis of v1's output revealed a cute artefact —
   `LOW` and `QQQ` had identical mention counts (4352 each) because they were
   always co-extracted from the same template "Rate cut expectations pushing
   QQQ higher". This was symptomatic of two real problems: the demo
   distribution was unrealistically narrow, and the ticker extractor had a
   case-folding bug (`text.upper()` was matching English `"low"` against the
   `LOW` ticker). v2 fixes both — Bluesky text is real human writing, and the
   extractor only matches bare-word tickers that are uppercase in the source.

3. **Volume.** Reddit's submission stream is paced by user posting frequency
   (a few per minute across the financial subreddits). Bluesky's firehose
   averages 50–200 events/sec across the entire network. The pipeline
   doesn't need that volume to be useful, but having it forces real
   decisions about backpressure that are missing from any low-volume
   pipeline.

The Reddit version was kept in git history rather than rewritten. The diff
between v1 and v2 is itself part of the submission — it shows iteration
under a constraint (better demonstration of streaming infrastructure)
rather than ground-up rewriting.

## Architecture decisions

### Two output tables instead of one

Raw posts and per-ticker mentions are written as separate Parquet tables.

The posts table preserves full context (title, body, quality metadata). The
mentions table is a pre-exploded join: one row per (post, ticker) pair,
making it fast to query "all NVDA mentions in the last 6 hours" without
scanning posts and filtering.

A model that needs per-ticker time-series sentiment reads the mentions
table. A model that needs full text reads the posts table. No join required
at training time.

### Bounded queue with drop-on-full, not unbounded buffering

The firehose runs in a background thread on its own asyncio loop and pushes
parsed posts into a `queue.Queue(maxsize=N)`. The main pipeline thread
consumes from this queue.

Three options were on the table:

- **Unbounded buffer**: simple, but a downstream stall (e.g. S3 outage) would
  cause memory to grow without bound and eventually OOM.
- **Block on full queue**: applies backpressure to the WebSocket reader, but
  Jetstream will eventually disconnect a client that doesn't read fast
  enough. Worse, a slow downstream becomes a connection problem rather than
  a metric.
- **Drop on full queue with counters** (chosen): the system stays connected
  and stable; the operator can see exactly how often the pipeline is over
  capacity via `dropped_queue_full`. Drops are explicit data loss, but
  they're observable and bounded — much easier to debug than memory exhaustion
  or mysterious disconnects.

### Server timestamps over client timestamps

Jetstream events carry both `time_us` (server-observed) and `record.createdAt`
(client-supplied). The pipeline uses `time_us` as `created_utc`. A malicious
or buggy client can put any value in `createdAt`, including the future or far
past; relying on it would mean training data could be poisoned by anyone with
a Bluesky account.

### Cursor persistence to local disk, not S3

The firehose cursor (a microsecond timestamp) is written every 10 seconds to
a local file mounted as a Docker volume. Alternatives considered:

- **S3 cursor file**: durable across container loss, but S3 latency is 20–50ms
  per write, so 10s frequency means ~0.5% of pipeline write traffic is just
  cursor updates, and an S3 outage would block the firehose loop.
- **Redis / etcd**: external dependency just for one integer.
- **Local file** (chosen): atomic write via `os.replace`, sub-millisecond,
  durable across pod restarts as long as the volume mount persists. For
  cross-host failover we'd move it to S3, but at single-host scale this is
  enough.

### Financial-relevance prefilter at ingestion

A keyword/cashtag-based prefilter runs immediately after parsing, before
sentiment scoring. The overwhelming majority of Bluesky posts (~90% in the
live run) are not about finance, and
running VADER + ticker regex on every post would waste CPU.

This is deliberately a coarse, false-positive-friendly filter. The downstream
ticker extractor and quality validator do precise filtering. Doing the cheap
filter early keeps the per-event cost low enough that the pipeline can keep
up with the firehose on a single core.

### Parquet + Snappy over JSON

Parquet was chosen for the same reasons as v1: columnar reads, ~3x compression
vs JSON, and the explicit schema fails loudly on type mismatch rather than
allowing corrupt records through silently.

### Time-based partitioning over ticker-based

S3 key structure: `posts/year=YYYY/month=MM/day=DD/hour=HH/batch_*.parquet`

Time-based partitioning fits the write pattern (append-only, time-ordered)
and produces manageable file counts. Ticker-based partitioning would be
ideal for single-ticker queries but creates thousands of small files and
complicates writes (one batch touches many partitions). Downstream query
tools (Athena, DuckDB, Spark) can filter by ticker using Parquet column
statistics without scanning every partition — and the pre-exploded mentions
table makes per-ticker scans cheap regardless.

### Sliding-window deduplication, in memory

The dedup layer uses an in-memory ordered dict keyed by `post_id` with a
1-hour TTL. The main reason dedup matters here is that the firehose can
re-deliver events on reconnect (cursor resume can replay a few seconds of
overlap). Persistent dedup state (Redis) would survive restarts, but the
worst case at restart is re-processing a small window of recent events,
which is harmless because S3 writes use deterministic keys (`post_id`) and
downstream consumers can dedup on read.

### VADER over FinBERT

VADER is rule-based, runs in <1ms per post, has no model download, and was
designed for social-media text. FinBERT is more accurate on formal financial
news but adds 50ms per post on CPU and a 400MB model download.

The sentiment scorer is isolated in `src/processing/sentiment.py`. Swapping
to FinBERT requires changing one function — the rest of the pipeline doesn't
care.

### Stateless workers (mostly)

The pipeline holds three pieces of state:

- the dedup window (in-memory, 1-hour TTL)
- the signal aggregator (in-memory, 24-hour TTL)
- the firehose cursor (durable on disk)

Everything else lives in S3. Restarts are cheap, and multiple instances can
in principle run in parallel against partitioned data. The firehose cursor is
the only piece that requires careful handling under restart.

## Empirical validation: design vs. measurement

The architectural choices above were made before the system ran live. After a
14-minute sustained run against the Jetstream firehose (35,545 raw events,
3,700 posts written), here's how each choice held up:

**The bounded queue did its job.** `queue_full = 0` for the entire run — the
downstream pipeline kept up with the ~43 events/sec firehose rate even after
financial filtering. The queue exists for the case where downstream stalls
(an S3 outage, a slow VADER cold-start). It didn't fire here, but the
mechanism is observable and tested via `dropped_queue_full` counter, so we
know it's wired up.

**The financial prefilter is more permissive than I designed for.** I expected
1–5% pass-through; actual is **10.3%** (3,650 / 35,545). Short keywords
(`rate`, `bull`, `bear`, `long`, `short`) match inside unrelated words
(`underrate`, `bullshit`, `bear hug`, `belong`). This is acceptable for a
coarse early filter — the downstream ticker extractor and quality validator
filter precisely. But it's also a real finding: at higher firehose volume the
extra CPU spent on these false-positive matches would matter. Tightening
would mean either word-boundary matching (`\brate\b`) or moving from keyword
match to a tiny classifier.

**Ticker density on Bluesky is much lower than expected.** Of the 3,700
financially-relevant posts, only ~1.2% mention a specific ticker (50
mentions across 44 posts). On Reddit's r/wallstreetbets the equivalent rate
would likely be 30–50%. This is the most important finding from the live
run, and it's an observation about the source, not the system: Bluesky's
financial culture differs from Reddit's. The right architectural response
is **add a second source** rather than tune the filter — and the
`IngestionSource` Protocol in `pipeline.py` makes that a single-file
addition (`src/ingestion/<new_source>.py` implementing `start/stop/stream`).

**Server timestamps work as intended.** No anomalies, no out-of-order events
seen during the run. The `cursor` (driven by `time_us`) is monotonic in
practice for a single connection.

**Cursor-on-disk works end-to-end, including backfill on resume.** Verified
manually by `docker compose stop pipeline && sleep 5 && docker compose start pipeline`:

```text
21:44:23 [firehose] received=62542 ... rate=43.59/s        ← steady state
21:44:35 INFO  Resuming firehose from cursor=1777671863200482
21:44:36 INFO  Connected: ... cursor=1777671863200482
21:44:38 [firehose] received=615 forwarded=50 rate=199.91/s   ← catch-up burst
21:45:05 [firehose] received=1696 ... rate=55.82/s             ← back to live
```

The cursor was loaded from disk on startup, the WebSocket was reopened with
`cursor=...` in the URL, and Jetstream replayed the events that occurred
during the 5-second downtime — the post-resume `rate=199.91/s` is ~5×
steady-state, which is the catch-up burst. This means a brief pipeline
restart loses no data; the only window of true loss is when the cursor
hasn't been written yet (default: every 10s of activity).

**VADER + regex per-post latency is well under target.** p50 around 0.36 ms,
p99 around 2.8 ms steady-state — comfortably below the 5 ms / 20 ms targets.
Cold-start outliers (first ~30 s) pushed p99 briefly to ~8 ms; once the JIT
caches warmed up, p99 settled.

**The reconnect/backoff/host-rotation logic was not tested in production.**
`reconnects = 0` over 14 minutes. The code is unit-tested at the parsing
level and exercised manually via a smoke script during development, but the
reconnect path itself has not run against a real network failure. This is
a real gap.

## What would change at 100x scale

**Volume.** A single Python process keeping up with 100×Jetstream is
unrealistic. The firehose client would split: a thin reader writing raw
events to a Kafka topic at line rate, and a fleet of consumers doing
parsing / sentiment / writes in parallel. Cursor management moves from
file → Kafka offsets.

**Deduplication.** In-memory dedup → Redis with TTL'd sets, shared across
worker pool.

**Writes.** Per-hour Parquet files would accumulate small files quickly. A
compaction job (Glue, Spark) would merge these into 128–512 MB files for
efficient querying. Iceberg would replace raw Parquet for snapshot isolation
and schema evolution.

**Sentiment.** VADER stays cheap to scale horizontally. FinBERT, if needed,
moves to a GPU pool with batched inference.

**Quality.** The current rule-based validator gets augmented with anomaly
detection on posting patterns (coordinated bot activity, sudden mention
spikes from new accounts, duplicate text across many accounts).

## What was deliberately not built

- **Orchestration / scheduling.** This is a continuous stream, not a batch
  job. Airflow would add complexity for no benefit.
- **Schema evolution tooling.** Parquet schema changes would require a
  migration strategy (column defaults, backward-compatible adds, dual writes).
  Real concern at scale, deferred here.
- **Authentication / secret management.** Credentials via env vars; in
  production these come from Secrets Manager / Vault.
- **Backfill from historical data.** Jetstream has a cursor-based replay,
  but a true backfill (e.g. last 30 days) would require reading from
  Bluesky's relay servers and is out of scope.
- **Cross-region failover.** The cursor is local; cross-host failover would
  require S3-backed cursor and a leader-election layer.
