"""The permanent memory of everything ever published.

Layers 1 and 2 (exact link, exact headline) are absolute blocks.
Layer 3 (word overlap) is ADVISORY ONLY and must never block on its own --
a mechanical overlap test cannot tell a rewording from two genuinely similar
events, and a hard block built on one silently starves the page.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from . import normalize

_LOGGER = logging.getLogger(__name__)

SOFT_THRESHOLD = 0.75
DEFAULT_WINDOW_DAYS = 548  # 18 months


def jaccard(a: list[str], b: list[str]) -> float:
    set_a, set_b = set(a), set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


class Memory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._entries: list[dict] | None = None

    def _load(self) -> list[dict]:
        """Read seen.jsonl, skipping any line we cannot use.

        Direct `entry["url_key"]` indexing meant a single malformed line --
        a partial write, a hand-edit, a truncated append -- raised on EVERY
        subsequent run, freezing the page permanently with the only evidence
        a traceback in run.log. A bad line is dropped and counted instead.

        Dropping a line does weaken the never-repeat guarantee for that one
        story, so the bar for dropping is deliberately narrow: only entries
        that cannot serve layers 1 and 2 at all (unparseable, not an object,
        or with no usable url_key/title_key) are discarded. A usable entry
        with, say, a broken `date` is kept -- the advisory layer-3 check
        below simply skips it."""
        if self._entries is not None:
            return self._entries

        self._entries = []
        skipped = 0
        if self.path.exists():
            try:
                with self.path.open(encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            skipped += 1
                            continue
                        if (not isinstance(entry, dict)
                                or not isinstance(entry.get("url_key"), str)
                                or not isinstance(entry.get("title_key"), str)):
                            skipped += 1
                            continue
                        self._entries.append(entry)
            except (OSError, UnicodeDecodeError) as error:
                _LOGGER.error("could not finish reading %s (%s); %d entries loaded",
                              self.path, error, len(self._entries))
        if skipped:
            _LOGGER.warning("%s: skipped %d unreadable line(s); %d entries loaded",
                            self.path, skipped, len(self._entries))
        return self._entries

    def is_blocked(self, url: str, title: str) -> bool:
        """Layers 1 and 2 only. Absolute, permanent, no exceptions."""
        key_u, key_t = normalize.url_key(url), normalize.title_key(title)
        for entry in self._load():
            if entry["url_key"] == key_u or entry["title_key"] == key_t:
                return True
        return False

    def is_near_duplicate(self, title: str, within_days: int = DEFAULT_WINDOW_DAYS) -> bool:
        """Layer 3. ADVISORY. Callers demote; they must not discard."""
        cutoff = date.today() - timedelta(days=within_days)
        toks = normalize.tokens(title)
        for entry in self._load():
            try:
                entry_date = date.fromisoformat(str(entry.get("date")))
            except (TypeError, ValueError):
                continue  # no usable date: the advisory layer just skips it
            if entry_date < cutoff:
                continue
            entry_tokens = entry.get("tokens")
            if not isinstance(entry_tokens, list):
                continue
            if jaccard(toks, entry_tokens) >= SOFT_THRESHOLD:
                return True
        return False

    def remember(self, url: str, title: str, date_str: str, slot: str) -> None:
        entry = {
            "url_key": normalize.url_key(url),
            "title_key": normalize.title_key(title),
            "tokens": normalize.tokens(title),
            "title": title,
            "date": date_str,
            "slot": slot,
        }
        entries = self._load()  # load cache BEFORE file is modified
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        entries.append(entry)

    def recent_titles(self, limit: int = 60) -> list[str]:
        titles = [e.get("title") for e in reversed(self._load())]
        return [t for t in titles if isinstance(t, str) and t][:limit]
