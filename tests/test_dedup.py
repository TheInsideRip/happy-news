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
