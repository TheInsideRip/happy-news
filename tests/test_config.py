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


def _write_config(tmp_path, editorial: str):
    feeds = tmp_path / "feeds"
    feeds.mkdir(exist_ok=True)
    (feeds / "sources.yaml").write_text("feeds: []\n", encoding="utf-8")
    (feeds / "editorial.yaml").write_text(editorial, encoding="utf-8")
    (feeds / "evergreen.yaml").write_text("stories: []\n", encoding="utf-8")
    return tmp_path


def test_missing_banned_terms_is_a_hard_error(tmp_path):
    """`editorial_cfg.get("banned_terms", [])` used to silently disable the
    politics filter if the YAML key were ever renamed: an empty list matches
    nothing. The filter is the product's soul -- refuse to start."""
    _write_config(tmp_path, "labels: [earth]\noutcome_overrides: []\n")
    with pytest.raises(ValueError, match="banned_terms"):
        config.load(tmp_path)


def test_empty_banned_terms_is_a_hard_error(tmp_path):
    _write_config(tmp_path, "labels: [earth]\nbanned_terms: []\noutcome_overrides: []\n")
    with pytest.raises(ValueError, match="banned_terms"):
        config.load(tmp_path)


def test_null_banned_terms_is_a_hard_error(tmp_path):
    _write_config(tmp_path, "labels: [earth]\nbanned_terms:\noutcome_overrides: []\n")
    with pytest.raises(ValueError, match="banned_terms"):
        config.load(tmp_path)


def test_the_real_shipped_editorial_yaml_has_banned_terms():
    """The live config must satisfy the rule it enforces."""
    cfg = config.load(config.PACKAGE_ROOT)
    assert cfg.editorial["banned_terms"]
