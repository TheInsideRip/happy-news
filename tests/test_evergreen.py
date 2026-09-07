"""feeds/evergreen.yaml is the last line of defence at tier 5 -- when the
live pipeline has found nothing, these are the only stories left standing
between the reader and a blank page, and they render with a STILL TRUE
stamp. That makes the file itself part of the product: it must always
parse, every entry must be complete, every label must be real, and every
url must at least be shaped like a live https link."""
from __future__ import annotations

import yaml

from happy_news.config import PACKAGE_ROOT

REQUIRED_FIELDS = ("title", "url", "source", "label", "summary")
MINIMUM_ENTRIES = 40


def _load_stories() -> list[dict]:
    path = PACKAGE_ROOT / "feeds" / "evergreen.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["stories"]


def _allowed_labels() -> set[str]:
    path = PACKAGE_ROOT / "feeds" / "editorial.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return set(data["labels"])


def test_evergreen_yaml_parses_and_has_at_least_forty_entries():
    stories = _load_stories()
    assert isinstance(stories, list)
    assert len(stories) >= MINIMUM_ENTRIES


def test_every_entry_has_all_required_fields_non_empty():
    for story in _load_stories():
        for field in REQUIRED_FIELDS:
            value = story.get(field)
            assert isinstance(value, str) and value.strip(), (
                f"{story.get('title', '<untitled>')!r} is missing a non-empty {field!r}"
            )


def test_every_label_is_in_the_allowed_list():
    allowed = _allowed_labels()
    for story in _load_stories():
        label = story["label"]
        assert label in allowed, f"{story['title']!r} has an unknown label {label!r}"


def test_every_url_starts_with_https():
    for story in _load_stories():
        url = story["url"]
        assert url.startswith("https://"), f"{story['title']!r} has a non-https url {url!r}"


def test_no_duplicate_urls():
    stories = _load_stories()
    urls = [story["url"] for story in stories]
    assert len(urls) == len(set(urls)), "evergreen.yaml has duplicate urls"
