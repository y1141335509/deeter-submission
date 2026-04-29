# Social Signal Pipeline

A real-time data pipeline that ingests financial Reddit discussions, extracts per-ticker sentiment signals, validates data quality, and writes ML-ready Parquet records to S3-compatible storage.

## Why this exists

Markets move on narratives. Before a price moves, a story forms — on forums, in comment sections, across social feeds. This pipeline captures that signal at the source: ingesting Reddit posts from high-signal financial communities, scoring sentiment per stock ticker, and writing clean, structured data to object storage where models can consume it.

The goal is not just to move data, but to make the data trustworthy. A model trained on corrupt or inconsistent inputs learns the wrong things. Every layer here — deduplication, schema validation, quality scoring — exists to ensure what lands in S3 is actually usable.

## Architecture

```
Reddit API (PRAW)
      │
      ▼
 Ingestion Layer           async stream from r/wallstreetbets, r/investing, r/stocks
      │
      ▼
 Deduplication             time-bounded sliding window by post_id (1hr TTL)
      │
      ▼
 Processing Layer          VADER sentiment scoring + regex ticker extraction
      │
      ▼
 Quality Layer             schema validation, field checks, quality score (0–1)
      │
      ▼
 Signal Aggregator         rolling sentiment windows per ticker (5m / 1h / 24h)
      │
      ▼
 S3 Writer                 batched Parquet writes, Snappy-compressed
      │
      ├── posts/year=.../month=.../day=.../hour=.../batch_*.parquet
      └── mentions/year=.../month=.../day=.../hour=.../batch_*.parquet
```

Two output tables:
- **posts** — one row per Reddit post, full text + sentiment + quality metadata
- **mentions** — one row per (post, ticker) pair — optimised for per-ticker ML queries

## Quick start

No Reddit credentials needed to run. Demo mode generates realistic synthetic posts.

```bash
# 1. Clone and configure
cp .env.example .env
# DEMO_MODE=true is the default — no changes needed to run

# 2. Start
docker compose up --build

# 3. Watch the pipeline run
# MinIO console: http://localhost:9001  (minioadmin / minioadmin)
# Browse your data at: s3://social-data/posts/ and s3://social-data/mentions/
```

**With real Reddit data:**
```bash
# Create a Reddit app at https://www.reddit.com/prefs/apps (type: script)
# Edit .env:
REDDIT_CLIENT_ID=your_id
REDDIT_CLIENT_SECRET=your_secret
DEMO_MODE=false

docker compose up --build
```

## Running tests

```bash
pip install -r requirements.txt
pip install pytest
pytest tests/ -v
```

## Success criteria

Measured in demo mode (`DEMO_PPM=120`) on Apple M-series, Docker on MinIO, 200 posts processed.

| Metric | Target | Measured | Notes |
|---|---|---|---|
| Processing latency p50 | < 5ms | **0.44ms** | Per-post VADER + ticker extraction |
| Processing latency p99 | < 20ms | **3.82ms** | |
| Write latency (batch of 50) | < 500ms | **~8ms avg** | Parquet+Snappy serialize + MinIO PUT |
| Throughput (demo mode) | ≥ 120 posts/min | **~112/min** | ~7% dupes filtered by dedup |
| Quality pass rate | ≥ 90% | **100%** | Synthetic posts pass all field checks |
| Dedup correctness | 100% | **100%** | No duplicate post_id written |
| Cold start to first write | < 2 min | **28.7s** | `docker compose up --build` → data in S3 |

Metrics are logged every flush cycle. Run `docker compose logs -f pipeline` to observe live.

## Data schema

### posts table
| Field | Type | Description |
|---|---|---|
| post_id | string | Reddit post ID (primary key) |
| subreddit | string | Source community |
| title | string | Post title |
| body | string | Post body text |
| score | int32 | Reddit upvote score |
| upvote_ratio | float32 | Ratio of upvotes to total votes |
| num_comments | int32 | Comment count at time of ingestion |
| created_utc | float64 | Post creation timestamp |
| sentiment_compound | float32 | VADER compound score, -1.0 to +1.0 |
| sentiment_positive | float32 | VADER positive component |
| sentiment_negative | float32 | VADER negative component |
| sentiment_neutral | float32 | VADER neutral component |
| tickers | list[string] | Stock tickers mentioned (e.g. ["NVDA", "AMD"]) |
| quality_score | float32 | Data quality score, 0.0 to 1.0 |
| fetched_at | float64 | Pipeline ingest timestamp |
| processed_at | float64 | Processing completion timestamp |

### mentions table
| Field | Type | Description |
|---|---|---|
| post_id | string | Source post |
| ticker | string | Stock ticker |
| subreddit | string | Source community |
| sentiment_compound | float32 | VADER compound score |
| score | int32 | Post score at time of ingestion |
| created_utc | float64 | Post creation time |

The mentions table is the primary training input: for each ticker, you get a timestamped stream of sentiment events with associated social signal (score, subreddit).

## Project structure

```
├── config/
│   ├── settings.py        environment-based configuration
│   └── tickers.py         ticker universe (~150 tickers) + blacklist
├── src/
│   ├── ingestion/
│   │   └── reddit_poller.py    live stream + demo mode
│   ├── models/
│   │   └── post.py             RawPost, ProcessedPost, SentimentScores dataclasses
│   ├── processing/
│   │   ├── sentiment.py        VADER scoring
│   │   └── ticker_extractor.py regex-based ticker extraction
│   ├── quality/
│   │   ├── validator.py        per-post quality checks + scoring
│   │   └── dedup.py            time-bounded sliding window deduplication
│   ├── signals/
│   │   └── aggregator.py       rolling per-ticker sentiment windows
│   ├── storage/
│   │   └── s3_writer.py        batched Parquet writes to S3/MinIO
│   └── pipeline.py             orchestration + metrics
├── tests/                      unit tests for all core modules
├── docs/design.md              architecture decisions and tradeoffs
├── docker-compose.yml          MinIO + pipeline, one-command startup
└── main.py                     entrypoint
```

## Configuration

All configuration via environment variables (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| DEMO_MODE | false | Generate synthetic posts instead of hitting Reddit |
| DEMO_PPM | 120 | Posts per minute in demo mode |
| SUBREDDITS | wallstreetbets,investing,stocks | Subreddits to stream |
| BATCH_SIZE | 50 | Posts per S3 write |
| BATCH_TIMEOUT | 30 | Max seconds between writes |
| S3_ENDPOINT | http://minio:9000 | S3-compatible endpoint |
| S3_BUCKET | social-data | Target bucket |

## Design decisions

See [docs/design.md](docs/design.md) for the full rationale behind architecture choices, tradeoffs made, and what would change at higher scale.
