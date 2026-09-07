"""Finding I1: only one run at a time.

All three scheduled tasks are StartWhenAvailable=True, so a late morning
catch-up can overlap the 14:00 afternoon run. Both read the edition dict and
write it back whole -- last writer wins and drops the other slot entirely,
while that slot's story is already permanently recorded in seen.jsonl. The
story is burned without ever having appeared, and the never-repeat promise
silently loses it.
"""
import os
import time

import pytest

from happy_news import lock


def test_a_second_instance_is_refused_while_the_first_holds_the_lock(tmp_path):
    path = tmp_path / "run.lock"
    with lock.exclusive(path):
        assert path.exists()
        with pytest.raises(lock.LockBusy):
            with lock.exclusive(path):
                raise AssertionError("a second instance must not get in")


def test_the_lock_is_released_when_the_block_finishes(tmp_path):
    path = tmp_path / "run.lock"
    with lock.exclusive(path):
        pass
    assert not path.exists()
    # and the next run can take it
    with lock.exclusive(path):
        pass


def test_the_lock_is_released_even_when_the_body_raises(tmp_path):
    """A failed run must never leave publishing wedged -- a lock that is not
    released is exactly the silent staleness this system exists to prevent."""
    path = tmp_path / "run.lock"
    with pytest.raises(RuntimeError):
        with lock.exclusive(path):
            raise RuntimeError("the run blew up")
    assert not path.exists()
    with lock.exclusive(path):
        pass


def test_a_stale_lock_from_a_killed_process_is_taken_over(tmp_path):
    """Task Scheduler kills a run at 15 minutes. A lock left behind by that
    kill must not freeze publishing forever."""
    path = tmp_path / "run.lock"
    path.write_text('{"pid": 4242}', encoding="utf-8")
    old = time.time() - (lock.STALE_AFTER_SECONDS + 60)
    os.utime(path, (old, old))

    with lock.exclusive(path):
        pass  # must not raise LockBusy

    assert not path.exists()


def test_a_fresh_lock_is_not_treated_as_stale(tmp_path):
    path = tmp_path / "run.lock"
    path.write_text('{"pid": 4242}', encoding="utf-8")

    with pytest.raises(lock.LockBusy):
        with lock.exclusive(path):
            pass

    assert path.exists(), "a live holder's lock must not be deleted"


def test_the_lock_directory_is_created_if_missing(tmp_path):
    path = tmp_path / "logs" / "run.lock"
    with lock.exclusive(path):
        assert path.exists()
