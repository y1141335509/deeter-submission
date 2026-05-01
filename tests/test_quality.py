import time
from src.models.post import ProcessedPost
from src.quality.validator import validate
from src.quality.dedup import Deduplicator


def _make_post(**overrides) -> ProcessedPost:
    defaults = dict(
        post_id="abc123",
        source="bluesky",
        title="NVDA to the moon — buying calls",
        body="Strong earnings, AI demand unstoppable",
        score=1500,
        upvote_ratio=0.92,
        num_comments=230,
        created_utc=time.time(),
        url="https://bsky.app/profile/example/post/abc123",
        fetched_at=time.time(),
        sentiment_compound=0.65,
        sentiment_positive=0.4,
        sentiment_negative=0.05,
        sentiment_neutral=0.55,
        tickers=["NVDA"],
        quality_score=0.0,
    )
    defaults.update(overrides)
    return ProcessedPost(**defaults)


class TestValidator:
    def test_valid_post_passes(self):
        report = validate(_make_post())
        assert report.is_valid is True
        assert report.quality_score > 0.9
        assert report.issues == []

    def test_removed_content_fails(self):
        report = validate(_make_post(body="[removed]"))
        assert report.is_valid is False

    def test_deleted_content_fails(self):
        report = validate(_make_post(body="[deleted]"))
        assert report.is_valid is False

    def test_missing_post_id_fails(self):
        report = validate(_make_post(post_id=""))
        assert report.is_valid is False

    def test_short_title_penalised(self):
        report = validate(_make_post(title="Hi"))
        assert report.is_valid is True
        assert report.quality_score < 1.0
        assert any("title" in issue for issue in report.issues)

    def test_invalid_upvote_ratio_penalised(self):
        report = validate(_make_post(upvote_ratio=1.5))
        assert any("upvote_ratio" in issue for issue in report.issues)

    def test_out_of_range_sentiment_penalised(self):
        report = validate(_make_post(sentiment_compound=2.5))
        assert any("sentiment_compound" in issue for issue in report.issues)


class TestDeduplicator:
    def test_new_post_not_duplicate(self):
        d = Deduplicator()
        assert d.is_duplicate("post_1") is False

    def test_seen_post_is_duplicate(self):
        d = Deduplicator()
        d.is_duplicate("post_1")
        assert d.is_duplicate("post_1") is True

    def test_different_posts_not_duplicate(self):
        d = Deduplicator()
        d.is_duplicate("post_1")
        assert d.is_duplicate("post_2") is False

    def test_evicts_expired_entries(self):
        d = Deduplicator(window_seconds=1)
        d.is_duplicate("old_post")
        assert d.size == 1
        time.sleep(1.1)
        d.is_duplicate("trigger_eviction")
        assert d.size == 1  # only the new one remains

    def test_size_tracks_correctly(self):
        d = Deduplicator()
        for i in range(5):
            d.is_duplicate(f"post_{i}")
        assert d.size == 5
