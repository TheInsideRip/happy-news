import pytest
from happy_news import render

STORY = {
    "title": "Sea turtle nests hit a record",
    "url": "https://example.com/turtles",
    "source": "BBC",
    "label": "animals",
    "summary": "Volunteers counted more nests than in any year since the survey began.",
    "age_text": "2 hours ago",
}

DAY = {
    "date": "2026-09-07",
    "slots": {
        "morning": {"published_at": "2026-09-07T08:03:41-04:00", "note": None, "stories": [STORY]},
    },
}


def test_page_contains_the_masthead_and_times():
    html = render.render_day(DAY, is_today=True)
    assert "Stacey Happy News" in html
    assert "Satcey" not in html
    for t in ("8:00", "2:00", "7:00"):
        assert t in html


def test_page_shows_last_updated():
    assert "Last updated" in render.render_day(DAY, is_today=True)


def test_newest_slot_renders_first():
    day = {"date": "2026-09-07", "slots": {
        "morning": {"published_at": "a", "note": None, "stories": [dict(STORY, title="MORNINGSTORY")]},
        "evening": {"published_at": "b", "note": None, "stories": [dict(STORY, title="EVENINGSTORY")]},
    }}
    html = render.render_day(day, is_today=True)
    assert html.index("EVENINGSTORY") < html.index("MORNINGSTORY")


def test_empty_slot_renders_its_note_instead_of_vanishing():
    day = {"date": "2026-09-07", "slots": {
        "morning": {"published_at": "a",
                    "note": "A quiet morning. Nothing new made the cut.",
                    "stories": []},
    }}
    html = render.render_day(day, is_today=True)
    assert "A quiet morning" in html


def test_evergreen_story_is_labelled_still_true():
    day = {"date": "2026-09-07", "slots": {
        "morning": {"published_at": "a", "note": None,
                    "stories": [dict(STORY, evergreen=True)]},
    }}
    assert "STILL TRUE" in render.render_day(day, is_today=True)


def test_hostile_story_text_is_escaped():
    day = {"date": "2026-09-07", "slots": {
        "morning": {"published_at": "a", "note": None, "stories": [
            dict(STORY, title="<script>alert(1)</script>")]},
    }}
    html = render.render_day(day, is_today=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_validate_rejects_a_page_with_no_story():
    empty = {"date": "2026-09-07", "slots": {}}
    with pytest.raises(ValueError):
        render.validate(render.render_day(empty, is_today=True))


def test_validate_rejects_a_non_http_url():
    day = {"date": "2026-09-07", "slots": {
        "morning": {"published_at": "a", "note": None, "stories": [
            dict(STORY, url="javascript:alert(1)")]},
    }}
    with pytest.raises(ValueError):
        render.validate(render.render_day(day, is_today=True))


def test_validate_rejects_a_whitespace_only_summary():
    day = {"date": "2026-09-07", "slots": {
        "morning": {"published_at": "a", "note": None, "stories": [
            dict(STORY, summary="   ")]},
    }}
    with pytest.raises(ValueError):
        render.validate(render.render_day(day, is_today=True))


def test_archive_index_lists_days_newest_first():
    html = render.render_archive_index(["2026-09-05", "2026-09-07", "2026-09-06"])
    assert html.index("2026-09-07") < html.index("2026-09-05")


def test_archive_page_renders_without_crashing():
    html = render.render_day(DAY, is_today=False)
    assert "Monday, September 7" in html
    assert '../assets/style.css' in html
    assert 'href="assets/style.css"' not in html


def test_slot_time_falls_back_to_published_at_when_no_time_text():
    day = {"date": "2026-09-07", "slots": {
        "morning": {"published_at": "2026-09-07T08:03:41-04:00", "note": None,
                    "stories": [STORY]},
    }}
    html = render.render_day(day, is_today=True)
    assert "8:03 am" in html


def test_hostile_summary_source_and_label_are_escaped():
    payload = "<script>alert(1)</script>"
    day = {"date": "2026-09-07", "slots": {
        "morning": {"published_at": "a", "note": None, "stories": [
            dict(STORY, summary=payload, source=payload, label=payload)]},
    }}
    html = render.render_day(day, is_today=True)
    assert payload not in html
    assert html.count("&lt;script&gt;") >= 3
