"""Five tiers of widening search.

A drought is a malfunction, not a news shortage. At one story per timeframe
across twelve labels, 'nothing good happened anywhere' is not a state the
world produces -- so the ladder reaches a long way before giving up, and
giving up raises an alarm. The quality bar never moves; only the haystack.

Because nothing is ever repeated, a story only has to be UNSEEN, not FRESH.

Tier 4 does NOT draw on the evergreen reserve. Only tier 5 does. Tier 4
means "reached back 90 days through real feeds" -- a warning. Tier 5 means
"fell back to the timeless reserve" -- an error. If tier 4 could also use
the reserve, both would collapse to the same meaning.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import editorial as ed
from . import fetch


@dataclass(frozen=True)
class Tier:
    number: int
    hours: int | None
    priority_only: bool
    allow_near_duplicates: bool
    evergreen: bool


TIERS = [
    Tier(1, 48, True, False, False),
    Tier(2, 24 * 7, False, False, False),
    Tier(3, 24 * 21, False, True, False),
    Tier(4, 24 * 90, False, True, False),
    Tier(5, None, False, True, True),
]

QUIET_NOTE = "A quiet morning. Nothing new made the cut."
MAX_CANDIDATES = 80


@dataclass
class Result:
    story: dict | None
    tier: int
    note: str | None = None
    evergreen: bool = False


def _survives(story: dict, memory, editorial_cfg: dict) -> bool:
    """Re-check the model's own pick in code. Never trust the prompt alone."""
    text = f"{story.get('title', '')} {story.get('summary', '')}"
    if ed.politics_blocked(text, editorial_cfg.get("banned_terms", []),
                           editorial_cfg.get("outcome_overrides", [])):
        return False
    return not memory.is_blocked(story.get("url", ""), story.get("title", ""))


def _prefilter(candidates, memory, editorial_cfg, allow_near):
    """Hard blocks and the politics filter apply identically at every tier --
    only near-duplicates (advisory, layer 3) are ever demoted rather than
    kept, and only released when the tier allows it. Kept candidates always
    precede demoted ones so the model sees the better candidates first."""
    kept, demoted = [], []
    for c in candidates:
        if memory.is_blocked(c.url, c.title):
            continue
        if ed.politics_blocked(f"{c.title} {c.blurb}",
                               editorial_cfg.get("banned_terms", []),
                               editorial_cfg.get("outcome_overrides", [])):
            continue
        (demoted if memory.is_near_duplicate(c.title) else kept).append(c)
    return kept + demoted if allow_near else kept


def select(*, candidates, memory, editorial_cfg, evergreen, ask_fn, now: datetime) -> Result:
    labels = editorial_cfg.get("labels", [])
    for tier in TIERS:
        if tier.hours is not None:
            pool = fetch.within_window(list(candidates), tier.hours, now)
            pool = _prefilter(pool, memory, editorial_cfg, tier.allow_near_duplicates)
            pool = pool[:MAX_CANDIDATES]
            if pool:
                for story in ask_fn(pool, memory.recent_titles()) or []:
                    if _survives(story, memory, editorial_cfg):
                        story["label"] = ed.normalise_label(story.get("label", ""), labels)
                        return Result(story=story, tier=tier.number)
        if tier.evergreen:
            for item in evergreen:
                if not memory.is_blocked(item["url"], item["title"]):
                    story = dict(item, why_good="Still true.")
                    story["label"] = ed.normalise_label(story.get("label", ""), labels)
                    return Result(story=story, tier=tier.number, evergreen=True)
    return Result(story=None, tier=5, note=QUIET_NOTE)
