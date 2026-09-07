"""Pull RSS feeds concurrently. One dead feed must never stop a run."""
from __future__ import annotations

import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser

USER_AGENT = "StaceyHappyNews/1.0 (+https://theinsiderip.github.io/happy-news/)"
BLURB_LIMIT = 300

# R2: an attacker-controlled feed has no size limit on the response urllib
# will buffer. A real RSS feed -- even a busy one with full-content
# descriptions for 100+ items -- is reliably well under 1 MB; 5 MB is
# generous headroom for a legitimate feed while keeping the worst case (8
# concurrent workers, every one maliciously oversized) to a ~40 MB spike
# instead of an unbounded one.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
_READ_CHUNK = 65536

# R3: a per-socket-operation timeout (the `timeout` parameter below) does
# not bound a feed that trickles data slowly enough to always beat it -- a
# server sending one byte every 19 seconds never trips a 20-second per-recv
# timeout. FEED_DEADLINE_SECONDS is instead a total wall-clock budget for
# one feed's entire fetch. 30s gives a real feed (typically a fraction of a
# second) enormous headroom, while keeping the worst case -- 12 feeds, 8
# concurrent workers, so at most two queued rounds -- to roughly a minute,
# trivial against Task Scheduler's 15-minute kill.
FEED_DEADLINE_SECONDS = 30

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    source: str
    published: datetime | None
    blurb: str
    priority: bool = False


def _get(url: str, timeout: int) -> bytes:
    """Fetch one feed's raw bytes, bounded on two axes an attacker-controlled
    feed can abuse independently of `timeout` (R2, R3): total size (a feed
    serving hundreds of megabytes) and total wall-clock time (a feed that
    streams so slowly no individual read ever trips `timeout`).

    Reads via `response.read1(n)`, not `response.read(n)`: `read1` performs
    at most one underlying system call and returns whatever is already
    available, so control returns to this loop -- and the size/deadline
    checks below actually run -- after every chunk the server sends, however
    small. `response.read(n)` instead loops internally trying to fill the
    full `n` bytes before returning, which is itself vulnerable to the exact
    slow-drip attack this exists to stop: a chunk could take arbitrarily
    long to fill while never individually tripping the per-recv `timeout`.

    `FEED_DEADLINE_SECONDS` is read as a plain module global on every call
    (not bound as a default parameter value) so tests can monkeypatch it
    directly; `_get`'s own call signature stays `_get(url, timeout)` so
    every caller -- and every test double standing in for it -- is
    unaffected.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        chunks: list[bytes] = []
        total = 0
        while True:
            if time.monotonic() - start > FEED_DEADLINE_SECONDS:
                raise TimeoutError(
                    f"{url}: exceeded the {FEED_DEADLINE_SECONDS}s total fetch budget"
                )
            chunk = response.read1(_READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ValueError(f"{url}: response exceeded {MAX_RESPONSE_BYTES} bytes")
            chunks.append(chunk)
    return b"".join(chunks)


def _published(entry) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def parse_feed(raw: bytes, source_name: str, priority: bool = False) -> list[Candidate]:
    parsed = feedparser.parse(raw)
    items: list[Candidate] = []
    for entry in getattr(parsed, "entries", []):
        title = (getattr(entry, "title", "") or "").strip()
        link = (getattr(entry, "link", "") or "").strip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        blurb = (getattr(entry, "summary", "") or "").strip()[:BLURB_LIMIT]
        items.append(Candidate(title, link, source_name, _published(entry), blurb, priority))

    undated = sum(1 for item in items if item.published is None)
    if undated:
        _LOGGER.info(
            "%s: %d item(s) have no publish date and will be excluded from any time window",
            source_name,
            undated,
        )
    return items


def within_window(items: list[Candidate], hours: int, now: datetime) -> list[Candidate]:
    cutoff = now - timedelta(hours=hours)
    return [i for i in items if i.published is not None and i.published >= cutoff]


def _feed_label(feed) -> str:
    if not isinstance(feed, dict):
        return "<invalid feed entry>"
    return feed.get("name") or feed.get("url") or "<unnamed feed>"


def fetch_all(
    feeds: list[dict], *, timeout: int = 20, deadline: float = FEED_DEADLINE_SECONDS
) -> tuple[list[Candidate], list[str]]:
    """Fetch every feed concurrently. `deadline` bounds each feed
    independently (R3): a feed that has not finished -- connect, headers,
    and body -- within that budget is abandoned and reported as failed,
    rather than the whole run blocking on it.

    The old `with ThreadPoolExecutor(...) as pool: pool.map(...)` shape
    exits via `__exit__`, which waits for every submitted task to finish no
    matter what -- so one feed that never returns (or a test double that
    just sleeps) hung the entire run until Task Scheduler's 15-minute kill.
    Submitting by hand and reading each future back with its own
    `result(timeout=deadline)` lets this function return once every feed has
    either finished or blown its budget; `pool.shutdown(wait=False)` then
    lets fetch_all return without waiting on whatever a timed-out feed's
    worker thread is still doing in the background (bounded on its own by
    `_get`'s internal deadline, so it is not left running forever either).
    """
    results: list[Candidate] = []
    failed: list[str] = []

    def one(feed):
        # feeds/sources.yaml is hand-edited: a missing/blank key or a stray
        # non-dict entry must be reported as a failure, never crash the run.
        if not isinstance(feed, dict):
            return "<invalid feed entry>", [], ValueError(f"feed entry is not a dict: {feed!r}")

        name = feed.get("name") or None
        url = feed.get("url") or None
        label = name or url or "<unnamed feed>"
        priority = feed.get("priority", False)

        if not name or not url:
            return label, [], ValueError(f"feed {label!r} is missing 'name' or 'url'")

        try:
            return name, parse_feed(_get(url, timeout), name, priority), None
        except Exception as error:  # noqa: BLE001 - a dead feed is expected, not exceptional
            return name, [], error

    pool = ThreadPoolExecutor(max_workers=8)
    try:
        futures = {pool.submit(one, feed): feed for feed in feeds}
        for future, feed in futures.items():
            try:
                name, items, error = future.result(timeout=deadline)
            except FutureTimeoutError:
                failed.append(_feed_label(feed))
                continue
            if error is not None:
                failed.append(name)
            else:
                results.extend(items)
    finally:
        pool.shutdown(wait=False)

    return results, failed
