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
from . import fetch, normalize


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

# R4: without a per-feed cap, a single compromised feed publishing enough
# items can supply every candidate in the pool -- verified: one priority
# feed publishing 80+ items filled 80/80 of the tier-1 pool, starving every
# honest source and maximising the prompt-injection surface the model is
# shown (the candidate list is untrusted text the model is told to treat as
# data, but more of it from one attacker-controlled source is strictly
# worse). 15 is chosen so twelve feeds can still fill MAX_CANDIDATES (80)
# comfortably even when several are quiet on a given day -- 12 * 15 = 180,
# more than double what's needed -- while capping any one source's share of
# an 80-slot pool to under a fifth instead of the 100% seen in review.
PER_FEED_CAP = 15


@dataclass
class Result:
    story: dict | None
    tier: int
    note: str | None = None
    evergreen: bool = False


def _banned_terms(editorial_cfg: dict) -> list[str]:
    """The politics filter is the product's soul and must never fail open.

    `editorial_cfg.get("banned_terms", [])` silently disabled the entire
    filter if the YAML key were ever renamed or emptied -- an empty banned
    list matches nothing, so every political story sails through both the
    prefilter and the post-model re-check with no error and no warning.
    config.load() already rejects such a config at startup; this is the
    second line of the same defence, for any caller that builds the dict
    itself."""
    terms = editorial_cfg.get("banned_terms") or []
    if not terms:
        raise ValueError(
            "editorial config has no banned_terms -- the politics filter "
            "would silently pass everything"
        )
    return terms


def _survives(story: dict, memory, editorial_cfg: dict, pool_url_keys: set[str]) -> bool:
    """Re-check the model's own pick in code. Never trust the prompt alone.

    Provenance is checked first (finding I2). The model is asked to copy a URL
    out of the candidate list, but it can hallucinate or mistype one -- and
    nothing downstream noticed: cli matched the pick back to a candidate only
    to compute age_text, and treated "no candidate has this URL" as normal,
    quietly publishing a live link with no timestamp. Worse,
    `memory.remember()` then stored a url_key matching nothing in any feed, so
    the real article stayed unseen and could be picked again later -- silently
    breaking the never-repeat promise this whole system rests on.

    So: a pick whose url_key is not in the pool the model was shown is not a
    story, it is a defect. Reject it and let the ladder try its next
    candidate. (Evergreen picks never come through here: they are taken
    straight from the reserve, not from a candidate pool.)"""
    if normalize.url_key(story.get("url", "")) not in pool_url_keys:
        return False
    text = f"{story.get('title', '')} {story.get('summary', '')}"
    if ed.politics_blocked(text, _banned_terms(editorial_cfg),
                           editorial_cfg.get("outcome_overrides", [])):
        return False
    return not memory.is_blocked(story.get("url", ""), story.get("title", ""))


def _cap_per_feed(candidates, cap):
    """Keep at most `cap` items per feed (`Candidate.source`), most-recent
    first, before the pool is assembled (finding R4): without this, a
    single compromised feed publishing enough items can fill every
    candidate slot on its own -- verified in review at 80/80 of the tier-1
    pool from one source.

    Undated items (`published is None`) sort after dated ones within their
    feed rather than raising. `within_window` has already dropped anything
    undated from every pool this actually runs on in `select()`, but
    sorting a mixed bool/datetime key this way keeps the function safe even
    if it's ever called on an unfiltered list, without assuming anything
    about timezone-awareness that would make comparing two `None`s or a
    `None` against a real datetime raise.
    """
    by_source: dict[str, list] = {}
    for c in candidates:
        by_source.setdefault(c.source, []).append(c)
    kept = []
    for items in by_source.values():
        items.sort(key=lambda c: (c.published is not None, c.published), reverse=True)
        kept.extend(items[:cap])
    return kept


def _prefilter(candidates, memory, editorial_cfg, allow_near, priority_only=False):
    """Hard blocks and the politics filter apply identically at every tier --
    only near-duplicates (advisory, layer 3) are ever demoted rather than
    kept, and only released when the tier allows it. Kept candidates always
    precede demoted ones so the model sees the better candidates first.

    priority_only is tier 1's own restriction: when True, only candidates
    from a dedicated priority outlet (fetch.Candidate.priority) are even
    considered -- everything else is dropped before the quality bar (hard
    blocks, politics, near-duplicates) is ever applied. Tiers 2 and beyond
    pass priority_only=False and see the full haystack."""
    kept, demoted = [], []
    for c in candidates:
        if priority_only and not c.priority:
            continue
        if memory.is_blocked(c.url, c.title):
            continue
        if ed.politics_blocked(f"{c.title} {c.blurb}",
                               _banned_terms(editorial_cfg),
                               editorial_cfg.get("outcome_overrides", [])):
            continue
        (demoted if memory.is_near_duplicate(c.title) else kept).append(c)
    return kept + demoted if allow_near else kept


def select(*, candidates, memory, editorial_cfg, evergreen, ask_fn, now: datetime) -> Result:
    labels = editorial_cfg.get("labels", [])
    for tier in TIERS:
        if tier.hours is not None:
            pool = fetch.within_window(list(candidates), tier.hours, now)
            pool = _cap_per_feed(pool, PER_FEED_CAP)
            pool = _prefilter(pool, memory, editorial_cfg, tier.allow_near_duplicates,
                              tier.priority_only)
            pool = pool[:MAX_CANDIDATES]
            if pool:
                # Exactly the URLs the model was shown -- a pick outside this
                # set did not come from any feed (finding I2).
                pool_url_keys = {normalize.url_key(c.url) for c in pool}
                for story in ask_fn(pool, memory.recent_titles()) or []:
                    if _survives(story, memory, editorial_cfg, pool_url_keys):
                        story["label"] = ed.normalise_label(story.get("label", ""), labels)
                        return Result(story=story, tier=tier.number)
        if tier.evergreen:
            for item in evergreen:
                if not memory.is_blocked(item["url"], item["title"]):
                    story = dict(item, why_good="Still true.")
                    story["label"] = ed.normalise_label(story.get("label", ""), labels)
                    return Result(story=story, tier=tier.number, evergreen=True)
    return Result(story=None, tier=5, note=QUIET_NOTE)
