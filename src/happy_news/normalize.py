"""Canonical keys for URLs and titles. Pure functions, no I/O."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

TRACKING_PREFIXES = ("utm_", "at_")
TRACKING_EXACT = {
    "fbclid", "gclid", "ref", "source", "mc_cid", "mc_eid", "cmp", "ito",
}

STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
    "her", "was", "one", "our", "out", "has", "had", "his", "him", "she",
    "they", "them", "this", "that", "with", "from", "into", "over", "after",
    "than", "then", "were", "been", "have", "will", "your", "its", "who",
    "how", "why", "what", "when", "where", "which", "their", "there",
    "says", "said", "new", "now", "more", "most", "some", "such", "only",
}

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def _is_tracking(key: str) -> bool:
    low = key.lower()
    return low in TRACKING_EXACT or low.startswith(TRACKING_PREFIXES)


def url_key(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for default_port in (":80", ":443"):
        if host.endswith(default_port):
            host = host[: -len(default_port)]
    path = parts.path.rstrip("/")
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking(key)
    ]
    query = urlencode(sorted(kept))
    return f"{host}{path}?{query}" if query else f"{host}{path}"


def title_norm(title: str) -> str:
    return _WHITESPACE.sub(" ", _PUNCT.sub(" ", title.lower())).strip()


def title_key(title: str) -> str:
    return hashlib.sha1(title_norm(title).encode("utf-8")).hexdigest()


def tokens(title: str) -> list[str]:
    words = title_norm(title).split()
    return sorted({w for w in words if len(w) >= 3 and w not in STOPWORDS})
