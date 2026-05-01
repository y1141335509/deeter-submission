import logging
import sys

from config.settings import Settings
from src.pipeline import Pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)


def main():
    settings = Settings()
    log = logging.getLogger()
    if settings.demo_mode:
        log.info("Running in DEMO MODE — synthetic posts, no network ingestion")
    else:
        log.info("Running in LIVE MODE — connecting to Bluesky Jetstream firehose")

    pipeline = Pipeline(settings)
    pipeline.run()


if __name__ == "__main__":
    main()
