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


# ---------------------------------------------------------------------------
# render_front: today plus previous days, newest first, on one page.
# render_day itself must keep working unchanged for archive pages -- every
# test above this line still exercises the untouched render_day directly.
# ---------------------------------------------------------------------------

YESTERDAY = {
    "date": "2026-09-06",
    "slots": {
        "evening": {"published_at": "2026-09-06T19:00:00-04:00", "note": None,
                    "stories": [dict(STORY, title="YESTERDAYSTORY")]},
    },
}

TWO_DAYS_AGO = {
    "date": "2026-09-05",
    "slots": {
        "morning": {"published_at": "2026-09-05T08:00:00-04:00", "note": None,
                    "stories": [dict(STORY, title="TWODAYSAGOSTORY")]},
    },
}


def test_render_front_is_a_single_page_with_today_first():
    html = render.render_front([DAY, YESTERDAY])
    assert html.count("<!doctype html>") == 1
    assert html.count("Stacey<br>Happy News") == 1
    assert html.index("Sea turtle nests hit a record") < html.index("YESTERDAYSTORY")


def test_render_front_shows_last_updated_for_today():
    html = render.render_front([DAY])
    assert "Last updated" in html


def test_render_front_gives_each_earlier_day_a_date_heading():
    html = render.render_front([DAY, YESTERDAY, TWO_DAYS_AGO])
    assert "Sunday, September 6" in html
    assert "Saturday, September 5" in html


def test_render_front_with_only_today_matches_render_day_content():
    html = render.render_front([DAY])
    assert "Sea turtle nests hit a record" in html
    assert "Last updated" in html
    assert "Saturday" not in html and "Sunday" not in html


def test_render_front_still_links_to_the_archive():
    html = render.render_front([DAY, YESTERDAY])
    assert 'href="archive/"' in html


def test_render_front_escapes_hostile_text_in_an_earlier_day():
    payload = "<script>alert(1)</script>"
    hostile_yesterday = {
        "date": "2026-09-06",
        "slots": {"evening": {"published_at": "a", "note": None,
                               "stories": [dict(STORY, title=payload)]}},
    }
    html = render.render_front([DAY, hostile_yesterday])
    assert payload not in html
    assert "&lt;script&gt;" in html


def test_render_front_evergreen_story_in_an_earlier_day_is_still_true():
    evergreen_yesterday = {
        "date": "2026-09-06",
        "slots": {"evening": {"published_at": "a", "note": None,
                               "stories": [dict(STORY, evergreen=True)]}},
    }
    html = render.render_front([DAY, evergreen_yesterday])
    assert "STILL TRUE" in html


def test_validate_passes_a_clean_multi_day_front_page():
    render.validate(render.render_front([DAY, YESTERDAY, TWO_DAYS_AGO]))


def test_validate_rejects_a_whitespace_only_summary_in_an_earlier_day():
    bad_yesterday = {
        "date": "2026-09-06",
        "slots": {"evening": {"published_at": "a", "note": None,
                               "stories": [dict(STORY, summary="   ")]}},
    }
    with pytest.raises(ValueError):
        render.validate(render.render_front([DAY, bad_yesterday]))


def test_validate_rejects_a_non_http_link_in_an_earlier_day():
    bad_yesterday = {
        "date": "2026-09-06",
        "slots": {"evening": {"published_at": "a", "note": None,
                               "stories": [dict(STORY, url="javascript:alert(1)")]}},
    }
    with pytest.raises(ValueError):
        render.validate(render.render_front([DAY, bad_yesterday]))


def test_validate_rejects_a_front_page_with_no_story_anywhere():
    empty = {"date": "2026-09-07", "slots": {}}
    empty_yesterday = {"date": "2026-09-06", "slots": {}}
    with pytest.raises(ValueError):
        render.validate(render.render_front([empty, empty_yesterday]))


def test_render_day_is_unaffected_by_render_front_existing():
    """render_day must still work exactly as before, unchanged, for archive
    pages -- it renders one day, never a stack of days."""
    html = render.render_day(DAY, is_today=False)
    assert "Monday, September 7" in html
    assert '../assets/style.css' in html


# ---------------------------------------------------------------------------
# C2: "Last updated" must carry the DAY, not just the clock time.
#
# The reader's only healthy/stale signal was `Last updated 5:10 pm`. If the
# laptop is off or asleep for a day or a week, no run happens -- so there is
# no toast and no log line either -- and the page stays byte-identical to a
# fresh one. Both of the spec's two independent places go silent at once for
# the single most likely real-world failure. A day-stamped heading makes the
# page itself say how old it is, without a run having to happen at all.
# ---------------------------------------------------------------------------


def test_last_updated_names_the_day_not_only_the_time():
    html = render.render_day(dict(DAY, updated_text="5:10 pm"), is_today=True)
    assert "Last updated Monday 7 Sep, 5:10 pm" in html


def test_render_front_last_updated_names_the_day_not_only_the_time():
    html = render.render_front([dict(DAY, updated_text="5:10 pm")])
    assert "Last updated Monday 7 Sep, 5:10 pm" in html


def test_a_week_old_page_does_not_look_identical_to_a_fresh_one():
    """The exact failure: same slot, same time of day, seven days apart. If
    the heading only carried the time these two pages would be identical."""
    fresh = render.render_front([dict(DAY, updated_text="5:10 pm")])
    stale = render.render_front([
        dict(DAY, date="2026-08-31", updated_text="5:10 pm"),
    ])
    assert "Last updated Monday 7 Sep" in fresh
    assert "Last updated Monday 31 Aug" in stale
    assert fresh != stale


def test_last_updated_falls_back_to_the_day_alone_when_no_time_is_known():
    day = {"date": "2026-09-07", "slots": {
        "morning": {"note": None, "stories": [STORY]},
    }}
    html = render.render_day(day, is_today=True)
    assert "Last updated Monday 7 Sep" in html
    assert "Last updated Monday 7 Sep," not in html  # no dangling comma


def test_last_updated_survives_an_unparseable_edition_date():
    """A malformed date must degrade to the old time-only heading, never
    crash the page."""
    html = render.render_day(
        {"date": "not-a-date", "updated_text": "5:10 pm",
         "slots": {"morning": {"note": None, "stories": [STORY]}}},
        is_today=True,
    )
    assert "Last updated 5:10 pm" in html

    html = render.render_front([
        {"date": "not-a-date", "updated_text": "5:10 pm",
         "slots": {"morning": {"note": None, "stories": [STORY]}}},
    ])
    assert "Last updated 5:10 pm" in html


def test_validate_rejects_a_javascript_url_dressed_up_as_html():
    """The old `href.endswith(".html")` escape hatch accepted ANY scheme, so
    a javascript: URL ending in .html sailed through validation and shipped
    as a live link on the page."""
    page = render.render_day({"date": "2026-09-07", "slots": {
        "morning": {"published_at": "a", "note": None, "stories": [
            dict(STORY, url="javascript:alert(1)//x.html")]},
    }}, is_today=True)
    with pytest.raises(ValueError, match="non-http link"):
        render.validate(page)


def test_validate_rejects_other_schemes_ending_in_html():
    for hostile in ("data:text/html,<script>x</script>#x.html",
                    "file:///C:/Windows/system32/x.html",
                    "vbscript:msgbox(1)/x.html"):
        page = render.render_day({"date": "2026-09-07", "slots": {
            "morning": {"published_at": "a", "note": None,
                        "stories": [dict(STORY, url=hostile)]},
        }}, is_today=True)
        with pytest.raises(ValueError, match="non-http link"):
            render.validate(page)


def test_validate_still_accepts_the_pages_own_nav_links():
    render.validate(render.render_day(DAY, is_today=True))
    render.validate(render.render_day(DAY, is_today=False))
    render.validate(render.render_front([DAY]))
