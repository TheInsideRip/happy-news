# Red-team fix report — 2026-09-07

Five remaining findings (R1-R5) from the adversarial red-team review, fixed
and tested. All fixes are committed in five logical commits, one per
finding. Full suite: 237 passed (was 222 before this work; +15 new tests).

Threat model throughout: an attacker controls the content of one of the
twelve RSS feeds (title, link, description, publish date) and can publish
many items. No test touches the network, invokes the real `claude` CLI, or
runs a real `git push`.

---

## R1 — HIGH: `validate()` accepted `../` story links

**Root cause.** `validate()`'s href allowlist was written for one purpose
(letting the page's own chrome links — stylesheet, `archive/`, `../` nav —
through) but was applied uniformly to every href on the page, story links
included. A story `href` starting with `../` slipped through unchecked and
rendered as the headline's live link.

**Fix.** Story anchors are now marked `class="story-link"` in
`_story_html()` so `validate()` can find exactly the story links with a
dedicated regex (`_STORY_HREF`) and hold them to a strict rule — `http://`
or `https://`, full stop — checked *before* the existing chrome-link
allowlist. Chrome links (stylesheet, `archive/`, `../`, `#`) are unchanged.

**Pre-fix failure (real output, captured before touching `render.py`):**

```
$ PYTHONPATH=src python -m pytest tests/test_render.py -k "r1_payload or relative_path_story or genuine_https_story" -v

FAILURES
______________ test_validate_rejects_a_relative_path_story_link _______________
    day = {"date": "2026-09-07", "slots": {
        "morning": {"published_at": "a", "note": None, "stories": [
            dict(STORY, url="../../../../etc/passwd")]},
    }}
>   with pytest.raises(ValueError):
E   Failed: DID NOT RAISE <class 'ValueError'>

tests\test_render.py:358: Failed
___________ test_validate_rejects_every_r1_payload_as_a_story_link ____________
>   with pytest.raises(ValueError):
E   Failed: DID NOT RAISE <class 'ValueError'>

tests\test_render.py:368: Failed
______ test_validate_rejects_a_relative_path_story_link_in_render_front _______
>   with pytest.raises(ValueError):
E   Failed: DID NOT RAISE <class 'ValueError'>

tests\test_render.py:388: Failed
=========== 3 failed, 1 passed, 33 deselected in 0.44s ===========
```

All six required payloads (`../../../../etc/passwd`,
`javascript:location.replace(...)//x.html`,
`data:text/html;base64,...#x.html`, `javascript:alert(1)`, `//evil.example/x`,
`file:///C:/Windows/win.ini`) are now rejected as story links, and
`https://legit.example/story` still validates. All existing chrome-link
tests (`../assets/style.css`, `archive/`, `#` nav) still pass unchanged.

**Post-fix:** `tests/test_render.py` — 37 passed.

---

## R2 — MEDIUM: no HTTP response-size limit

**Fix.** `_get` now reads via `response.read1(n)` (one underlying syscall
per call, so it never silently blocks trying to fill a large buffer) in a
loop, aborting with `ValueError` once the running total crosses
`MAX_RESPONSE_BYTES`. An oversized feed is reported as a failed feed, same
as a dead or unreachable one — never a crash.

**Chosen number: 5 MB (`MAX_RESPONSE_BYTES = 5 * 1024 * 1024`).** A real
RSS feed, even a busy one with full-content descriptions for 100+ items, is
reliably well under 1 MB. 5 MB gives a legitimate feed generous headroom
while keeping the worst case — 8 concurrent workers, all maliciously
oversized — to a roughly 40 MB spike instead of an unbounded one.

**Tests:** `test_get_rejects_a_response_over_the_size_cap`,
`test_get_never_buffers_past_the_cap` (asserts `_get` stops asking for more
chunks once the cap is crossed, not just that it eventually rejects a huge
buffer), `test_fetch_all_reports_an_oversized_feed_as_failed_not_a_crash`.
First two failed with `AttributeError: module 'happy_news.fetch' has no
attribute 'MAX_RESPONSE_BYTES'` before the fix.

---

## R3 — MEDIUM: a slow-drip feed hangs the whole run

**Fix, two layers.**
1. `_get`'s read loop checks a wall-clock deadline (module global
   `FEED_DEADLINE_SECONDS`, read fresh on every call so it stays
   monkeypatchable) between every `read1()` call, and raises `TimeoutError`
   once it's exceeded — this is what actually makes the worker thread
   terminate on its own for the realistic attack (a feed trickling its
   body), rather than leaving it running forever in the background.
2. `fetch_all` no longer uses `with ThreadPoolExecutor(...) as pool:
   pool.map(...)`, whose `__exit__` waits for every submitted task
   regardless. It now submits each feed by hand and reads each future back
   with `future.result(timeout=deadline)`; a feed that blows its budget is
   abandoned and reported as failed, and `pool.shutdown(wait=False)` lets
   `fetch_all` return without waiting on it. This is the backstop that
   makes `fetch_all` itself provably bounded regardless of what's hanging
   inside `_get` (connect, headers, or body).

**Chosen number: 30 seconds (`FEED_DEADLINE_SECONDS`).** A real fetch is a
fraction of a second; 30s is enormous headroom. Worst case — 12 feeds, 8
concurrent workers, so at most two queued rounds — is roughly a minute,
trivial against Task Scheduler's 15-minute kill.

**Test:** `test_fetch_all_abandons_a_feed_that_blows_its_deadline_and_returns_promptly`
simulates a feed whose fake `_get` sleeps 0.6s against a 0.1s deadline, and
asserts `fetch_all` returns in under 0.5s with that feed named in
`failed` and the fast feed's items still present. A companion
`_get`-level test (`test_get_enforces_a_total_deadline...`) simulates the
literal one-byte-at-a-time drip via a fake `read1()`. Both failed with
`AttributeError` (missing `FEED_DEADLINE_SECONDS` / `deadline` kwarg)
before the fix — deliberately *not* via a `deadline=` keyword argument to
`_get` itself, since that would raise `TypeError` against the unfixed code
and pass for the wrong reason (documented inline in the test).

---

## R4 — MEDIUM: one compromised feed fills every candidate slot

**Fix.** New `ladder._cap_per_feed()` keeps at most `PER_FEED_CAP` items per
feed (`Candidate.source`), most-recent first, applied right after
`fetch.within_window()` and before `_prefilter()` in every dated tier —
so a compromised feed's contribution is bounded before politics/dedup
filtering even runs, regardless of how many items it actually published.

**Chosen number: 15 (`PER_FEED_CAP`).** Twelve feeds × 15 = 180, more than
double `MAX_CANDIDATES` (80), so the pool still fills comfortably even if
several feeds are quiet on a given day. It caps any single source's share
of an 80-slot pool to under a fifth, versus the 100% (80/80) verified in
review.

**Test:** `test_tier_pool_caps_a_single_feed_so_it_cannot_fill_every_slot`
reproduces the exact review scenario end-to-end through `ladder.select()` —
one feed publishing 80 items, one honest feed with 1 — and asserts the
honest item survives into the tier-1 pool. Pre-fix: `AttributeError:
module 'happy_news.ladder' has no attribute 'PER_FEED_CAP'`; once that
constant is stubbed in isolation the direct unit test
(`test_cap_per_feed_keeps_at_most_the_cap_and_keeps_the_most_recent`) shows
the uncapped pool would have handed the model 60 compromised-feed items
across the widening tiers.

---

## R5 — MINOR: dedup evadable by Unicode homoglyphs/decomposition

**Fix.** `normalize.title_norm` now runs `unicodedata.normalize("NFKC",
title)` before lowercasing/stripping punctuation.

**Honesty note on scope.** NFKC genuinely fixes an NFD/NFC decomposition
mismatch and a fullwidth-Unicode homoglyph swap (a real, documented
text-filter evasion technique — both are true Unicode
canonical/compatibility equivalences). It does **not** fix a genuine
cross-script confusable such as Cyrillic `е` (U+0435) substituted for Latin
`e` (U+0065): verified empirically — those are different characters in
different scripts with no Unicode equivalence relation at all, so no
normalization form unifies them. Closing that specific gap needs a
confusables-skeleton check (Unicode TR39), which is out of scope for this
MINOR finding's specified fix. This is made explicit in both the code
comment and a dedicated test
(`test_nfkc_does_not_unify_a_cross_script_cyrillic_confusable`) so the
boundary isn't silently overclaimed.

**Tests:** `test_title_key_survives_nfd_decomposition` (NFD vs NFC "é"
pair), `test_title_key_survives_a_fullwidth_homoglyph_swap` (fullwidth "W"
vs plain "W"). Both failed pre-fix with mismatched SHA1 hashes (real
output captured, e.g. `cd0d248c...` vs `8d552d29...` for the NFD/NFC
pair). As noted, this cannot *poison* memory — entries are only written by
`Memory.remember()` after a real publish — it is a bypass of the
never-repeat block, not an injection into it.

---

## Full suite result

```
$ PYTHONPATH=src python -m pytest -q
........................................................................ [ 30%]
........................................................................ [ 60%]
........................................................................ [ 91%]
.....................                                                    [100%]
237 passed, 57 warnings in 5.22s
```

(Baseline before this work: 222 passed. +15 new tests across the five
findings, 0 regressions. `assets/style.css` untouched — no styling,
palette, or dark-mode change of any kind.)

## Commits

| SHA | Finding | Summary |
|---|---|---|
| `08b25d4` | R1 | require story links to be http(s), never a relative path |
| `cfdd1ed` | R2 + R3 | cap feed response size and enforce a total per-feed fetch deadline |
| `cf41448` | R4 | cap candidates per feed so one source cannot fill the whole pool |
| `0f8f2c5` | R5 | Unicode-normalize titles before hashing, closing an NFD/homoglyph dedup bypass |

R2 and R3 share one commit: both fixes live in the same `_get`/`fetch_all`
read loop and are most honestly reviewed together (the R3 deadline check
sits inside the very loop R2 added for incremental, capped reading).

## Regression check against "do not regress" list

All previously-fixed findings' behaviors were re-verified passing in the
237-test final run, unchanged by this work: `validate()` still rejects a
no-story page and a whitespace-only summary and is never called on
`archive/index.html` (`cli.py` untouched); `git add` filtering/exit-code
handling untouched (`publish.py` untouched, `test_publish.py` 11/11);
`Memory.remember()`/`is_blocked()` untouched (`dedup.py` untouched,
`test_dedup.py` 15/15); `fetch_all` still never raises for malformed feed
entries (all prior `test_fetch.py` cases still pass); `_get` stays
module-level with an unchanged `(url, timeout)` call signature so every
existing `monkeypatch.setattr(fetch, "_get", fake_get)` two-argument fake
still works; edition/atomic-write/corrupt-JSON handling untouched
(`clock.py` untouched); single-instance lock untouched (`lock.py`
untouched); tier 4 `evergreen=False` and tier 1 priority-only restriction
untouched (only a new capping step was inserted, no tier semantics
changed); the model's pick still must have a `url_key` in the candidate
pool (`_survives` untouched). No dark mode, palette unchanged.

## Unfixed

Nothing from R1-R5 is left unfixed. The one explicitly scoped-out gap is
noted under R5 above: cross-script Unicode confusables (e.g. Cyrillic/Latin
letter swaps) are not caught by the NFKC fix as specified, and would need a
separate confusables-skeleton check to close — flagged, not silently
dropped.
