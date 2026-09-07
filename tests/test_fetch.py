from datetime import datetime, timezone
from pathlib import Path

from happy_news import fetch

FIX = Path(__file__).parent / "fixtures"


def test_parse_feed_extracts_items():
    items = fetch.parse_feed((FIX / "feed_ok.xml").read_bytes(), "Example")
    assert len(items) == 2
    assert items[0].title == "Sea turtle nests hit a record"
    assert items[0].source == "Example"
    assert items[0].url.startswith("https://example.com/turtles")


def test_parse_feed_survives_garbage():
    assert fetch.parse_feed((FIX / "feed_malformed.xml").read_bytes(), "Broken") == []


def test_within_window_filters_by_age():
    items = fetch.parse_feed((FIX / "feed_ok.xml").read_bytes(), "Example")
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    assert len(fetch.within_window(items, 48, now)) == 1
    assert len(fetch.within_window(items, 24 * 21, now)) == 2


def test_fetch_all_reports_failures_without_raising(monkeypatch):
    def fake_get(url, timeout):
        if "bad" in url:
            raise OSError("unreachable")
        return (FIX / "feed_ok.xml").read_bytes()

    monkeypatch.setattr(fetch, "_get", fake_get)
    feeds = [
        {"name": "Good", "url": "https://good.example/rss"},
        {"name": "Bad", "url": "https://bad.example/rss"},
    ]
    items, failed = fetch.fetch_all(feeds)
    assert len(items) == 2
    assert failed == ["Bad"]
