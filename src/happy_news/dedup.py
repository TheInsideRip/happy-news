"""The permanent memory of everything ever published.

Layers 1 and 2 (exact link, exact headline) are absolute blocks.
Layer 3 (word overlap) is ADVISORY ONLY and must never block on its own --
a mechanical overlap test cannot tell a rewording from two genuinely similar
events, and a hard block built on one silently starves the page.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from . import normalize

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
        if self._entries is None:
            self._entries = []
            if self.path.exists():
                with self.path.open(encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if line:
                            self._entries.append(json.loads(line))
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
            if date.fromisoformat(entry["date"]) < cutoff:
                continue
            if jaccard(toks, entry["tokens"]) >= SOFT_THRESHOLD:
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
        return [e["title"] for e in reversed(self._load())][:limit]
