import logging
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# R2: a feed response has no size limit. `_get` used a single
# `response.read()`, which buffers the entire body regardless of size -- a
# feed serving 500 MB is fully read into memory, and with 8 concurrent
# workers that is a multi-GB spike on the user's laptop.
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Stands in for the object `urllib.request.urlopen(...)` returns as a
    context manager: supports `read1(n)` (one chunk per call, like the real
    `http.client.HTTPResponse.read1`) and nothing else `_get` needs."""

    def __init__(self, chunks, delay=0.0):
        self._chunks = list(chunks)
        self._delay = delay

    def read1(self, n=-1):
        if self._delay:
            time.sleep(self._delay)
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_get_rejects_a_response_over_the_size_cap(monkeypatch):
    """A feed serving far more than any real RSS feed ever would must be
    rejected, not buffered in full."""
    oversized_chunk = b"x" * (fetch.MAX_RESPONSE_BYTES // 2 + 1)
    fake = _FakeResponse([oversized_chunk, oversized_chunk, oversized_chunk])
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: fake)

    with pytest.raises(ValueError):
        fetch._get("https://evil.example/huge-feed", 20)


def test_get_never_buffers_past_the_cap(monkeypatch):
    """`_get` must abort as soon as the running total crosses the cap,
    rather than reading every chunk a malicious server offers first -- this
    is what "read incrementally" actually buys over reading it all then
    checking `len()`. The fake server below has an infinite supply of
    chunks; if `_get` ever asked for dozens of them before giving up, this
    test would still terminate, but `calls` would be far larger than it
    needs to be to cross the cap."""
    chunk_size = fetch.MAX_RESPONSE_BYTES // 4
    calls = []

    class _CountingResponse(_FakeResponse):
        def read1(self, n=-1):
            calls.append(1)
            return b"x" * chunk_size

    fake = _CountingResponse([])
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: fake)

    with pytest.raises(ValueError):
        fetch._get("https://evil.example/huge-feed", 20)
    # The cap is crossed on the 5th chunk (4 * chunk_size <= cap < 5 *
    # chunk_size); _get must not have kept asking for more after that.
    assert len(calls) <= 6


def test_fetch_all_reports_an_oversized_feed_as_failed_not_a_crash(monkeypatch):
    def fake_get(url, timeout):
        if "huge" in url:
            raise ValueError("response exceeded the size cap")
        return (FIX / "feed_ok.xml").read_bytes()

    monkeypatch.setattr(fetch, "_get", fake_get)
    feeds = [
        {"name": "Huge", "url": "https://huge.example/rss"},
        {"name": "Good", "url": "https://good.example/rss"},
    ]
    items, failed = fetch.fetch_all(feeds)
    assert failed == ["Huge"]
    assert len(items) == 2


# ---------------------------------------------------------------------------
# R3: a slow-drip feed hangs the whole run. `_get` streamed under a
# per-recv 20s timeout, so a server sending one byte every 19 seconds never
# tripped it -- and `fetch_all` exited via `with ThreadPoolExecutor(...)`,
# whose `__exit__` waits for every thread, so one hung feed blocked the
# entire run until Task Scheduler killed it at 15 minutes.
# ---------------------------------------------------------------------------


def test_get_enforces_a_total_deadline_even_though_each_read_is_fast_enough(monkeypatch):
    """Simulates the exact drip: every single read1() call returns quickly
    (well under any per-operation timeout), but there are infinitely many of
    them, so the total time blows a small deadline. `_get` must notice and
    abort rather than patiently accumulating forever.

    `FEED_DEADLINE_SECONDS` is monkeypatched down rather than passed as an
    argument to `_get`, deliberately: `_get`'s call signature must stay
    `_get(url, timeout)` so every existing `monkeypatch.setattr(fetch,
    "_get", fake_get)` two-argument fake in this file keeps working
    unchanged. (A version of this test that instead called
    `fetch._get(url, timeout, deadline=0.2)` would raise TypeError against
    the pre-fix `_get` and pass for the wrong reason -- the assertion below
    would never actually run.)"""
    def trickle():
        while True:
            yield b"x"

    class _DripResponse(_FakeResponse):
        def __init__(self):
            self._gen = trickle()

        def read1(self, n=-1):
            time.sleep(0.02)  # fast per-call, but this never ends
            return next(self._gen)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _DripResponse())
    monkeypatch.setattr(fetch, "FEED_DEADLINE_SECONDS", 0.2)

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        fetch._get("https://slow.example/rss", 20)
    elapsed = time.monotonic() - start
    assert elapsed < 2, f"_get took {elapsed}s -- the per-feed deadline was not enforced"


def test_fetch_all_abandons_a_feed_that_blows_its_deadline_and_returns_promptly(monkeypatch):
    """The whole-run version of the same finding: fetch_all itself must
    return within its budget and name the offending feed as failed, rather
    than blocking on `with ThreadPoolExecutor(...)`'s wait-for-every-thread
    exit -- a genuinely slow feed's worker thread is left running in the
    background instead."""
    def fake_get(url, timeout):
        if "slow" in url:
            time.sleep(0.6)  # longer than the deadline below, but still short
            return (FIX / "feed_ok.xml").read_bytes()
        return (FIX / "feed_ok.xml").read_bytes()

    monkeypatch.setattr(fetch, "_get", fake_get)
    feeds = [
        {"name": "Slow", "url": "https://slow.example/rss"},
        {"name": "Fast", "url": "https://fast.example/rss"},
    ]

    start = time.monotonic()
    items, failed = fetch.fetch_all(feeds, deadline=0.1)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5, f"fetch_all took {elapsed}s -- it waited on the slow feed's thread"
    assert failed == ["Slow"]
    assert len(items) == 2
    assert all(i.source == "Fast" for i in items)
