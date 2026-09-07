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


# ---------------------------------------------------------------------------
# R5: dedup is evadable by Unicode homoglyphs and decomposition. title_norm
# lowercased and stripped punctuation but never Unicode-normalized, so a
# visually-identical-but-differently-encoded headline produced a different
# title_key -- letting a previously-published headline slip back past the
# "never repeat" block. NFKC folds both an NFD-decomposed accent and a
# fullwidth-Unicode homoglyph swap into the same canonical form as the
# plain-ASCII original.
#
# NFKC does NOT unify every visual lookalike: a genuine cross-script
# confusable (Cyrillic 'е' U+0435 substituted for Latin 'e' U+0065) is a
# different letter with no Unicode equivalence to the Latin one at all, so
# it is untouched by any of NFC/NFD/NFKC/NFKD. Closing that specific gap
# needs a confusables-skeleton algorithm (Unicode TR39), not normalization,
# and is out of scope for this fix -- verified empirically below alongside
# what NFKC does fix, so the boundary of this fix is explicit and not
# silently overclaimed.
# ---------------------------------------------------------------------------


def test_title_key_survives_nfd_decomposition():
    """The same 'é' rendered two different ways: as the single precomposed
    codepoint (NFC, U+00E9) and as 'e' + a combining acute accent (NFD,
    U+0065 U+0301). They render identically and must hash the same."""
    nfc = "Café opens downtown"          # é as one codepoint
    nfd = "Café opens downtown"          # e + combining acute
    assert nfc != nfd  # different byte sequences going in
    assert n.title_key(nfc) == n.title_key(nfd)


def test_title_key_survives_a_fullwidth_homoglyph_swap():
    """Fullwidth Unicode forms (U+FF00 block) are a real, documented
    text-filter evasion technique and are exactly what NFKC's compatibility
    decomposition exists to fold back to their ordinary ASCII equivalents --
    unlike a cross-script confusable, this one IS a genuine Unicode
    equivalence."""
    fullwidth = "Ｗhales recover"          # fullwidth 'W'
    plain = "Whales recover"
    assert fullwidth != plain
    assert n.title_key(fullwidth) == n.title_key(plain)


def test_nfkc_does_not_unify_a_cross_script_cyrillic_confusable():
    """Documents the honest boundary of this fix: a Cyrillic 'е' (U+0435)
    substituted for a Latin 'e' is visually identical but a different
    letter in a different script, with no Unicode canonical or
    compatibility equivalence to the Latin one -- so it is NOT caught by
    title_norm's NFKC normalization. Closing this would need a
    confusables-skeleton check, not Unicode normalization."""
    cyrillic = "Whalеs recover"           # Cyrillic 'е', not Latin 'e'
    plain = "Whales recover"
    assert n.title_key(cyrillic) != n.title_key(plain)
