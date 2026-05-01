"""Unit tests for the Bluesky firehose parser and prefilter.

Network and threading are not exercised here — only the pure functions that
turn a JSON envelope into a `RawPost`. The async/queue/reconnect machinery
is integration-tested by running the pipeline live.
"""

import json
import time

import pytest

from src.ingestion.bluesky_firehose import (
    is_financial_text,
    parse_jetstream_message,
)


def _commit_event(text: str, did="did:plc:abc", rkey="3kxyz", time_us=None):
    if time_us is None:
        time_us = int(time.time() * 1_000_000)
    return json.dumps({
        "did": did,
        "time_us": time_us,
        "kind": "commit",
        "commit": {
            "operation": "create",
            "collection": "app.bsky.feed.post",
            "rkey": rkey,
            "record": {
                "text": text,
                "createdAt": "2026-05-01T00:00:00Z",
            },
        },
    })


class TestParseJetstreamMessage:
    def test_valid_post_parses(self):
        msg = _commit_event("Going long $NVDA before earnings")
        post = parse_jetstream_message(msg)
        assert post is not None
        assert post.body == "Going long $NVDA before earnings"
        assert post.source == "bluesky"
        assert post.post_id.startswith("did:plc:abc/")
        assert post.url.startswith("https://bsky.app/")

    def test_uses_server_timestamp_not_client(self):
        # Client createdAt is far in the past but time_us is now.
        ts_us = int(time.time() * 1_000_000)
        msg = _commit_event("$SPY puts", time_us=ts_us)
        post = parse_jetstream_message(msg)
        assert abs(post.created_utc - ts_us / 1_000_000) < 1

    def test_delete_operation_skipped(self):
        msg = json.dumps({
            "did": "did:plc:abc",
            "time_us": 1,
            "kind": "commit",
            "commit": {
                "operation": "delete",
                "collection": "app.bsky.feed.post",
                "rkey": "x",
            },
        })
        assert parse_jetstream_message(msg) is None

    def test_non_post_collection_skipped(self):
        msg = json.dumps({
            "did": "did:plc:abc",
            "time_us": 1,
            "kind": "commit",
            "commit": {
                "operation": "create",
                "collection": "app.bsky.feed.like",
                "record": {"subject": "..."},
            },
        })
        assert parse_jetstream_message(msg) is None

    def test_account_event_skipped(self):
        msg = json.dumps({
            "did": "did:plc:abc",
            "time_us": 1,
            "kind": "account",
            "account": {"active": True},
        })
        assert parse_jetstream_message(msg) is None

    def test_empty_text_skipped(self):
        msg = _commit_event("")
        assert parse_jetstream_message(msg) is None

    def test_whitespace_only_text_skipped(self):
        msg = _commit_event("   \n  \t  ")
        assert parse_jetstream_message(msg) is None

    def test_malformed_json_returns_none(self):
        assert parse_jetstream_message("{not json") is None
        assert parse_jetstream_message("") is None

    def test_bytes_input_decoded(self):
        msg = _commit_event("$AAPL strong buy").encode("utf-8")
        post = parse_jetstream_message(msg)
        assert post is not None
        assert "$AAPL" in post.body

    def test_missing_did_or_rkey_skipped(self):
        # No rkey
        msg = json.dumps({
            "did": "did:plc:abc",
            "time_us": 1,
            "kind": "commit",
            "commit": {
                "operation": "create",
                "collection": "app.bsky.feed.post",
                "record": {"text": "hi"},
            },
        })
        assert parse_jetstream_message(msg) is None


class TestIsFinancial:
    @pytest.mark.parametrize("text", [
        "buying $TSLA calls",
        "I think the market is overheating",
        "huge bullish move on NVDA",
        "selling shares ahead of earnings",
        "Fed minutes drop tomorrow",
        "is this an etf or a fund?",
        "bitcoin breaking out again",
    ])
    def test_financial_kept(self, text):
        assert is_financial_text(text) is True

    @pytest.mark.parametrize("text", [
        "just had the best ramen of my life",
        "look at my dog 🐕",
        "anyone else watching the eclipse?",
        "new song dropped this morning",
    ])
    def test_non_financial_dropped(self, text):
        assert is_financial_text(text) is False

    def test_empty_dropped(self):
        assert is_financial_text("") is False
        assert is_financial_text(None) is False
