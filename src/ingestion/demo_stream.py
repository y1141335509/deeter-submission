"""Synthetic post generator for offline development and CI.

Generates ~realistic financial-discussion text without any network dependency.
Useful for running tests, debugging the downstream pipeline, or demoing the
system in environments where the live Bluesky firehose isn't reachable.

Not intended to model the real distribution of social posts — it's deliberately
narrow (only financial templates) so every generated post exercises the
sentiment + ticker + S3 path.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Generator

from config.settings import Settings
from src.models.post import RawPost

logger = logging.getLogger(__name__)


_DEMO_TEMPLATES = [
    ("$TSLA puts or calls ahead of earnings?",
     "Torn on TSLA this quarter. Revenue guidance was weak but Elon might surprise. Thoughts?"),
    ("NVDA is unstoppable — buying more on dip",
     "NVDA has a monopoly on AI training chips. Every datacenter is buying H100s. Long term hold."),
    ("Why I sold my $AAPL position today",
     "Cook's vision for AI feels late. Samsung and Google are catching up. Took profits after 40% run."),
    ("GME going parabolic again?",
     "Volume spiking on GME. Is this another gamma squeeze? DFV still around?"),
    ("SPY bearish divergence on daily chart",
     "RSI diverging from price action on SPY. Puts printing soon. Bears waking up."),
    ("$AMD vs $INTC — who wins the datacenter war?",
     "AMD has been taking market share from Intel consistently. EPYC chips are legit."),
    ("Rate cut expectations pushing QQQ higher",
     "Fed signaling dovish pivot. Tech stocks like NVDA and MSFT love a dovish Fed. QQQ to ATH?"),
    ("$COIN earnings play — is crypto season back?",
     "Bitcoin above 70k again. COIN should see massive trading volume this quarter."),
    ("META AI strategy — underrated or overhyped?",
     "Zuckerberg is spending $50B on AI infra. Either genius or burning money. Reality Labs still bleeding."),
    ("PLTR government contracts accelerating",
     "Palantir getting massive DoD contracts. AIP platform gaining traction. Long PLTR."),
    ("$MSTR Bitcoin proxy trade thesis",
     "If you believe in Bitcoin, MSTR is a leveraged play. Saylor keeps buying. 2x BTC exposure effectively."),
    ("Fed minutes — reading between the lines",
     "Two rate cuts priced in for 2025. SPY already at 540. Is this priced in? Feels frothy."),
    ("Selling covered calls on my $MSFT position",
     "MSFT at ATH. Selling 420 strike calls for premium. Copilot revenue not yet in numbers."),
    ("$RIVN delivery numbers huge disappointment",
     "RIVN missed Q3 deliveries by 20%. Supply chain issues again. Shorts covering or adding?"),
    ("Energy sector heating up — $XOM $CVX both breaking out",
     "Oil back above 90. XOM and CVX printing. War premium or genuine demand?"),
    ("$SOFI banking charter changing everything",
     "SOFI with banking charter now has 3.5% APY. Fintech convergence is real."),
    ("My 5-year YOLO on $VOO",
     "Stop picking stocks. Just buy VOO and chill. 99% of retail can't beat the index."),
    ("$TSLA FSD is actually working now",
     "Drove 200 miles on FSD 12 without an intervention. This changes the bull thesis."),
    ("Morning DD: $NVDA supply chain checks positive",
     "Channel checks show H200 allocation fully sold out through Q2. Blackwell on track."),
    ("$BA 737 MAX problems never ending",
     "Another quality control issue at Boeing. How many times? Short BA until leadership changes."),
]


class DemoStream:
    """Generates synthetic posts at a configurable rate.

    Conforms to the same start/stop/stream interface as `BlueskyFirehose`
    so the pipeline can swap between them transparently.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._stopped = False

    def start(self) -> None:
        logger.info(
            f"Demo stream starting at ~{self.settings.demo_posts_per_minute} posts/min"
        )

    def stop(self, timeout: float = 0.0) -> None:
        self._stopped = True

    def stream(self) -> Generator[RawPost, None, None]:
        interval = 60.0 / max(1, self.settings.demo_posts_per_minute)
        post_num = 0
        while not self._stopped:
            post_num += 1
            title, body = random.choice(_DEMO_TEMPLATES)
            # Occasionally emit a duplicate id to exercise the dedup layer
            post_id = (
                f"demo_{post_num}"
                if random.random() > 0.05
                else f"demo_{max(1, post_num - 1)}"
            )
            yield RawPost(
                post_id=post_id,
                source="demo",
                title=title,
                body=body,
                score=random.randint(-10, 5000),
                upvote_ratio=round(random.uniform(0.5, 1.0), 2),
                num_comments=random.randint(0, 800),
                created_utc=time.time(),
                url=f"https://bsky.app/demo/{post_id}",
            )
            time.sleep(interval)
