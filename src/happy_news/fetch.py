"""Pull RSS feeds concurrently. One dead feed must never stop a run."""
from __future__ import annotations

import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser

USER_AGENT = "StaceyHappyNews/1.0 (+https://theinsiderip.github.io/happy-news/)"
BLURB_LIMIT = 300


@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    source: str
    published: datetime | None
    blurb: str


def _get(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _published(entry) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def parse_feed(raw: bytes, source_name: str) -> list[Candidate]:
    parsed = feedparser.parse(raw)
    items: list[Candidate] = []
    for entry in getattr(parsed, "entries", []):
        title = (getattr(entry, "title", "") or "").strip()
        link = (getattr(entry, "link", "") or "").strip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        blurb = (getattr(entry, "summary", "") or "").strip()[:BLURB_LIMIT]
        items.append(Candidate(title, link, source_name, _published(entry), blurb))
    return items


def within_window(items: list[Candidate], hours: int, now: datetime) -> list[Candidate]:
    cutoff = now - timedelta(hours=hours)
    return [i for i in items if i.published is not None and i.published >= cutoff]


def fetch_all(feeds: list[dict], *, timeout: int = 20) -> tuple[list[Candidate], list[str]]:
    results: list[Candidate] = []
    failed: list[str] = []

    def one(feed: dict):
        try:
            return feed["name"], parse_feed(_get(feed["url"], timeout), feed["name"]), None
        except Exception as error:  # noqa: BLE001 - a dead feed is expected, not exceptional
            return feed["name"], [], error

    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, items, error in pool.map(one, feeds):
            if error is not None:
                failed.append(name)
            else:
                results.extend(items)
    return results, failed
