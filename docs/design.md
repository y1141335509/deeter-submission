# Design Notes

## Problem framing

The objective is to turn high-volume, noisy social text into a structured, trustworthy signal that ML models can train on. The challenge is not just ingestion — it's that raw social data is messy (deleted posts, spam, non-financial content, duplicate submissions), and a model trained on corrupt inputs will learn the wrong patterns. Data quality is as important as throughput.

## Architecture decisions

### Two output tables instead of one

Raw posts and per-ticker mentions are written as separate Parquet tables.

The posts table preserves full context (title, body, quality metadata). The mentions table is a pre-exploded join: one row per (post, ticker) pair, making it fast to query "all NVDA mentions in the last 6 hours" without scanning posts and filtering.

A model that needs per-ticker time-series sentiment reads the mentions table. A model that needs full text reads the posts table. No join required at training time.

### Parquet + Snappy over JSON

Options considered: raw JSON to S3, NDJSON, CSV, Parquet.

Parquet was chosen because:
- **Columnar reads**: training jobs typically read sentiment_compound + created_utc for a specific ticker, not full rows. Parquet makes this 10–100x faster than row-based formats.
- **Snappy compression**: ~3x size reduction vs JSON at minimal CPU cost.
- **Explicit schema**: the schema is enforced at write time (pyarrow), so corrupt or type-mismatched records fail loudly rather than silently passing through.

### Time-based partitioning over ticker-based

S3 key structure: `posts/year=YYYY/month=MM/day=DD/hour=HH/batch_*.parquet`

Alternative considered: partition by ticker (e.g. `mentions/ticker=NVDA/...`).

Ticker-based partitioning would be ideal for single-ticker queries but creates thousands of small files and complicates writes (one batch touches many partitions). Time-based partitioning fits the write pattern (append-only, roughly time-ordered) and keeps file sizes manageable. Downstream query tools (Athena, Spark) can filter by ticker using Parquet column statistics without scanning every partition.

### Sliding window deduplication over persistent state

Reddit's streaming API occasionally re-delivers posts. Deduplication uses an in-memory ordered dict keyed by post_id, with entries evicted after 1 hour.

A Redis-backed set would survive restarts, but adds an external dependency and operational complexity. For a 1-hour window the memory footprint is bounded (~100MB worst case at extreme post volume). On restart, the worst case is re-processing a small number of posts from the last hour — acceptable because S3 writes are idempotent by design (post_id is a natural key and downstream consumers can dedup on read).

### Batch writes over per-record writes

S3 PUT requests have fixed latency overhead (~20–50ms). Writing 50 posts per batch rather than 50 individual PUTs reduces S3 request cost by 50x and keeps write latency from dominating end-to-end processing time.

Batch timeout of 30 seconds ensures data lands in S3 promptly even during low-volume periods.

### VADER over FinBERT

VADER is a rule-based sentiment analyzer optimized for social media text. FinBERT is a BERT variant fine-tuned on financial news.

VADER was chosen for this implementation because:
- **Latency**: VADER runs in <1ms per post. FinBERT requires ~50ms on CPU (or a GPU).
- **No model download at startup**: FinBERT requires downloading a 400MB model, which complicates Docker builds and cold starts.
- **Good enough for social text**: VADER was designed for social media language (slang, caps, emojis), which is exactly what WSB posts contain.

The sentiment scorer is isolated in `src/processing/sentiment.py` with a clean interface. Swapping to FinBERT requires changing one function.

### Stateless pipeline workers

The pipeline holds no state except the dedup window and signal aggregator. All durable state goes to S3. This means multiple instances can run in parallel (against different subreddits or time ranges) without coordination, and restarts are cheap.

The signal aggregator is in-memory because it's a read-optimized cache of recent data — the source of truth is always S3.

## What would change at 100x scale

**Volume**: At high volume, PRAW's single-stream approach becomes a bottleneck. The ingestion layer would need to be parallelized across subreddits with a Kafka topic as the intermediate buffer. Multiple consumer workers would process posts concurrently.

**Deduplication**: The in-memory dedup would move to Redis with TTL-keyed sets, shared across workers.

**Writes**: Per-hour Parquet files would accumulate quickly. A compaction job (e.g. Spark or Glue) would merge small files into larger ones to keep query performance high.

**Sentiment**: At scale, VADER can be parallelized cheaply. If accuracy becomes the bottleneck, FinBERT inference would move to a GPU worker pool with batched inference (32–64 posts per forward pass).

**Quality**: The current rule-based validator would be augmented with anomaly detection on posting patterns (e.g. coordinated spam bursts from new accounts).

## What was deliberately not built

- **Orchestration / scheduling**: The pipeline is a continuous stream, not a batch job. A scheduler like Airflow would add complexity with no benefit here.
- **Schema evolution tooling**: Parquet schema changes require a migration strategy (e.g. column defaults, backward-compatible adds). This is a real operational concern at scale, deferred here.
- **Authentication / secret management**: Credentials are passed via environment variables. In production, these would come from AWS Secrets Manager or Vault.
