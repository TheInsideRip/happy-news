from happy_news import normalize as n


def test_url_key_strips_tracking_and_www_and_slash():
    a = "https://www.Example.com/story/whales/?utm_source=rss&utm_medium=feed#top"
    b = "https://example.com/story/whales"
    assert n.url_key(a) == n.url_key(b)


def test_url_key_keeps_non_tracking_params():
    key = n.url_key("https://example.com/index.php?p=123&utm_campaign=x")
    assert "p=123" in key
    assert "utm_campaign" not in key


def test_url_key_distinguishes_different_paths():
    assert n.url_key("https://example.com/a") != n.url_key("https://example.com/b")


def test_title_key_ignores_case_and_punctuation():
    assert n.title_key("Whales Recover!") == n.title_key("whales recover")


def test_title_key_distinguishes_real_differences():
    assert n.title_key("Whales recover in Florida") != n.title_key("Whales recover in Australia")


def test_tokens_drop_stopwords_and_short_words():
    assert n.tokens("The whales of the sea are recovering") == ["recovering", "sea", "whales"]
