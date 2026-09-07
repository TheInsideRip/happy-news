import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from happy_news import clock

ET = ZoneInfo("America/New_York")


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def test_slot_boundaries():
    assert clock.slot_for(at(2026, 9, 7, 7, 59)) is None
    assert clock.slot_for(at(2026, 9, 7, 8, 0)) == "morning"
    assert clock.slot_for(at(2026, 9, 7, 13, 59)) == "morning"
    assert clock.slot_for(at(2026, 9, 7, 14, 0)) == "afternoon"
    assert clock.slot_for(at(2026, 9, 7, 18, 59)) == "afternoon"
    assert clock.slot_for(at(2026, 9, 7, 19, 0)) == "evening"
    assert clock.slot_for(at(2026, 9, 7, 23, 59)) == "evening"
    assert clock.slot_for(at(2026, 9, 7, 3, 0)) is None


def test_slots_are_correct_on_both_dst_changeovers():
    # Spring forward 2026-03-08, fall back 2026-11-01. 8am local is 8am
    # local on both days; zoneinfo must absorb the offset change.
    assert clock.slot_for(at(2026, 3, 8, 8, 0)) == "morning"
    assert clock.slot_for(at(2026, 11, 1, 8, 0)) == "morning"
    assert at(2026, 3, 8, 8, 0).utcoffset().total_seconds() == -4 * 3600
    assert at(2026, 1, 8, 8, 0).utcoffset().total_seconds() == -5 * 3600


def test_already_published_true_when_slot_has_a_story(tmp_path):
    day = date(2026, 9, 7)
    (tmp_path / "2026-09-07.json").write_text(json.dumps({
        "date": "2026-09-07",
        "slots": {"morning": {"published_at": "x", "note": None,
                              "stories": [{"title": "t"}]}},
    }), encoding="utf-8")
    assert clock.already_published(tmp_path, day, "morning")
    assert not clock.already_published(tmp_path, day, "evening")


def test_empty_slot_does_not_count_as_published(tmp_path):
    """A drought writes an empty slot. Later runs in the same window must
    still be allowed to fill it."""
    day = date(2026, 9, 7)
    (tmp_path / "2026-09-07.json").write_text(json.dumps({
        "date": "2026-09-07",
        "slots": {"morning": {"published_at": "x",
                              "note": "A quiet morning. Nothing new made the cut.",
                              "stories": []}},
    }), encoding="utf-8")
    assert not clock.already_published(tmp_path, day, "morning")


def test_missing_file_is_not_published(tmp_path):
    assert not clock.already_published(tmp_path, date(2026, 9, 7), "morning")
