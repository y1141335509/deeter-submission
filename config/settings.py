import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Settings:
    # Reddit credentials
    reddit_client_id: str = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_ID", ""))
    reddit_client_secret: str = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_SECRET", ""))
    reddit_user_agent: str = field(default_factory=lambda: os.getenv("REDDIT_USER_AGENT", "social-pipeline/1.0"))

    # S3 / MinIO
    s3_endpoint: str = field(default_factory=lambda: os.getenv("S3_ENDPOINT", "http://localhost:9000"))
    s3_access_key: str = field(default_factory=lambda: os.getenv("S3_ACCESS_KEY", "minioadmin"))
    s3_secret_key: str = field(default_factory=lambda: os.getenv("S3_SECRET_KEY", "minioadmin"))
    s3_bucket: str = field(default_factory=lambda: os.getenv("S3_BUCKET", "social-data"))
    s3_region: str = field(default_factory=lambda: os.getenv("S3_REGION", "us-east-1"))

    # Pipeline tuning
    batch_size: int = field(default_factory=lambda: int(os.getenv("BATCH_SIZE", "50")))
    batch_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("BATCH_TIMEOUT", "30")))
    dedup_window_seconds: int = field(default_factory=lambda: int(os.getenv("DEDUP_WINDOW", "3600")))

    # Demo / replay mode — runs without Reddit credentials
    demo_mode: bool = field(default_factory=lambda: os.getenv("DEMO_MODE", "false").lower() == "true")
    demo_posts_per_minute: int = field(default_factory=lambda: int(os.getenv("DEMO_PPM", "120")))

    # Subreddits to ingest
    subreddits: List[str] = field(default_factory=lambda: os.getenv(
        "SUBREDDITS", "wallstreetbets,investing,stocks"
    ).split(","))
