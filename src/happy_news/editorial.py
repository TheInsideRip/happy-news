"""The politics filter. Runs as a cheap prefilter AND again in code after the
model answers -- the rule is enforced, never merely requested."""
from __future__ import annotations

import re

FALLBACK_LABEL = "world"


def _matches_any(text_lower: str, phrases: list[str]) -> bool:
    for phrase in phrases:
        pattern = r"\b" + re.escape(phrase.lower()) + r"\b"
        if re.search(pattern, text_lower):
            return True
    return False


def politics_blocked(text: str, banned: list[str], overrides: list[str]) -> bool:
    """Reject when a banned term matches AND no outcome override matches."""
    low = text.lower()
    if _matches_any(low, overrides):
        return False
    return _matches_any(low, banned)


def label_is_known(label: str, labels: list[str]) -> bool:
    return label.strip().lower() in {l.lower() for l in labels}


def normalise_label(label: str, labels: list[str]) -> str:
    """Never reject a story for having an unfamiliar label -- fall back to
    'world'. The taxonomy labels stories; it must not filter them."""
    cleaned = (label or "").strip().lower()
    return cleaned if label_is_known(cleaned, labels) else FALLBACK_LABEL
