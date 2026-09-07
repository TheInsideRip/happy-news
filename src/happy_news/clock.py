"""Which slot is it, and has that slot already published?

Windows are wide and contiguous on purpose. Task Scheduler is configured to
run a missed task as soon as possible, so a laptop asleep until 11:30 still
delivers a morning edition rather than nothing.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_LOGGER = logging.getLogger(__name__)

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
    """Read one day's edition, degrading to the empty default if the file on
    disk is unreadable or not valid JSON.

    This must never raise. `already_published` (below) is called from OUTSIDE
    cli.do_run's try/except -- deliberately, so the 15 of 18 daily runs that
    land on a done slot exit in milliseconds without touching config. That
    placement means an exception raised here escapes `main` altogether: no
    failures.log line, no health.json update, no toast, no failure counter.
    The page would then freeze on its last good render and repeat the same
    crash on every run, with nothing anywhere saying so -- exactly the silent
    staleness this whole system exists to prevent.

    A half-written edition file is not hypothetical: the scheduled tasks kill
    the process at 15 minutes. `save_edition` now makes producing one very
    unlikely, but a corrupt file that does exist (bad shutdown, disk error,
    a hand-edit) must self-heal: returning the empty default makes the slot
    look unpublished, so the run republishes it and overwrites the bad file
    with a good one."""
    path = edition_path(editions_dir, day)
    default = {"date": day.isoformat(), "slots": {}}
    if not path.exists():
        return default
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
        _LOGGER.warning("unreadable edition file %s (%s); treating the day as empty",
                        path, error)
        return default
    if not isinstance(data, dict):
        _LOGGER.warning("edition file %s does not hold an object; treating the day as empty",
                        path)
        return default
    return data


def save_edition(editions_dir: Path, day: date, data: dict) -> None:
    """Write one day's edition atomically.

    Same guarantee (and the same mechanism) alert.Health._write already gives
    health.json: serialise into a temp file in the same directory, then
    os.replace over the target -- atomic on POSIX and on Windows/NTFS when
    source and destination share a volume. A plain write_text truncates the
    existing file first, so a kill landing in the gap leaves a half-file
    behind; os.replace has no such gap. The reader's page is only ever as
    trustworthy as this file, since it is what `already_published` reads to
    decide whether a slot still needs publishing."""
    editions_dir = Path(editions_dir)
    editions_dir.mkdir(parents=True, exist_ok=True)
    target = edition_path(editions_dir, day)
    fd, tmp_name = tempfile.mkstemp(dir=str(editions_dir), prefix=target.name + ".",
                                    suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def already_published(editions_dir: Path, day: date, slot: str) -> bool:
    """True only when the slot holds at least one story. An empty slot written
    during a drought does not count, so later runs can still fill it."""
    edition = load_edition(editions_dir, day)
    return bool(edition.get("slots", {}).get(slot, {}).get("stories"))
