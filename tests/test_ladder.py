from datetime import datetime, timedelta, timezone

import pytest

from happy_news import ladder
from happy_news.dedup import Memory
from happy_news.fetch import Candidate

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
ED = {"banned_terms": ["election"], "outcome_overrides": [], "labels": ["earth", "world"]}
EVERGREEN = [{"title": "Ozone healing", "url": "https://a.com/oz", "source": "UNEP",
              "label": "earth", "summary": "Recovering."}]


def cand(title, hours_old=2, url=None, priority=False):
    # The brief's own helper used NOW.replace(hour=12 - hours_old), which
    # raises ValueError for any hours_old outside roughly -11..12 (e.g. the
    # brief's own hours_old=24*9=216 in test_ladder_reaches_back_in_time_
    # before_giving_up). timedelta works for any magnitude.
    return Candidate(title, url or f"https://a.com/{abs(hash(title))}", "Src",
                     NOW - timedelta(hours=hours_old), "blurb", priority=priority)


def picker(story):
    def ask(pool, recent_titles):
        return [story]
    return ask


def test_tier1_publishes_a_fresh_story(tmp_path):
    story = {"title": "Turtles recover", "url": "https://a.com/t", "source": "BBC",
             "label": "earth", "summary": "Good.", "why_good": "It is good."}
    result = ladder.select(candidates=[cand("Turtles recover", priority=True,
                                            url="https://a.com/t")],
                           memory=Memory(tmp_path / "s.jsonl"), editorial_cfg=ED,
                           evergreen=EVERGREEN, ask_fn=picker(story), now=NOW)
    assert result.tier == 1
    assert result.story["title"] == "Turtles recover"
    assert not result.evergreen


def test_tier1_ignores_a_fresh_but_non_priority_candidate(tmp_path):
    """Tier 1 means 'a dedicated priority outlet had something today', not
    'anything surfaced in the last 48 hours'. A fresh candidate whose source
    is not flagged priority=True must not satisfy tier 1, even though it
    would otherwise be a perfect tier-1 match on timing alone."""
    story = {"title": "Turtles recover", "url": "https://a.com/t", "source": "BBC",
             "label": "earth", "summary": "Good.", "why_good": "It is good."}
    result = ladder.select(candidates=[cand("Turtles recover", priority=False,
                                            url="https://a.com/t")],
                           memory=Memory(tmp_path / "s.jsonl"), editorial_cfg=ED,
                           evergreen=EVERGREEN, ask_fn=picker(story), now=NOW)
    assert result.tier != 1


def test_same_non_priority_candidate_is_considered_at_tier2(tmp_path):
    """The exact candidate tier 1 must reject on priority grounds alone is
    still found once the ladder reaches tier 2, which does not filter by
    priority -- only the time window changes."""
    story = {"title": "Turtles recover", "url": "https://a.com/t", "source": "BBC",
             "label": "earth", "summary": "Good.", "why_good": "It is good."}
    result = ladder.select(candidates=[cand("Turtles recover", priority=False,
                                            url="https://a.com/t")],
                           memory=Memory(tmp_path / "s.jsonl"), editorial_cfg=ED,
                           evergreen=EVERGREEN, ask_fn=picker(story), now=NOW)
    assert result.tier == 2
    assert result.story["title"] == "Turtles recover"
    assert not result.evergreen


def test_prefilter_enforces_priority_only_when_the_tier_asks_for_it(tmp_path):
    """Direct unit test of _prefilter's new priority_only parameter, isolated
    from timing/window concerns: a tier-1-shaped call (priority_only=True)
    must drop the non-priority candidate; a tier-2-shaped call
    (priority_only=False) must keep both."""
    memory = Memory(tmp_path / "s.jsonl")
    non_priority = cand("Coral reef recovers", priority=False)
    priority = cand("Turtles saved from extinction", priority=True)
    pool = [non_priority, priority]

    tier1_pool = ladder._prefilter(pool, memory, ED, allow_near=False, priority_only=True)
    assert tier1_pool == [priority]

    tier2_pool = ladder._prefilter(pool, memory, ED, allow_near=False, priority_only=False)
    assert tier2_pool == [non_priority, priority]


def test_ladder_does_not_crash_or_hang_when_every_priority_feed_is_empty(tmp_path):
    """Judgement call: if every priority feed is down or empty, no candidate
    anywhere in the pool carries priority=True. Tier 1's pool must correctly
    come up empty -- not crash, not hang, not skip a tier -- and the ladder
    must fall straight through to tier 2 exactly as it would for any other
    empty-tier-1-pool case."""
    story = {"title": "Coral reef recovers", "url": "https://a.com/c", "source": "BBC",
             "label": "earth", "summary": "Good.", "why_good": "It is good."}
    candidates = [
        cand("Coral reef recovers", priority=False, url="https://a.com/c"),
        cand("Ocean cleanup expands", priority=False, url="https://a.com/ocean"),
    ]
    result = ladder.select(candidates=candidates,
                           memory=Memory(tmp_path / "s.jsonl"), editorial_cfg=ED,
                           evergreen=EVERGREEN, ask_fn=picker(story), now=NOW)
    assert result.tier == 2
    assert result.story is not None
    assert not result.evergreen


def test_ladder_reaches_back_in_time_before_giving_up(tmp_path):
    """A story from 9 days ago that she has never seen is still new to her."""
    story = {"title": "Old but unseen", "url": "https://a.com/o", "source": "BBC",
             "label": "earth", "summary": "Good.", "why_good": "y"}
    result = ladder.select(candidates=[cand("Old but unseen", hours_old=24 * 9,
                                            url="https://a.com/o")],
                           memory=Memory(tmp_path / "s.jsonl"), editorial_cfg=ED,
                           evergreen=EVERGREEN, ask_fn=picker(story), now=NOW)
    assert result.story["title"] == "Old but unseen"
    assert result.tier >= 2


def test_falls_through_to_evergreen_when_nothing_qualifies(tmp_path):
    def ask(pool, recent_titles):
        return []
    result = ladder.select(candidates=[], memory=Memory(tmp_path / "s.jsonl"),
                           editorial_cfg=ED, evergreen=EVERGREEN, ask_fn=ask, now=NOW)
    assert result.evergreen
    assert result.tier == 5
    assert result.story["title"] == "Ozone healing"


def test_exhausted_ladder_returns_no_story_and_a_note(tmp_path):
    def ask(pool, recent_titles):
        return []
    result = ladder.select(candidates=[], memory=Memory(tmp_path / "s.jsonl"),
                           editorial_cfg=ED, evergreen=[], ask_fn=ask, now=NOW)
    assert result.story is None
    assert "quiet" in result.note.lower()


def test_politics_filter_reapplied_after_the_model_answers(tmp_path):
    """The model's own output is filtered in code, not trusted.

    The candidate text itself must stay clean (so it survives the candidate-
    level _prefilter and actually reaches ask_fn) -- otherwise this test would
    pass even if the post-model _survives() check were deleted, because the
    candidate would never make it into the pool in the first place.
    """
    candidate = cand("Local turnout drive expands civic participation",
                     url="https://a.com/e")
    bad = {"title": "Election turnout soars", "url": "https://a.com/e", "source": "BBC",
           "label": "government", "summary": "s", "why_good": "y"}
    result = ladder.select(candidates=[candidate],
                           memory=Memory(tmp_path / "s.jsonl"), editorial_cfg=ED,
                           evergreen=EVERGREEN, ask_fn=picker(bad), now=NOW)
    assert result.story["title"] != "Election turnout soars"


def test_blocked_story_is_rejected_even_if_the_model_picks_it(tmp_path):
    """A story already in memory must be rejected even if it slips past the
    candidate-level prefilter -- the candidate here is a different URL/title
    than the one memory has seen, so it reaches ask_fn; the model then hands
    back the already-seen story anyway, and _survives() must still catch it.
    (If the candidate itself matched memory it would be dropped by
    _prefilter before ask_fn was ever called, and this test would pass even
    with the post-model check deleted.)
    """
    memory = Memory(tmp_path / "s.jsonl")
    memory.remember("https://a.com/seen", "Already shown", "2026-09-07", "morning")
    candidate = cand("Fresh sounding headline", url="https://a.com/fresh")
    seen = {"title": "Already shown", "url": "https://a.com/fresh", "source": "BBC",
            "label": "earth", "summary": "s", "why_good": "y"}
    result = ladder.select(candidates=[candidate], memory=memory, editorial_cfg=ED,
                           evergreen=EVERGREEN, ask_fn=picker(seen), now=NOW)
    assert result.story["title"] != "Already shown"


def test_tier_4_does_not_draw_on_the_evergreen_reserve():
    """Ruling: only tier 5 draws on the reserve. Tier 4 (90 days through real
    feeds) is a warning; only falling to the timeless reserve is an error.
    With tier 4 wrongly allowed to use the reserve,
    test_falls_through_to_evergreen_when_nothing_qualifies would return tier 4
    instead of 5."""
    by_number = {t.number: t for t in ladder.TIERS}
    assert by_number[4].evergreen is False
    assert by_number[4].hours == 24 * 90
    assert by_number[5].evergreen is True
    assert by_number[5].hours is None


def test_prefilter_blocks_and_demotes_consistently_regardless_of_allow_near(tmp_path):
    """The quality bar never moves between tiers: hard-blocked and
    politically-banned candidates are excluded whether or not the tier allows
    near-duplicates. Only near-duplicates are allowed through, and only when
    the tier permits it -- and when they are, they land after fresh (kept)
    candidates so the model sees the better ones first."""
    memory = Memory(tmp_path / "s.jsonl")
    memory.remember("https://a.com/seen", "Already shown", "2026-09-07", "morning")
    memory.remember("https://a.com/turtle-old", "Turtles saved from extinction",
                     "2026-08-01", "morning")

    blocked = cand("Already shown", url="https://a.com/seen")
    political = cand("Election turnout soars nationwide")
    near_dup = cand("Turtles saved from extinction event", url="https://a.com/turtle-new")
    fresh = cand("Coral reef fully recovers")

    pool = [blocked, political, near_dup, fresh]

    kept_only = ladder._prefilter(pool, memory, ED, allow_near=False)
    assert kept_only == [fresh]

    with_near = ladder._prefilter(pool, memory, ED, allow_near=True)
    assert with_near == [fresh, near_dup]


def test_ask_fn_receives_pool_and_recent_titles(tmp_path):
    """select() must call ask_fn(pool, memory.recent_titles()) -- both the
    live candidate pool and the do-not-repeat list, not just a prompt."""
    memory = Memory(tmp_path / "s.jsonl")
    memory.remember("https://a.com/old", "Old story", "2026-09-06", "morning")
    calls = []

    def ask(pool, recent_titles):
        calls.append((list(pool), list(recent_titles)))
        return []

    ladder.select(candidates=[cand("Fresh story")], memory=memory, editorial_cfg=ED,
                  evergreen=EVERGREEN, ask_fn=ask, now=NOW)

    assert calls, "ask_fn should have been called at least once"
    pool, recent = calls[0]
    assert any(c.title == "Fresh story" for c in pool)
    assert recent == ["Old story"]


def test_evergreen_source_dict_is_not_mutated(tmp_path):
    """select() builds the returned story as story['label'] = ... on the
    dict it hands back. The reserve is loaded once by config.load() and
    reused across runs, so that assignment must never touch the caller's
    original evergreen list."""
    reserve_item = {"title": "Ozone healing", "url": "https://a.com/oz", "source": "UNEP",
                     "label": "not-a-real-label", "summary": "Recovering."}
    evergreen = [reserve_item]

    def ask(pool, recent_titles):
        return []

    result = ladder.select(candidates=[], memory=Memory(tmp_path / "s.jsonl"),
                           editorial_cfg=ED, evergreen=evergreen, ask_fn=ask, now=NOW)

    assert result.story["label"] == "world"
    assert reserve_item["label"] == "not-a-real-label"
    assert evergreen[0]["label"] == "not-a-real-label"


# ---------------------------------------------------------------------------
# I2: the published URL must come from the candidate pool.
#
# _survives re-checked politics and dedup but never provenance, and cli
# treated "no candidate matches this URL" as normal, silently blanking
# age_text. So a hallucinated or mistyped URL published as a live link with
# no timestamp -- and memory.remember() then stored a key matching no real
# feed item, leaving the real article free to be picked again later. That
# breaks the never-repeat promise silently, which is the worst way to break
# it.
# ---------------------------------------------------------------------------


def test_a_hallucinated_url_is_rejected_and_the_next_candidate_is_used(tmp_path):
    real = cand("Turtles recover", priority=True, url="https://a.com/turtles")
    hallucinated = {"title": "Turtles recover", "url": "https://a.com/not-a-real-link",
                    "source": "BBC", "label": "earth", "summary": "Good.", "why_good": "y"}
    genuine = {"title": "Turtles recover", "url": "https://a.com/turtles",
               "source": "BBC", "label": "earth", "summary": "Good.", "why_good": "y"}

    def ask(pool, recent_titles):
        return [hallucinated, genuine]

    result = ladder.select(candidates=[real], memory=Memory(tmp_path / "s.jsonl"),
                           editorial_cfg=ED, evergreen=EVERGREEN, ask_fn=ask, now=NOW)

    assert result.story["url"] == "https://a.com/turtles"
    assert result.tier == 1


def test_a_pick_with_no_matching_candidate_never_publishes(tmp_path):
    """Nothing in the pool matches, so the ladder must fall all the way
    through to the evergreen reserve rather than publish a link that came
    from nowhere."""
    real = cand("Turtles recover", priority=True, url="https://a.com/turtles")
    invented = {"title": "Something wonderful", "url": "https://invented.example/story",
                "source": "BBC", "label": "earth", "summary": "Good.", "why_good": "y"}

    result = ladder.select(candidates=[real], memory=Memory(tmp_path / "s.jsonl"),
                           editorial_cfg=ED, evergreen=EVERGREEN,
                           ask_fn=picker(invented), now=NOW)

    assert result.evergreen is True
    assert result.story["url"] == "https://a.com/oz"


def test_provenance_matches_on_url_key_not_raw_string(tmp_path):
    """The model copies the URL out of the prompt, which may differ from the
    feed's raw link by tracking parameters or a trailing slash. Those are the
    same article and must not be rejected."""
    real = cand("Turtles recover", priority=True,
                url="https://www.a.com/turtles/?utm_source=rss")
    story = {"title": "Turtles recover", "url": "https://a.com/turtles",
             "source": "BBC", "label": "earth", "summary": "Good.", "why_good": "y"}

    result = ladder.select(candidates=[real], memory=Memory(tmp_path / "s.jsonl"),
                           editorial_cfg=ED, evergreen=EVERGREEN,
                           ask_fn=picker(story), now=NOW)

    assert result.tier == 1
    assert result.story["title"] == "Turtles recover"


def test_survives_rejects_a_url_outside_the_pool(tmp_path):
    """Direct unit test of the provenance clause itself."""
    memory = Memory(tmp_path / "s.jsonl")
    story = {"title": "Turtles recover", "url": "https://a.com/turtles",
             "summary": "Good."}

    assert ladder._survives(story, memory, ED, {"a.com/turtles"}) is True
    assert ladder._survives(story, memory, ED, {"a.com/something-else"}) is False
    assert ladder._survives(story, memory, ED, set()) is False


# ---------------------------------------------------------------------------
# The politics filter must never fail open.
# ---------------------------------------------------------------------------


def test_an_empty_banned_terms_list_is_a_hard_error_not_a_disabled_filter(tmp_path):
    """editorial_cfg.get("banned_terms", []) silently disabled the whole
    politics filter if the YAML key were renamed or emptied: an empty list
    matches nothing, so every political story sails through with no error and
    no warning. The filter is the product's soul -- it must fail loudly."""
    candidate = cand("Election turnout soars nationwide", priority=True,
                     url="https://a.com/e")
    story = {"title": "Election turnout soars", "url": "https://a.com/e",
             "source": "BBC", "label": "world", "summary": "s", "why_good": "y"}

    for broken in ({"labels": ["world"], "outcome_overrides": []},
                   {"labels": ["world"], "banned_terms": [], "outcome_overrides": []},
                   {"labels": ["world"], "banned_terms": None, "outcome_overrides": []}):
        with pytest.raises(ValueError, match="banned_terms"):
            ladder.select(candidates=[candidate], memory=Memory(tmp_path / "s.jsonl"),
                          editorial_cfg=broken, evergreen=EVERGREEN,
                          ask_fn=picker(story), now=NOW)
