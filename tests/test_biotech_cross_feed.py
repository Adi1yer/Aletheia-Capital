"""Biotech cross-feed for stock pipeline."""

from src.biotech.cross_feed import build_cross_feed, cross_feed_prompt_snippet


def test_cross_feed_empty():
    assert cross_feed_prompt_snippet() == "" or "BIOTECH" in cross_feed_prompt_snippet()


def test_build_cross_feed():
    payload = build_cross_feed(weeks=1)
    assert "tickers" in payload
