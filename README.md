# Social Signal Pipeline

A real-time data pipeline that ingests the public Bluesky firehose, prefilters
to financial discussion, scores per-ticker sentiment, validates data quality,
and writes ML-ready Parquet records to S3-compatible storage.

## Why this exists

Markets move on narratives. Before a price moves, a story forms — on forums, in
comment sections, across social feeds. This pipeline captures that signal at
the source: connecting to the live AT Protocol firehose, filtering for
financially relevant posts, scoring sentiment per stock ticker, and writing
clean, structured data to object storage where models can consume it.

The goal is not just to move data, but to make the data **trustworthy**. A model
trained on corrupt or inconsistent inputs learns the wrong things. Every layer
here — backpressure, deduplication, schema validation, quality scoring — exists
to ensure what lands in S3 is actually usable.

## Architecture

```
   Bluesky Jetstream WebSocket  (public, ~100–200 events/sec global firehose)
              │
              ▼
   Firehose client                async WebSocket, exponential reconnect,
   src/ingestion/bluesky_firehose  cursor checkpoint, host rotation
              │
              ▼
   Financial-relevance prefilter  cheap keyword/cashtag drop ~95% of volume
              │
              ▼
   Bounded queue (drop-on-full)   isolates network thread from pipeline,
                                  drops counted in metrics
              │
              ▼
   Deduplication                  time-bounded sliding window by post_id (1 hr TTL)
              │
              ▼
   Processing                     VADER sentiment + regex ticker extraction
              │
              ▼
   Quality                        schema validation, field range checks,
                                  0.0–1.0 quality score per record
              │
              ▼
   Signal aggregator              rolling per-ticker windows (5 m / 1 h / 24 h)
              │
              ▼
   S3 Writer                      batched Parquet writes, Snappy-compressed
              │
              ├── posts/year=.../month=.../day=.../hour=.../batch_*.parquet
              └── mentions/year=.../month=.../day=.../hour=.../batch_*.parquet
```

Two output tables:

- **posts** — one row per post, full text + sentiment + quality metadata
- **mentions** — one row per (post, ticker) pair — optimised for per-ticker ML queries

## Quick start

The default mode connects to the **live Bluesky Jetstream firehose** — public,
unauthenticated, no credentials needed.

```bash
cp .env.example .env
docker compose up --build

# MinIO console:  http://localhost:9001  (minioadmin / minioadmin)
# Browse data at: s3://social-data/posts/  and  s3://social-data/mentions/
```

For offline development or CI, set `DEMO_MODE=true` in `.env` — the pipeline
will skip the network and stream synthetic financial posts at `DEMO_PPM`
posts/min instead.

## Running tests

```bash
pip install -r requirements.txt pytest
pytest tests/ -v
```

56 tests cover sentiment scoring, ticker extraction (including the LOW/ARE
false-positive regression), validation, deduplication, signal aggregation, and
the Jetstream message parser.

## Design highlights

### Backpressure-aware ingestion

The Jetstream firehose pushes events as fast as the network allows. If the
downstream pipeline (validation + sentiment + S3) can't keep up, we have to
choose: block the WebSocket, or drop events. Blocking eventually causes the
server to disconnect us; unbounded buffering exhausts memory.

This pipeline uses a **bounded queue with drop-on-full**, surfaced as a metric
(`dropped_queue_full`). The system stays healthy under load and the operator
can see exactly when and how often the pipeline is over capacity.

### Resumable across restarts

The firehose client persists its cursor (Jetstream's `time_us` watermark) to
disk every 10 seconds. On restart the connection resumes from the last saved
position rather than tailing live, so a brief pipeline crash doesn't lose
data. Out-of-order events (cursor going backwards) are dropped explicitly.

### Connection lifecycle

The WebSocket client handles dropped connections with exponential backoff
(capped at 60 s) and rotates between Jetstream's four geographic hosts on
reconnect, so a single regional outage doesn't take the pipeline down.

### Data quality is enforced, not assumed

Every post goes through a validator that checks for hard failures
(missing ID, removed/deleted content) and soft penalties (short title,
out-of-range fields, suspicious sentiment scores). Records below a quality
threshold are dropped before reaching S3. The quality score itself is
written into the Parquet table so downstream consumers can re-filter.

### Server timestamp, not client

`created_utc` is taken from the Jetstream-observed `time_us`, not from the
post's self-reported `createdAt`. Clients can backdate their own
`createdAt` arbitrarily; the server timestamp is tamper-resistant.

## Success criteria

Measured on Apple M-series, Docker on local MinIO. **Demo mode** numbers
exercise the pipeline without network variability; **live mode** numbers are
from a 14-minute sustained run against the Bluesky Jetstream firehose
(35,545 raw events received, 3,700 posts written).

| Metric | Target | Demo mode | Live (Jetstream) |
|---|---|---|---|
| Processing latency p50 | < 5 ms | 0.44 ms | **0.34–0.39 ms** |
| Processing latency p99 | < 20 ms | 3.82 ms | **2.3–8 ms** (most batches < 3 ms) |
| Forwarded throughput | — | 113 / min | **264–300 / min** |
| Firehose ingest rate | — | n/a | **~42.9 events/sec** |
| Financial-filter pass rate | — | n/a | **~10.3% (3,650 / 35,545)** |
| Quality pass rate | ≥ 90% | 100% (clean templates) | **100%** |
| Reconnects | 0 | n/a | **0** (over 14 min) |
| Queue-full drops | 0 | n/a | **0** |
| Feed lag | < 1 s | n/a | **0.01–0.04 s** |
| Cold start to first write | < 2 min | 28.7 s | **~30 s** |

A few things worth noting from these numbers:

- **Bluesky has much lower ticker density than Reddit's r/wallstreetbets.** Of
  3,700 posts that pass the financial keyword filter, only ~1.2% mention a
  specific stock ticker (50 mentions across 44 posts, 26 distinct tickers in
  15 minutes of wall-clock data). The pipeline correctly captures the signal
  that exists, but Bluesky simply has fewer "$NVDA"-style posts than the
  financial-Reddit equivalent. This is honest empirical data, not a system
  limitation — if the model trainer needs higher ticker volume, the answer is
  to add a second source (Reddit, StockTwits) rather than tune the filter.
- **The keyword prefilter is intentionally permissive.** The 10% pass-through
  is higher than I expected — short keywords like `rate`, `bull`, `bear`
  match inside unrelated words (`underrate`, `bullshit`, `bear hug`). Doing
  precise filtering at this stage would risk dropping real signal; the
  downstream ticker extractor + quality validator do the cleanup.
- **Reconnects = 0 over 14 min is still anecdotal.** Longer runs will eventually hit
  drops; the `[firehose]` metric block will surface them when they happen.

The metrics block is logged on every flush, not only on shutdown:

```
[pipeline]  elapsed=225.1s ingested=1050 processed=1050 written=1050 dups=0 quality=100.0% throughput=279.9/min p50=0.39ms p99=8.17ms
[firehose]  received=9598 forwarded=1050 non_fin=8548 queue_full=0 reconnects=0 rate=42.58/s lag=0.01s
```

## Data schema

### posts table
| Field | Type | Description |
|---|---|---|
| post_id | string | `did/rkey` from AT Protocol (primary key) |
| source | string | Always `"bluesky"` in live mode, `"demo"` in demo mode |
| title | string | First 300 chars of post text (Bluesky has no separate title) |
| body | string | Full post text |
| score | int32 | 0 — Bluesky firehose does not include engagement counts |
| upvote_ratio | float32 | 1.0 — placeholder |
| num_comments | int32 | 0 — placeholder |
| created_utc | float64 | **Server-observed** Jetstream timestamp |
| sentiment_compound | float32 | VADER compound score, -1.0 to +1.0 |
| sentiment_positive | float32 | VADER positive component |
| sentiment_negative | float32 | VADER negative component |
| sentiment_neutral | float32 | VADER neutral component |
| tickers | list[string] | Stock tickers mentioned (e.g. ["NVDA", "AMD"]) |
| quality_score | float32 | Data quality score, 0.0 to 1.0 |
| fetched_at | float64 | Pipeline ingest timestamp |
| processed_at | float64 | Processing completion timestamp |

### mentions table
One row per (post, ticker) pair. This is the primary training input — for each
ticker, you get a timestamped stream of sentiment events with associated
metadata.

## Project history (a note on the git log)

The first version of this pipeline (commits `55ec1ed`, `b97229e`) ingested
Reddit via the PRAW library. It worked, but PRAW hides the entire connection
layer — there's no real WebSocket handling, no reconnection logic, no
backpressure, no cursor checkpointing visible in the code. Looking at the
result, you couldn't tell whether the author understood streaming
infrastructure or had just wired up someone else's library.

I rewrote the ingestion layer to consume the Bluesky Jetstream firehose
directly over WebSocket. This:

- Replaces a polling library with a real WebSocket connection — exposing all
  the reliability concerns (drops, backpressure, gap handling, cursor resume)
  in code I had to write.
- Switches from a small set of subreddits to the entire global AT Protocol
  network — drops the synthetic-template feel that was visible in v1's output
  (e.g. `LOW` and `QQQ` co-occurring with identical mention counts because
  they were extracted from the same demo template).
- Fixes a real ticker-extraction bug in v1 where `text.upper()` would turn
  English words like `"low"` and `"all"` into ticker matches (`LOW`, `ALL`).
  The new extractor only matches bare tickers that are already uppercase in
  the source text. Regression test added.

The Reddit version is preserved in git history and deliberately not squashed —
the diff itself is part of the submission. v1 was the right size to validate
the pipeline shape end-to-end; v2 is the version that exercises the things
this role actually cares about.

## Project structure

```
├── config/
│   ├── settings.py            environment-based configuration
│   └── tickers.py             ticker universe (~150 tickers) + blacklist
├── src/
│   ├── ingestion/
│   │   ├── bluesky_firehose.py    Jetstream WebSocket client + parser
│   │   └── demo_stream.py         synthetic post generator (offline)
│   ├── models/
│   │   └── post.py                RawPost / ProcessedPost / SentimentScores
│   ├── processing/
│   │   ├── sentiment.py           VADER scoring
│   │   └── ticker_extractor.py    regex-based ticker extraction
│   ├── quality/
│   │   ├── validator.py           per-post quality checks + scoring
│   │   └── dedup.py               sliding-window deduplication
│   ├── signals/
│   │   └── aggregator.py          rolling per-ticker sentiment windows
│   ├── storage/
│   │   └── s3_writer.py           batched Parquet writes to S3 / MinIO
│   └── pipeline.py                orchestration + metrics
├── tests/                          pytest unit tests (56 cases)
├── docs/design.md                  architecture decisions and tradeoffs
├── docker-compose.yml              MinIO + pipeline, one-command startup
└── main.py                         entrypoint
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DEMO_MODE` | `false` | If true, generate synthetic posts instead of connecting to Bluesky |
| `DEMO_PPM` | `120` | Posts per minute in demo mode |
| `BATCH_SIZE` | `50` | Posts per S3 write |
| `BATCH_TIMEOUT` | `30` | Max seconds between writes |
| `DEDUP_WINDOW` | `3600` | Dedup TTL in seconds |
| `FIREHOSE_QUEUE_SIZE` | `2000` | Bounded queue between firehose thread and pipeline |
| `FIREHOSE_CURSOR_PATH` | `/var/lib/pipeline/cursor` | Where to persist resume cursor |
| `FIREHOSE_CURSOR_SAVE_INTERVAL` | `10` | Seconds between cursor saves |
| `S3_ENDPOINT` | `http://minio:9000` | S3-compatible endpoint |
| `S3_BUCKET` | `social-data` | Target bucket |

## Design decisions

See [docs/design.md](docs/design.md) for the full rationale behind architecture
choices, tradeoffs made, what was deliberately left out, and what would change
at higher scale.
