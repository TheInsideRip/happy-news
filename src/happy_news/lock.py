"""One run at a time.

All three scheduled tasks are registered with StartWhenAvailable=True, so a
morning task that was missed (laptop asleep) starts as soon as the machine
wakes -- which can be at 14:00, exactly when the afternoon task fires. A run
spans a 12-feed fetch plus a model call of up to 180 seconds, so the overlap
is wide.

Two overlapping runs are not merely wasteful, they lose a story for good.
Both read `data/editions/<date>.json` into a dict and later write the whole
dict back: the last writer wins and drops the other slot entirely -- while
that slot's story is already recorded in `seen.jsonl`, which is permanent and
append-only. The story is burned without ever having appeared. Concurrent
`git add`/`git commit` in the same repo also collide on `.git/index.lock`.

So: an exclusive lock file, created with O_CREAT|O_EXCL (a single atomic
syscall on both Windows and POSIX -- no check-then-create race). A second
instance does not wait and does not fail: a run skipped because another run
is already doing the work is a correct outcome, not an error, so it says so
and exits 0.

A lock left behind by a killed process must not freeze publishing forever --
that would be the very silent staleness this system exists to prevent. The
scheduled tasks kill a run at 15 minutes, so a lock file older than
STALE_AFTER_SECONDS cannot belong to a live scheduled run and is taken over.
"""
from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

# Task Scheduler kills a run at 15 minutes; double it so a slow-but-alive run
# is never stolen from, while a crashed one still clears within the hour
# between slots.
STALE_AFTER_SECONDS = 30 * 60


class LockBusy(RuntimeError):
    """Another instance holds the lock. Not an error -- a reason to stand down."""


def _describe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip() or "(empty)"
    except OSError:
        return "(unreadable)"


def _age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def _create(path: Path) -> int:
    """O_EXCL create: atomically fails if the file already exists."""
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    os.write(fd, json.dumps({"pid": os.getpid(), "at": time.time()}).encode("utf-8"))
    return fd


def _acquire(path: Path, stale_after: float) -> int:
    try:
        return _create(path)
    except FileExistsError:
        pass

    age = _age_seconds(path)
    if age is None:
        # It vanished between the failed create and the stat -- the holder
        # finished. One more try, then give up.
        try:
            return _create(path)
        except FileExistsError:
            raise LockBusy(f"another run holds {path}") from None

    if age < stale_after:
        raise LockBusy(
            f"another run holds {path} (held {int(age)}s ago by {_describe(path)})"
        )

    _LOGGER.warning("taking over a stale lock %s (%d seconds old, %s)",
                    path, int(age), _describe(path))
    try:
        os.remove(path)
    except OSError:
        pass
    try:
        return _create(path)
    except FileExistsError:
        raise LockBusy(f"another run took {path} first") from None


@contextmanager
def exclusive(path, *, stale_after: float = STALE_AFTER_SECONDS):
    """Hold an exclusive lock for the duration of the block.

    Raises LockBusy immediately (never blocks) if another live instance holds
    it. The lock is always released, including when the body raises.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = _acquire(path, stale_after)
    try:
        yield path
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(path)
        except OSError:
            _LOGGER.warning("could not remove the lock file %s", path)
