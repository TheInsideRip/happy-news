"""Which slot is it, and has that slot already published?

Windows are wide and contiguous on purpose. Task Scheduler is configured to
run a missed task as soon as possible, so a laptop asleep until 11:30 still
delivers a morning edition rather than nothing.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")

SLOT_WINDOWS: dict[str, tuple[int, int]] = {
    "morning": (8, 14),
    "afternoon": (14, 19),
    "evening": (19, 24),
}

SLOT_ORDER = ["evening", "afternoon", "morning"]  # newest first, for rendering


def now_local() -> datetime:
    return datetime.now(TZ)


def slot_for(moment: datetime) -> str | None:
    hour = moment.hour
    for name, (start, end) in SLOT_WINDOWS.items():
        if start <= hour < end:
            return name
    return None


def edition_path(editions_dir: Path, day: date) -> Path:
    return Path(editions_dir) / f"{day.isoformat()}.json"


def load_edition(editions_dir: Path, day: date) -> dict:
    path = edition_path(editions_dir, day)
    if not path.exists():
        return {"date": day.isoformat(), "slots": {}}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def already_published(editions_dir: Path, day: date, slot: str) -> bool:
    """True only when the slot holds at least one story. An empty slot written
    during a drought does not count, so later runs can still fill it."""
    edition = load_edition(editions_dir, day)
    return bool(edition.get("slots", {}).get(slot, {}).get("stories"))
