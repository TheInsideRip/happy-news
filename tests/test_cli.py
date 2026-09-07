"""Tests for the cli.py orchestrator.

No test here touches the network, invokes the real `claude` CLI, or runs a
real `git push` -- `fetch.fetch_all`, `curate.ask`/`check_auth`, and
`publish.push`/`publish.run_git` are always monkeypatched to canned,
in-memory stand-ins. `alert.notify` is monkeypatched everywhere too, so no
test pops a real Windows toast.
"""
from __future__ import annotations

import inspect
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from happy_news import alert, cli, curate, ladder, publish, render
from happy_news.fetch import Candidate

ET = ZoneInfo("America/New_York")

EDITORIAL = {
    "labels": ["earth", "world"],
    "banned_terms": ["election"],
    "outcome_overrides": [],
}


def _make_root(tmp_path: Path, *, feeds=None, evergreen=None) -> Path:
    """A tmp_path with a minimal, valid feeds/*.yaml so config.load succeeds."""
    feeds_dir = tmp_path / "feeds"
    feeds_dir.mkdir(parents=True, exist_ok=True)
    (feeds_dir / "sources.yaml").write_text(
        yaml.safe_dump({"feeds": feeds or []}), encoding="utf-8"
    )
    (feeds_dir / "editorial.yaml").write_text(yaml.safe_dump(EDITORIAL), encoding="utf-8")
    (feeds_dir / "evergreen.yaml").write_text(
        yaml.safe_dump({"stories": evergreen or []}), encoding="utf-8"
    )
    return tmp_path


def _quiet_notify(monkeypatch, calls=None):
    """Prevent every test from popping a real Windows toast; optionally record calls."""
    calls = calls if calls is not None else []

    def fake_notify(title, message):
        calls.append((title, message))

    monkeypatch.setattr(cli.alert, "notify", fake_notify)
    return calls


def _no_push(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not push")

    monkeypatch.setattr(cli.publish, "push", boom)


def _recording_push(monkeypatch):
    calls = []

    def fake_push(root, message, **kwargs):
        calls.append((root, message))

    monkeypatch.setattr(cli.publish, "push", fake_push)
    return calls


def _story(title="Turtles recover", url="https://example.com/turtles"):
    return {
        "title": title,
        "url": url,
        "source": "BBC",
        "label": "earth",
        "summary": "Good news happened.",
        "why_good": "It is good.",
    }


# ---------------------------------------------------------------------------
# Ruling 1: slot / already-published checks happen BEFORE config.load
# ---------------------------------------------------------------------------


def test_run_exits_quietly_outside_a_window(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 3, 0, tzinfo=ET))
    # tmp_path has no feeds/ directory at all -- if config.load were reached
    # first this would raise FileNotFoundError instead of returning 0.
    assert cli.main(["run", "--root", str(tmp_path)]) == 0


def test_run_exits_quietly_when_the_slot_already_published(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    monkeypatch.setattr(cli.clock, "already_published", lambda *a, **k: True)
    assert cli.main(["run", "--root", str(tmp_path)]) == 0


def test_dry_run_at_an_unpublished_slot_with_no_feeds_dir_still_short_circuits(monkeypatch, tmp_path):
    """Same ruling-1 guarantee for dry-run: the two checks are outside the try
    block entirely, so they don't need config.load to succeed either."""
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 3, 0, tzinfo=ET))
    assert cli.main(["dry-run", "--root", str(tmp_path)]) == 0


# ---------------------------------------------------------------------------
# dry-run writes nothing, pushes nothing
# ---------------------------------------------------------------------------


def test_dry_run_writes_nothing(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    _no_push(monkeypatch)
    _quiet_notify(monkeypatch)

    now_utc = datetime.now(timezone.utc)
    candidate = Candidate("Turtles recover", "https://example.com/turtles", "BBC",
                          now_utc - timedelta(hours=2), "blurb")
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([candidate], []))
    monkeypatch.setattr(cli.curate, "ask", lambda prompt, system, **k: [_story()])

    assert cli.main(["dry-run", "--root", str(root)]) == 0

    assert not (root / "index.html").exists()
    assert not (root / "archive").exists()
    assert not (root / "data" / "editions").exists()
    assert not (root / "data" / "health.json").exists()
    assert not (root / "data" / "seen.jsonl").exists()


def test_dry_run_prints_the_chosen_story(monkeypatch, tmp_path, capsys):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    _no_push(monkeypatch)
    _quiet_notify(monkeypatch)

    now_utc = datetime.now(timezone.utc)
    candidate = Candidate("Turtles recover", "https://example.com/turtles", "BBC",
                          now_utc - timedelta(hours=2), "blurb", priority=True)
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([candidate], []))
    monkeypatch.setattr(cli.curate, "ask", lambda prompt, system, **k: [_story()])

    cli.main(["dry-run", "--root", str(root)])
    out = capsys.readouterr().out
    assert "Turtles recover" in out
    assert "tier 1" in out


# ---------------------------------------------------------------------------
# Full happy path: tier 1 story is fetched, built, validated, written, pushed
# ---------------------------------------------------------------------------


def test_run_publishes_a_tier1_story_end_to_end(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    fake_now = datetime(2026, 9, 7, 8, 30, tzinfo=ET)
    monkeypatch.setattr(cli.clock, "now_local", lambda: fake_now)
    notify_calls = _quiet_notify(monkeypatch)
    push_calls = _recording_push(monkeypatch)

    # age_text is computed against clock.now_local()'s reading, so the
    # candidate's published time must be relative to that same fake "now"
    # (not the real wall clock) for "N hours ago" to come out exact.
    candidate = Candidate("Turtles recover", "https://example.com/turtles", "BBC",
                          fake_now.astimezone(timezone.utc) - timedelta(hours=2), "blurb",
                          priority=True)
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([candidate], []))
    monkeypatch.setattr(cli.curate, "ask", lambda prompt, system, **k: [_story()])

    assert cli.main(["run", "--root", str(root)]) == 0

    index_html = (root / "index.html").read_text(encoding="utf-8")
    assert "Turtles recover" in index_html
    assert "2 hours ago" in index_html

    edition = json.loads((root / "data" / "editions" / "2026-09-07.json").read_text(encoding="utf-8"))
    story = edition["slots"]["morning"]["stories"][0]
    assert story["title"] == "Turtles recover"
    assert story["age_text"] == "2 hours ago"
    assert story["evergreen"] is False

    seen_lines = (root / "data" / "seen.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(seen_lines) == 1

    health = json.loads((root / "data" / "health.json").read_text(encoding="utf-8"))
    assert health["consecutive_failures"] == 0
    assert health["tiers"][-1] == 1
    assert health["droughts"] == []

    assert len(push_calls) == 1
    assert push_calls[0][0] == root
    assert not notify_calls  # tier 1, a story was found: no alert needed


# ---------------------------------------------------------------------------
# Fix round 1, finding 1: a failed push must not leave the edition file
# looking published, or the next run in the same window silently no-ops
# via clock.already_published() instead of genuinely retrying.
# ---------------------------------------------------------------------------


def test_a_failed_push_does_not_block_a_retry_in_the_same_window(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    _quiet_notify(monkeypatch)

    now_utc = datetime.now(timezone.utc)
    candidate = Candidate("Turtles recover", "https://example.com/turtles", "BBC",
                          now_utc - timedelta(hours=2), "blurb")
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([candidate], []))
    monkeypatch.setattr(cli.curate, "ask", lambda prompt, system, **k: [_story()])

    first_push_calls = []

    def failing_push(root, message, **kwargs):
        first_push_calls.append(message)
        raise publish.PublishError("push failed after rebase: simulated network failure")

    monkeypatch.setattr(cli.publish, "push", failing_push)

    # First run: the ladder finds a story and the page validates, but the
    # push to git fails (network down, remote rejected it, whatever).
    assert cli.main(["run", "--root", str(root)]) == 1
    assert len(first_push_calls) == 1

    # Nothing that failed may leave a trace that makes the slot look done.
    editions_dir = root / "data" / "editions"
    from happy_news import clock
    assert clock.already_published(editions_dir, date(2026, 9, 7), "morning") is False

    # The dedup memory is append-only and absolute -- a story that never
    # reached the page must not be permanently burned.
    seen_path = root / "data" / "seen.jsonl"
    assert not seen_path.exists() or seen_path.read_text(encoding="utf-8").strip() == ""

    health = json.loads((root / "data" / "health.json").read_text(encoding="utf-8"))
    assert health["consecutive_failures"] == 1
    assert health["last_success"] is None

    # Second run, same window: must genuinely retry (fetch again, pick
    # again, push again) rather than exiting quietly with "already published".
    second_push_calls = _recording_push(monkeypatch)

    assert cli.main(["run", "--root", str(root)]) == 0
    assert len(second_push_calls) == 1

    index_html = (root / "index.html").read_text(encoding="utf-8")
    assert "Turtles recover" in index_html

    edition = json.loads((editions_dir / "2026-09-07.json").read_text(encoding="utf-8"))
    assert edition["slots"]["morning"]["stories"][0]["title"] == "Turtles recover"

    seen_lines = seen_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(seen_lines) == 1

    health = json.loads((root / "data" / "health.json").read_text(encoding="utf-8"))
    assert health["consecutive_failures"] == 0
    assert health["last_success"] is not None


# ---------------------------------------------------------------------------
# Fix round 1, finding 2: health.record_success() must not run before
# publish.push() -- otherwise a failed push's failure count restarts at 1
# instead of correctly extending whatever streak was already running.
# ---------------------------------------------------------------------------


def test_a_failed_push_correctly_extends_the_consecutive_failure_streak(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    notify_calls = _quiet_notify(monkeypatch)

    # Two failures already on record from earlier runs today.
    health_path = root / "data" / "health.json"
    health_path.parent.mkdir(parents=True)
    health_path.write_text(json.dumps({
        "consecutive_failures": 2, "last_success": None,
        "failures": [{"at": "x", "reason": "boom"}, {"at": "y", "reason": "boom"}],
        "droughts": [], "tiers": [],
    }), encoding="utf-8")

    now_utc = datetime.now(timezone.utc)
    candidate = Candidate("Turtles recover", "https://example.com/turtles", "BBC",
                          now_utc - timedelta(hours=2), "blurb")
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([candidate], []))
    monkeypatch.setattr(cli.curate, "ask", lambda prompt, system, **k: [_story()])

    def failing_push(root, message, **kwargs):
        raise publish.PublishError("push failed after rebase: simulated network failure")

    monkeypatch.setattr(cli.publish, "push", failing_push)

    assert cli.main(["run", "--root", str(root)]) == 1

    health = json.loads(health_path.read_text(encoding="utf-8"))
    # If record_success() had run before the push (resetting the counter to
    # 0) and only then the push failed, this would read back as 1, not 3,
    # and the "3 in a row" alarm below would never fire.
    assert health["consecutive_failures"] == 3
    assert health["last_success"] is None
    assert any("3 in a row" in title for title, _ in notify_calls)


# ---------------------------------------------------------------------------
# Ruling 2: age_text is matched back to the real Candidate.published
# ---------------------------------------------------------------------------


def test_age_text_matches_the_chosen_candidate_by_url_key(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    fake_now = datetime(2026, 9, 7, 8, 30, tzinfo=ET)
    monkeypatch.setattr(cli.clock, "now_local", lambda: fake_now)
    _quiet_notify(monkeypatch)
    _recording_push(monkeypatch)

    now_utc = fake_now.astimezone(timezone.utc)
    # Two candidates: only one matches the model's chosen URL (via url_key,
    # so a trailing slash / query difference must not break the match).
    decoy = Candidate("Some other story", "https://example.com/decoy", "BBC",
                      now_utc - timedelta(hours=50), "blurb")
    chosen = Candidate("Turtles recover", "https://example.com/turtles/?utm_source=x", "BBC",
                       now_utc - timedelta(hours=5), "blurb")
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([decoy, chosen], []))
    # The model returns the canonical (tracking-stripped) URL, as it would
    # from reading the candidate list built by curate.build_prompt.
    monkeypatch.setattr(cli.curate, "ask", lambda prompt, system, **k: [_story(url="https://example.com/turtles")])

    assert cli.main(["run", "--root", str(root)]) == 0

    edition = json.loads((root / "data" / "editions" / "2026-09-07.json").read_text(encoding="utf-8"))
    story = edition["slots"]["morning"]["stories"][0]
    assert story["age_text"] == "5 hours ago"


def test_age_text_shows_a_weekday_for_stories_over_three_days_old(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    _quiet_notify(monkeypatch)
    _recording_push(monkeypatch)

    now_utc = datetime.now(timezone.utc)
    old_published = now_utc - timedelta(days=4)
    candidate = Candidate("Old but unseen", "https://example.com/old", "BBC",
                          old_published, "blurb")
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([candidate], []))
    monkeypatch.setattr(cli.curate, "ask", lambda prompt, system, **k: [_story(title="Old but unseen", url="https://example.com/old")])

    assert cli.main(["run", "--root", str(root)]) == 0

    edition = json.loads((root / "data" / "editions" / "2026-09-07.json").read_text(encoding="utf-8"))
    story = edition["slots"]["morning"]["stories"][0]
    assert story["age_text"] == old_published.strftime("%A")


# ---------------------------------------------------------------------------
# Evergreen: bypasses age_text, renders STILL TRUE, alerts at tier 5
# ---------------------------------------------------------------------------


def test_evergreen_story_bypasses_age_text_and_alerts(monkeypatch, tmp_path):
    evergreen_item = {
        "title": "Ozone healing", "url": "https://a.example/ozone",
        "source": "UNEP", "label": "earth", "summary": "Recovering.",
    }
    root = _make_root(tmp_path, feeds=[], evergreen=[evergreen_item])
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    notify_calls = _quiet_notify(monkeypatch)
    _recording_push(monkeypatch)
    # No candidates at all (empty feeds list) -- every real-feed tier is
    # skipped and the ladder falls straight to the evergreen reserve without
    # ever calling curate.ask.
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([], []))
    monkeypatch.setattr(cli.curate, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call ask")))

    assert cli.main(["run", "--root", str(root)]) == 0

    edition = json.loads((root / "data" / "editions" / "2026-09-07.json").read_text(encoding="utf-8"))
    story = edition["slots"]["morning"]["stories"][0]
    assert story["evergreen"] is True
    assert story["age_text"] == ""

    index_html = (root / "index.html").read_text(encoding="utf-8")
    assert "STILL TRUE" in index_html

    assert any("tier 5" in msg.lower() or "evergreen" in msg.lower() for _, msg in notify_calls)


def test_reaching_tier4_logs_a_warning_not_an_alert(monkeypatch, tmp_path, caplog):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    notify_calls = _quiet_notify(monkeypatch)
    _recording_push(monkeypatch)

    now_utc = datetime.now(timezone.utc)
    # Old enough (80 days) that only tier 4 (90-day window) picks it up.
    candidate = Candidate("Reached way back", "https://example.com/way-back", "BBC",
                          now_utc - timedelta(days=80), "blurb")
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([candidate], []))
    monkeypatch.setattr(cli.curate, "ask",
                        lambda prompt, system, **k: [_story(title="Reached way back", url="https://example.com/way-back")])

    with caplog.at_level("WARNING"):
        assert cli.main(["run", "--root", str(root)]) == 0

    assert any("tier 4" in rec.message for rec in caplog.records)
    assert not notify_calls  # tier 4 is a log warning, not a toast alert


# ---------------------------------------------------------------------------
# Drought handling
# ---------------------------------------------------------------------------


def test_exhausted_ladder_records_a_drought_not_a_failure_and_skips_the_page(monkeypatch, tmp_path):
    """First slot of the day, nothing found anywhere (feeds AND evergreen
    both empty): the edition JSON must still record the empty slot so a
    later run in the same window can retry, but index.html must NOT be
    written -- there is nothing yet to show, and render.validate() would
    correctly reject a page with zero stories."""
    root = _make_root(tmp_path, feeds=[], evergreen=[])
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    notify_calls = _quiet_notify(monkeypatch)
    push_calls = _recording_push(monkeypatch)
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([], []))

    assert cli.main(["run", "--root", str(root)]) == 0

    assert not (root / "index.html").exists()

    edition = json.loads((root / "data" / "editions" / "2026-09-07.json").read_text(encoding="utf-8"))
    slot = edition["slots"]["morning"]
    assert slot["stories"] == []
    assert slot["note"] == ladder.QUIET_NOTE

    health = json.loads((root / "data" / "health.json").read_text(encoding="utf-8"))
    assert health["consecutive_failures"] == 0
    assert health["droughts"], "a drought must be recorded"
    assert health["droughts"][-1]["reason"]

    assert any("defect" in msg.lower() for _, msg in notify_calls)
    # The data file still changed, so it is still committed/pushed even
    # though no HTML page changed.
    assert len(push_calls) == 1

    # Not already-published: a later run this window must still try.
    from happy_news import clock
    assert clock.already_published(root / "data" / "editions", edition_date(edition), "morning") is False


def edition_date(edition):
    from datetime import date
    return date.fromisoformat(edition["date"])


def test_drought_in_a_later_slot_still_publishes_the_page_that_already_has_a_story(monkeypatch, tmp_path):
    root = _make_root(tmp_path, feeds=[], evergreen=[])
    editions_dir = root / "data" / "editions"
    editions_dir.mkdir(parents=True)
    existing = {
        "date": "2026-09-07",
        "updated_text": "8:03 am",
        "slots": {
            "morning": {
                "published_at": "2026-09-07T08:03:00-04:00",
                "time_text": "8:03 am",
                "note": None,
                "stories": [dict(_story(title="Morning story", url="https://example.com/morning"),
                                 age_text="1 hour ago", evergreen=False)],
            }
        },
    }
    (editions_dir / "2026-09-07.json").write_text(json.dumps(existing), encoding="utf-8")

    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 15, 0, tzinfo=ET))
    notify_calls = _quiet_notify(monkeypatch)
    _recording_push(monkeypatch)
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([], []))

    assert cli.main(["run", "--root", str(root)]) == 0

    index_html = (root / "index.html").read_text(encoding="utf-8")
    assert "Morning story" in index_html
    assert ladder.QUIET_NOTE in index_html

    health = json.loads((root / "data" / "health.json").read_text(encoding="utf-8"))
    assert health["consecutive_failures"] == 0
    assert health["droughts"]
    assert any("defect" in msg.lower() for _, msg in notify_calls)


# ---------------------------------------------------------------------------
# Nothing is published unless render validation passes
# ---------------------------------------------------------------------------


def test_a_genuine_validation_failure_is_a_real_failure_not_a_silent_skip(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    notify_calls = _quiet_notify(monkeypatch)
    _no_push(monkeypatch)  # a broken page must never even reach the commit step

    now_utc = datetime.now(timezone.utc)
    candidate = Candidate("Turtles recover", "https://example.com/turtles", "BBC",
                          now_utc - timedelta(hours=2), "blurb")
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([candidate], []))
    monkeypatch.setattr(cli.curate, "ask", lambda prompt, system, **k: [_story()])

    def broken_validate(page):
        raise ValueError("page contains an empty summary")

    monkeypatch.setattr(cli.render, "validate", broken_validate)

    assert cli.main(["run", "--root", str(root)]) == 1

    assert not (root / "index.html").exists()
    health = json.loads((root / "data" / "health.json").read_text(encoding="utf-8"))
    assert health["consecutive_failures"] == 1
    assert health["failures"][-1]["reason"]
    log_path = root / "logs" / "failures.log"
    assert log_path.exists() and log_path.read_text(encoding="utf-8").strip()
    assert notify_calls  # top-level except must notify


# ---------------------------------------------------------------------------
# Ruling 6: validate() is never called on the archive index page
# ---------------------------------------------------------------------------


def test_validate_is_never_called_on_the_archive_index(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.clock, "now_local", lambda: datetime(2026, 9, 7, 8, 30, tzinfo=ET))
    _quiet_notify(monkeypatch)
    _recording_push(monkeypatch)

    now_utc = datetime.now(timezone.utc)
    candidate = Candidate("Turtles recover", "https://example.com/turtles", "BBC",
                          now_utc - timedelta(hours=2), "blurb")
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([candidate], []))
    monkeypatch.setattr(cli.curate, "ask", lambda prompt, system, **k: [_story()])

    real_validate = render.validate
    pages_validated = []

    def spy(page):
        pages_validated.append(page)
        return real_validate(page)

    monkeypatch.setattr(cli.render, "validate", spy)

    assert cli.main(["run", "--root", str(root)]) == 0

    assert pages_validated, "at least the day page must have been validated"
    for page in pages_validated:
        assert 'class="archive-list"' not in page

    assert (root / "archive" / "index.html").exists()
    archive_index = (root / "archive" / "index.html").read_text(encoding="utf-8")
    assert 'class="archive-list"' in archive_index


def test_rebuild_with_no_editions_writes_an_empty_archive_index_without_crashing(tmp_path):
    """Ruling 6 in miniature: render.validate() requires >=1 story, but the
    archive index legitimately has zero -- rebuild on an empty data dir must
    not raise."""
    root = _make_root(tmp_path)
    assert cli.main(["rebuild", "--root", str(root)]) == 0
    assert (root / "archive" / "index.html").exists()
    assert not (root / "index.html").exists()  # nothing to show yet, none written


def test_rebuild_regenerates_pages_from_existing_editions(tmp_path):
    root = _make_root(tmp_path)
    editions_dir = root / "data" / "editions"
    editions_dir.mkdir(parents=True)
    edition = {
        "date": "2026-09-07",
        "updated_text": "8:03 am",
        "slots": {
            "morning": {
                "published_at": "2026-09-07T08:03:00-04:00",
                "time_text": "8:03 am",
                "note": None,
                "stories": [dict(_story(), age_text="1 hour ago", evergreen=False)],
            }
        },
    }
    (editions_dir / "2026-09-07.json").write_text(json.dumps(edition), encoding="utf-8")

    assert cli.main(["rebuild", "--root", str(root)]) == 0

    assert "Turtles recover" in (root / "index.html").read_text(encoding="utf-8")
    assert "Turtles recover" in (root / "archive" / "2026-09-07.html").read_text(encoding="utf-8")
    assert "2026-09-07" in (root / "archive" / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Ruling 3: doctor calls curate.check_auth(), never curate.ask()
# ---------------------------------------------------------------------------


def test_doctor_calls_check_auth_and_never_ask(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([], []))
    monkeypatch.setattr(cli.curate, "check_auth", lambda **k: None)
    monkeypatch.setattr(cli.curate, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call ask")))
    monkeypatch.setattr(cli.publish, "run_git", lambda args, cwd: (0, "## main"))

    assert cli.main(["doctor", "--root", str(root)]) == 0


def test_doctor_reports_failure_when_check_auth_raises(monkeypatch, tmp_path, capsys):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([], []))

    def fail(**k):
        raise curate.CurateError("Failed to authenticate: OAuth session expired")

    monkeypatch.setattr(cli.curate, "check_auth", fail)
    monkeypatch.setattr(cli.publish, "run_git", lambda args, cwd: (0, "## main"))

    assert cli.main(["doctor", "--root", str(root)]) == 1
    assert "authenticate" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# Ruling 5: doctor calls the public publish.run_git, never the private _run
# ---------------------------------------------------------------------------


def test_doctor_uses_the_public_run_git(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([], []))
    monkeypatch.setattr(cli.curate, "check_auth", lambda **k: None)

    calls = []
    monkeypatch.setattr(cli.publish, "run_git", lambda args, cwd: (calls.append((args, cwd)), (0, "## main"))[1])

    assert cli.main(["doctor", "--root", str(root)]) == 0
    assert calls, "publish.run_git must have been called"
    assert calls[0][1] == root


def test_doctor_fails_when_git_check_fails(monkeypatch, tmp_path):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([], []))
    monkeypatch.setattr(cli.curate, "check_auth", lambda **k: None)
    monkeypatch.setattr(cli.publish, "run_git", lambda args, cwd: (1, "fatal: not a git repository"))

    assert cli.main(["doctor", "--root", str(root)]) == 1


# ---------------------------------------------------------------------------
# Fix round 1, finding 3: doctor must report a missing executable as a
# failed check, not crash with a raw traceback.
# ---------------------------------------------------------------------------


def test_doctor_reports_missing_claude_executable_instead_of_crashing(monkeypatch, tmp_path, capsys):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([], []))

    def missing_exe(**k):
        raise FileNotFoundError(2, "No such file or directory", r"C:\Users\kaimo\.local\bin\claude.exe")

    monkeypatch.setattr(cli.curate, "check_auth", missing_exe)
    monkeypatch.setattr(cli.publish, "run_git", lambda args, cwd: (0, "## main"))

    assert cli.main(["doctor", "--root", str(root)]) == 1
    assert "claude cli: failed" in capsys.readouterr().out.lower()


def test_doctor_reports_missing_git_executable_instead_of_crashing(monkeypatch, tmp_path, capsys):
    root = _make_root(tmp_path)
    monkeypatch.setattr(cli.fetch, "fetch_all", lambda feeds, **k: ([], []))
    monkeypatch.setattr(cli.curate, "check_auth", lambda **k: None)

    def missing_git(args, cwd):
        raise FileNotFoundError(2, "No such file or directory", "git")

    monkeypatch.setattr(cli.publish, "run_git", missing_git)

    assert cli.main(["doctor", "--root", str(root)]) == 1
    assert "git: failed" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# Ruling 4: no __import__ transcription artefacts
# ---------------------------------------------------------------------------


def test_cli_module_uses_ordinary_imports_only():
    source = inspect.getsource(cli)
    assert "__import__" not in source


# ---------------------------------------------------------------------------
# Front page shows today plus previous days, newest first -- "its fine to
# scroll, i dont want that to limit info". Archive pages are unaffected: they
# still render one day each (already covered by test_rebuild_regenerates_
# pages_from_existing_editions above).
# ---------------------------------------------------------------------------


def _edition_with_story(day_str: str, title: str, time_text: str = "8:03 am") -> dict:
    return {
        "date": day_str,
        "updated_text": time_text,
        "slots": {
            "morning": {
                "published_at": f"{day_str}T08:03:00-04:00",
                "time_text": time_text,
                "note": None,
                "stories": [dict(_story(title=title, url=f"https://example.com/{title}"),
                                 age_text="1 hour ago", evergreen=False)],
            }
        },
    }


def test_front_page_includes_todays_and_previous_days_stories(tmp_path):
    root = _make_root(tmp_path)
    editions_dir = root / "data" / "editions"
    editions_dir.mkdir(parents=True)
    for day_str, title in [
        ("2026-09-07", "TodayStory"),
        ("2026-09-06", "YesterdayStory"),
        ("2026-09-05", "TwoDaysAgoStory"),
    ]:
        edition = _edition_with_story(day_str, title)
        (editions_dir / f"{day_str}.json").write_text(json.dumps(edition), encoding="utf-8")

    assert cli.main(["rebuild", "--root", str(root)]) == 0

    index_html = (root / "index.html").read_text(encoding="utf-8")
    assert "TodayStory" in index_html
    assert "YesterdayStory" in index_html
    assert "TwoDaysAgoStory" in index_html
    # today's story must appear first (newest first)
    assert index_html.index("TodayStory") < index_html.index("YesterdayStory")
    assert index_html.index("YesterdayStory") < index_html.index("TwoDaysAgoStory")

    # archive pages are untouched: each is still exactly one day
    archive_yesterday = (root / "archive" / "2026-09-06.html").read_text(encoding="utf-8")
    assert "YesterdayStory" in archive_yesterday
    assert "TodayStory" not in archive_yesterday
    assert "TwoDaysAgoStory" not in archive_yesterday


def test_front_page_shows_at_most_the_last_seven_days(tmp_path):
    root = _make_root(tmp_path)
    editions_dir = root / "data" / "editions"
    editions_dir.mkdir(parents=True)
    # today (2026-09-07) plus 9 previous days: only the 6 most recent
    # previous days (2026-09-06 down to 2026-09-01) belong on the front page;
    # 2026-08-31 and earlier must not appear there.
    days = [date(2026, 9, 7) - timedelta(days=n) for n in range(10)]
    for day in days:
        day_str = day.isoformat()
        title = f"Story{day_str}"
        edition = _edition_with_story(day_str, title)
        (editions_dir / f"{day_str}.json").write_text(json.dumps(edition), encoding="utf-8")

    assert cli.main(["rebuild", "--root", str(root)]) == 0

    index_html = (root / "index.html").read_text(encoding="utf-8")
    for day in days[:7]:
        assert f"Story{day.isoformat()}" in index_html
    for day in days[7:]:
        assert f"Story{day.isoformat()}" not in index_html

    # the older days are still findable in the archive, just not the front page
    archive_index = (root / "archive" / "index.html").read_text(encoding="utf-8")
    assert days[9].isoformat() in archive_index


def test_front_page_with_only_today_still_works(monkeypatch, tmp_path):
    """No previous edition files at all yet (a brand new install) must not
    crash -- the front page is just today, same as the old behaviour."""
    root = _make_root(tmp_path)
    editions_dir = root / "data" / "editions"
    editions_dir.mkdir(parents=True)
    edition = _edition_with_story("2026-09-07", "OnlyTodayStory")
    (editions_dir / "2026-09-07.json").write_text(json.dumps(edition), encoding="utf-8")

    assert cli.main(["rebuild", "--root", str(root)]) == 0

    index_html = (root / "index.html").read_text(encoding="utf-8")
    assert "OnlyTodayStory" in index_html
