from happy_news.dedup import Memory, jaccard, SOFT_THRESHOLD


def make(tmp_path):
    return Memory(tmp_path / "seen.jsonl")


def test_exact_url_is_blocked_forever(tmp_path):
    mem = make(tmp_path)
    mem.remember("https://example.com/whales", "Whales recover", "2026-09-07", "morning")
    assert mem.is_blocked("https://www.example.com/whales/?utm_source=rss", "A totally different headline")


def test_exact_title_is_blocked_forever(tmp_path):
    mem = make(tmp_path)
    mem.remember("https://a.com/1", "Whales recover in the Pacific", "2026-09-07", "morning")
    assert mem.is_blocked("https://b.com/2", "whales recover in the pacific!")


def test_unrelated_story_is_not_blocked(tmp_path):
    mem = make(tmp_path)
    mem.remember("https://a.com/1", "Whales recover", "2026-09-07", "morning")
    assert not mem.is_blocked("https://b.com/2", "Library lends tools")


def test_florida_and_australia_are_NOT_blocked(tmp_path):
    """Two different stories that share most of their words. The original 0.60
    fuzzy threshold scored these at 0.67 and would have destroyed one."""
    mem = make(tmp_path)
    mem.remember("https://a.com/fl", "Sea turtle numbers recover in Florida", "2026-09-07", "morning")
    assert not mem.is_blocked("https://b.com/au", "Sea turtle numbers recover in Australia")


def test_near_duplicate_is_advisory_not_a_block(tmp_path):
    mem = make(tmp_path)
    mem.remember("https://a.com/1", "Humpback whale numbers recover strongly worldwide", "2026-09-07", "morning")
    title = "Humpback whale numbers recover strongly worldwide today"
    assert mem.is_near_duplicate(title)
    assert not mem.is_blocked("https://b.com/2", title)


def test_jaccard_boundaries():
    a = ["alpha", "beta", "gamma", "delta"]
    assert jaccard(a, a) == 1.0
    assert jaccard(a, ["epsilon"]) == 0.0
    assert jaccard([], a) == 0.0


def test_soft_threshold_is_strict_enough():
    assert SOFT_THRESHOLD == 0.75


def test_recent_titles_returns_newest_first(tmp_path):
    mem = make(tmp_path)
    for i in range(5):
        mem.remember(f"https://a.com/{i}", f"Story number {i}", "2026-09-07", "morning")
    assert mem.recent_titles(limit=2) == ["Story number 4", "Story number 3"]


def test_no_duplicate_on_first_entry(tmp_path):
    """Cache length must match remember() calls. First entry must not be counted twice."""
    mem = make(tmp_path)
    for i in range(5):
        mem.remember(f"https://a.com/{i}", f"Story {i}", "2026-09-07", "morning")
    # Cache should have exactly 5 entries, no duplicates
    assert len(mem._load()) == 5
    # All 5 titles in order, newest first
    titles = mem.recent_titles(limit=100)
    assert len(titles) == 5
    assert titles == ["Story 4", "Story 3", "Story 2", "Story 1", "Story 0"]


def test_is_near_duplicate_respects_18_month_window(tmp_path):
    """Old entries outside the 548-day window must not trigger near_duplicate."""
    from datetime import date, timedelta
    mem = make(tmp_path)

    # Remember an entry from 600+ days ago
    old_date = (date.today() - timedelta(days=600)).isoformat()
    mem.remember("https://a.com/old", "Humpback whale numbers recover strongly worldwide today", old_date, "morning")

    # A title with high Jaccard similarity to the old entry
    similar_title = "Humpback whale numbers recover strongly worldwide"

    # Should NOT be marked as near_duplicate because the entry is outside the 548-day window
    assert not mem.is_near_duplicate(similar_title, within_days=548)

    # But it SHOULD be near_duplicate if we expand the window beyond 600 days
    assert mem.is_near_duplicate(similar_title, within_days=700)
