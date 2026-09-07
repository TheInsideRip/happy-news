import pytest
from pathlib import Path
from happy_news import config


def test_load_reads_all_three_files(tmp_path):
    feeds = tmp_path / "feeds"
    feeds.mkdir()
    (feeds / "sources.yaml").write_text("feeds:\n  - url: https://example.com/rss\n    name: Example\n    priority: true\n", encoding="utf-8")
    (feeds / "editorial.yaml").write_text("banned_terms: [election]\noutcome_overrides: [convicted]\nlabels: [earth, world]\n", encoding="utf-8")
    (feeds / "evergreen.yaml").write_text("stories:\n  - title: Ozone layer healing\n    url: https://example.com/ozone\n    source: BBC\n    label: earth\n    summary: It is recovering.\n", encoding="utf-8")

    cfg = config.load(tmp_path)

    assert cfg.sources["feeds"][0]["name"] == "Example"
    assert "election" in cfg.editorial["banned_terms"]
    assert cfg.evergreen[0]["title"] == "Ozone layer healing"


def test_missing_file_names_the_path(tmp_path):
    (tmp_path / "feeds").mkdir()
    with pytest.raises(FileNotFoundError) as exc:
        config.load(tmp_path)
    assert "sources.yaml" in str(exc.value)
