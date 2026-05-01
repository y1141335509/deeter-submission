import os
from dataclasses import dataclass, field


@dataclass
class Settings:
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

    # Demo mode — generates synthetic posts instead of connecting to Bluesky.
    # Useful for offline development, CI, and exercising the pipeline without
    # an internet connection.
    demo_mode: bool = field(default_factory=lambda: os.getenv("DEMO_MODE", "false").lower() == "true")
    demo_posts_per_minute: int = field(default_factory=lambda: int(os.getenv("DEMO_PPM", "120")))

    # Bluesky firehose — Jetstream is a public, unauthenticated WebSocket.
    firehose_queue_size: int = field(default_factory=lambda: int(os.getenv("FIREHOSE_QUEUE_SIZE", "2000")))
    firehose_cursor_path: str = field(default_factory=lambda: os.getenv("FIREHOSE_CURSOR_PATH", "/var/lib/pipeline/cursor"))
    firehose_cursor_save_interval: float = field(default_factory=lambda: float(os.getenv("FIREHOSE_CURSOR_SAVE_INTERVAL", "10")))
