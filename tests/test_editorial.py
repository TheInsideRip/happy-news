import pytest
from happy_news import editorial

BANNED = ["election", "clash", "clashes", "scandal", "poll", "candidate", "primaries"]
OVERRIDES = ["ceasefire", "court ruled", "convicted", "agreement signed"]
LABELS = ["earth", "animals", "peace", "world"]


def blocked(text):
    return editorial.politics_blocked(text, BANNED, OVERRIDES)


def test_banned_term_blocks():
    assert blocked("Turnout soars in the national election")
    assert blocked("A scandal engulfs the ministry")


def test_override_rescues_a_finished_outcome():
    assert not blocked("After months of clashes, a ceasefire was signed")
    assert not blocked("Court ruled in favour of the river's clean-up")


def test_peace_story_survives_the_word_clash():
    """A ceasefire report almost always contains 'clash' in the same sentence
    that makes it good news. Without the override the peace label is unusable."""
    assert not blocked("Ceasefire holds after two years of border clashes")


def test_clean_text_is_not_blocked():
    assert not blocked("Sea turtle nests hit a record along a protected coastline")


def test_word_boundaries_prevent_false_positives():
    assert not blocked("The primary school planted a thousand trees")
    assert not blocked("A clashing colour scheme won the design prize")


def test_matching_is_case_insensitive():
    assert blocked("ELECTION results certified")


def test_unknown_label_falls_back_to_world():
    assert editorial.normalise_label("Animals", LABELS) == "animals"
    assert editorial.normalise_label("gastronomy", LABELS) == "world"
