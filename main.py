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
    if settings.demo_mode:
        logging.getLogger().info("Running in DEMO MODE — no Reddit credentials required")
    else:
        if not settings.reddit_client_id or not settings.reddit_client_secret:
            print("ERROR: Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET, or set DEMO_MODE=true")
            sys.exit(1)

    pipeline = Pipeline(settings)
    pipeline.run()


if __name__ == "__main__":
    main()
