import logging
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


def test_parse_feed_logs_undated_item_count(caplog):
    with caplog.at_level(logging.INFO, logger="happy_news.fetch"):
        items = fetch.parse_feed((FIX / "feed_undated.xml").read_bytes(), "Example")
    assert len(items) == 2
    undated = [i for i in items if i.published is None]
    assert len(undated) == 1
    assert undated[0].title == "A story with no date"
    matches = [
        record
        for record in caplog.records
        if "Example" in record.message and "1" in record.message and "date" in record.message.lower()
    ]
    assert matches, f"expected a log record reporting 1 undated item, got: {[r.message for r in caplog.records]}"


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


def test_fetch_all_survives_feed_missing_name(monkeypatch):
    def fake_get(url, timeout):
        return (FIX / "feed_ok.xml").read_bytes()

    monkeypatch.setattr(fetch, "_get", fake_get)
    feeds = [{"url": "https://noname.example/rss"}]
    items, failed = fetch.fetch_all(feeds)
    assert items == []
    assert len(failed) == 1


def test_fetch_all_survives_feed_missing_url(monkeypatch):
    def fake_get(url, timeout):
        raise AssertionError("_get should not be called when url is missing")

    monkeypatch.setattr(fetch, "_get", fake_get)
    feeds = [{"name": "NoUrl"}]
    items, failed = fetch.fetch_all(feeds)
    assert items == []
    assert failed == ["NoUrl"]


def test_fetch_all_survives_non_dict_entry(monkeypatch):
    def fake_get(url, timeout):
        return (FIX / "feed_ok.xml").read_bytes()

    monkeypatch.setattr(fetch, "_get", fake_get)
    feeds = ["not-a-dict"]
    items, failed = fetch.fetch_all(feeds)
    assert items == []
    assert len(failed) == 1


def test_fetch_all_mixes_good_and_malformed_entries(monkeypatch):
    def fake_get(url, timeout):
        return (FIX / "feed_ok.xml").read_bytes()

    monkeypatch.setattr(fetch, "_get", fake_get)
    feeds = [
        {"name": "Good", "url": "https://good.example/rss"},
        {"url": "https://noname.example/rss"},
        {"name": "NoUrl"},
        "not-a-dict",
        None,
    ]
    items, failed = fetch.fetch_all(feeds)
    assert len(items) == 2
    assert len(failed) == 4


def test_parse_feed_sets_priority_flag():
    priority_items = fetch.parse_feed((FIX / "feed_ok.xml").read_bytes(), "Example", priority=True)
    assert priority_items
    assert all(item.priority is True for item in priority_items)

    default_items = fetch.parse_feed((FIX / "feed_ok.xml").read_bytes(), "Example")
    assert default_items
    assert all(item.priority is False for item in default_items)


def test_fetch_all_sets_priority_from_feed_config(monkeypatch):
    def fake_get(url, timeout):
        return (FIX / "feed_ok.xml").read_bytes()

    monkeypatch.setattr(fetch, "_get", fake_get)
    feeds = [
        {"name": "Priority Feed", "url": "https://priority.example/rss", "priority": True},
        {"name": "Regular Feed", "url": "https://regular.example/rss"},
        {"name": "Explicit False", "url": "https://explicit.example/rss", "priority": False},
    ]
    items, failed = fetch.fetch_all(feeds)
    assert failed == []

    priority_items = [i for i in items if i.source == "Priority Feed"]
    regular_items = [i for i in items if i.source == "Regular Feed"]
    explicit_false_items = [i for i in items if i.source == "Explicit False"]

    assert priority_items and all(i.priority is True for i in priority_items)
    assert regular_items and all(i.priority is False for i in regular_items)
    assert explicit_false_items and all(i.priority is False for i in explicit_false_items)


def test_fetch_all_survives_malformed_priority_value(monkeypatch):
    """A hand-edited sources.yaml could put a non-bool under `priority` --
    that must still never crash the run (same contract as missing name/url)."""
    def fake_get(url, timeout):
        return (FIX / "feed_ok.xml").read_bytes()

    monkeypatch.setattr(fetch, "_get", fake_get)
    feeds = [{"name": "Weird", "url": "https://weird.example/rss", "priority": "not-a-bool"}]
    items, failed = fetch.fetch_all(feeds)
    assert failed == []
    assert items
