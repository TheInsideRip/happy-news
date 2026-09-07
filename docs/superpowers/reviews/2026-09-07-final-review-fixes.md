# Final whole-branch review — fix report

Branch `main`, working directory `E:\Satcey Happy News`, Python 3.14.3, Windows 11.

**Baseline:** 155 passed. **Final:** 222 passed, 0 failed. 11 commits, `e26fe9c` … `61e2316`.
Nothing was pushed. No test touches the network, the real `claude` CLI, or a real `git push`.

---

## CRITICAL

### C1 — A truncated edition file froze the page forever with no alert whatsoever

**Cause.** `cli.do_run` calls `clock.already_published()` *outside* the `try` block (deliberately —
Task 12 ruling 1 keeps the 15-of-18 early-exit runs off the disk). `clock.load_edition` did a bare
`json.load`. So a half-written `data/editions/<date>.json` raised `JSONDecodeError` straight out of
`main`: no `failures.log`, no `health.json` update, no toast, no failure counter — and the identical
crash on every subsequent run. The reader sees a frozen page; the operator sees only a traceback in
`logs\run.log`.

The trigger was real: `cli._persist` used plain `write_text` (truncate-then-write) while
`alert.Health._write` already used temp-file + `os.replace`, and the scheduled tasks kill the process
at 15 minutes.

**Pre-fix, real output.** A deliberately truncated edition file, read through the exact call the CLI
makes outside its try block:

```
$ printf '{\n  "date": "2026-09-07",\n  "slots": {\n    "morning": {\n      "stor' > <tmp>/2026-09-07.json
$ PYTHONPATH=src python -c "from datetime import date; from pathlib import Path; from happy_news import clock; print(clock.already_published(Path(r'<tmp>'), date(2026,9,7), 'morning'))"
  File "E:\Satcey Happy News\src\happy_news\clock.py", line 52, in already_published
    edition = load_edition(editions_dir, day)
  File "E:\Satcey Happy News\src\happy_news\clock.py", line 46, in load_edition
    return json.load(handle)
           ~~~~~~~~~^^^^^^^^
  ...
json.decoder.JSONDecodeError: Unterminated string starting at: line 5 column 7 (char 62)
```

And the same thing through the full CLI, as a test (`tests/test_cli.py`):

```
$ python -m pytest tests/test_cli.py -k truncated
E           json.decoder.JSONDecodeError: Unterminated string starting at: line 5 column 7 (char 62)
C:\...\json\decoder.py:361: JSONDecodeError
FAILED tests/test_cli.py::test_a_truncated_edition_file_does_not_crash_the_run_and_self_heals
1 failed, 29 deselected in 0.69s
```

**Fix (both halves).**

* `clock.load_edition` returns the empty default on `json.JSONDecodeError`, `OSError`,
  `UnicodeDecodeError`, or a payload that is not an object, logging a warning. Because the slot then
  looks unpublished, the run republishes it and overwrites the corrupt file — it self-heals.
* New `clock.save_edition(editions_dir, day, data)` writes through `tempfile.mkstemp` in the same
  directory then `os.replace` — the same pattern `alert.Health._write` uses, atomic on NTFS when
  source and destination share a volume. `cli._persist` now calls it, so a kill mid-write can no
  longer produce a half-file at all. The temp file is removed if anything raises.

**Post-fix, real output.** Same truncated file, same call:

```
WARNING happy_news.clock: unreadable edition file ...\2026-09-07.json
  (Unterminated string starting at: line 5 column 7 (char 62)); treating the day as empty
load_edition -> {'date': '2026-09-07', 'slots': {}}
already_published -> False
```

**Tests** (all fail without the fix): `tests/test_clock.py` — truncated / empty / non-UTF-8 /
non-object files degrade to the default; `save_edition` leaves no temp file; a failed `os.replace`
leaves the previous good file intact. `tests/test_cli.py` — a full run over a truncated edition file
returns 0, republishes the slot and rewrites the file correctly; the edition is persisted through
`clock.save_edition` with no temp files left behind.

Commit `e26fe9c`.

---

### C2 — The reader's staleness signal did not convey staleness

**Cause.** `render.py` emitted `Last updated {time}` with `%I:%M %p` only — the live page said
`Last updated 5:10 pm`, no date. If the laptop is off or asleep for a day or a week, no run happens,
so there is also no toast and no log line: both of the spec's "two independent places" (§8, §1
criterion 5) go silent at once, for the single most likely real-world failure. And the page is
byte-identical to a fresh one. The recent front-page change made it worse — every *earlier* day is
date-stamped, so the stale top block was the only undated thing on the page.

**Pre-fix, real output.**

```
$ python -m pytest tests/test_render.py -k "last_updated or week_old"
>       assert "Last updated Monday 7 Sep" in html
E       assert 'Last updated Monday 7 Sep' in '<!doctype html>...'
...
>       day = date.fromisoformat(edition["date"])
E       ValueError: Invalid isoformat string: 'not-a-date'
FAILED tests/test_render.py::test_last_updated_names_the_day_not_only_the_time
FAILED tests/test_render.py::test_render_front_last_updated_names_the_day_not_only_the_time
FAILED tests/test_render.py::test_a_week_old_page_does_not_look_identical_to_a_fresh_one
FAILED tests/test_render.py::test_last_updated_falls_back_to_the_day_alone_when_no_time_is_known
FAILED tests/test_render.py::test_last_updated_survives_an_unparseable_edition_date
5 failed, 2 passed, 23 deselected in 0.39s
```

Rendering the live `data/editions/2026-09-07.json` before the fix produced:
`<p class="sn-updated">Last updated 5:10 pm</p>`

**Fix.** One shared `render._updated_heading(edition, current_slot)` used by both `render_day`
(`is_today=True`) and `render_front`, building `Last updated Monday 7 Sep, 5:10 pm` from
`_day_stamp()` (`%A` + day number + `%b`; `%-d` is a glibc extension that raises on Windows) plus the
existing time text. A missing time degrades to the day alone with no dangling comma; an unparseable
date degrades to the old time-only heading rather than raising. `_archive_heading()` factors out the
existing past-day heading, unchanged in wording, and is now also crash-proof.

No styling was touched: `assets/style.css` is byte-identical, the palette is still
`--g:#D7E4C8` / `--pl:#F1F6EA`, and there is still no dark mode and no
`@media (prefers-color-scheme: dark)` block.

**Post-fix, real output** on the live edition file:

```
<p class="sn-updated">Last updated Monday 7 Sep, 5:10 pm</p>
```

**Tests:** the five above, including `test_a_week_old_page_does_not_look_identical_to_a_fresh_one`,
which renders the same slot at the same clock time seven days apart and asserts the two pages differ.

Commit `2c59017`.

---

## IMPORTANT

### I1 — No single-instance lock — commit `2d331dc`

New `src/happy_news/lock.py`: `lock.exclusive(path)`, a context manager over an
`os.open(..., O_CREAT|O_EXCL)` lock file — one atomic syscall, no check-then-create race. `main()`
wraps the `run` command in `lock.exclusive(root / "logs" / "run.lock")`; `logs/` is gitignored, so the
lock is never committed. A second instance does not block and does not fail: it prints and logs
`another run is already in progress; skipping (...)` and returns 0.

The lock sits *outside* the already-published check on purpose — otherwise two overlapping runs could
both read that check as "not yet done" and both proceed. That costs the early-exit path one file
create and one delete; the `cli` module docstring now records this against Task 12 ruling 1.

A lock older than `STALE_AFTER_SECONDS` (30 minutes; the tasks kill a run at 15) is taken over with a
warning, so a killed process can never wedge publishing — that would be the very staleness this
system exists to prevent. The lock is released in a `finally`, including when the run raises.

`dry-run` is deliberately unlocked: it writes nothing, so the operator can always inspect mid-run.

Tests: `tests/test_lock.py` (6) — refusal while held, release on success and on exception, stale
takeover, a fresh lock is not stolen, directory creation. `tests/test_cli.py` (4) — a second
concurrent run exits 0, fetches nothing, writes no page/edition/seen line and no `failures.log`, and
does not steal the holder's lock; a normal run holds the lock for its whole duration and releases it;
a failed run still releases it; `dry-run` is not blocked. Verified failing without the `cli` change.

### I2 — The published URL was never checked against the candidate pool — commit `1ed6d16`

`ladder._survives` now takes the set of `url_key`s from exactly the pool the model was shown and
rejects any pick outside it, before the politics and dedup re-checks; `select` builds that set from
the truncated pool. The ladder then falls through to its next candidate, then its next tier, then the
reserve. Matching is on `normalize.url_key`, so tracking parameters and trailing slashes are still
the same article. `cli` logs a warning if the (now unreachable) unmatched branch ever fires, instead
of silently shipping a live link with no timestamp.

Also folded in here, same never-fail-open principle: a missing or empty `banned_terms` is now a hard
error in `config.load` *and* in `ladder._banned_terms`, rather than silently disabling the entire
politics filter.

Tests: `tests/test_ladder.py` — a hallucinated URL is skipped and the next candidate used; a pick
matching nothing falls all the way to the reserve; `url_key` normalisation still matches; a direct
unit test of the provenance clause; and empty/missing/null `banned_terms` raise.
`tests/test_config.py` — three hard-error cases plus one asserting the live shipped
`feeds/editorial.yaml` satisfies the rule. `tests/test_cli.py` — a hallucinated URL never reaches
`index.html` *or* `seen.jsonl`, the real article is not burned, and a genuine pick still gets its
`age_text`.

Seven pre-existing `test_ladder.py` cases happened to use a model pick whose URL was not in the pool
(e.g. candidate `https://a.com/<hash>` vs story `https://a.com/t`). They were updated to use a real
pool URL so each still isolates the layer it was written for — in particular
`test_politics_filter_reapplied_after_the_model_answers` and
`test_blocked_story_is_rejected_even_if_the_model_picks_it` would otherwise have started passing on
provenance rather than on the layer under test.

### I3 — `tzdata` missing from `requirements.txt` — commit `3116885`

`clock.py` evaluates `ZoneInfo("America/New_York")` at import; Windows ships no system IANA database,
so a clean install dies during import — before `do_run` has executed, hence with no alert of any
kind. Pinned to the installed version, checked with `python -m pip show tzdata` → `2025.3`, with a
comment explaining why it is not optional. Tests assert the pin exists in `requirements.txt` and that
`clock.TZ` actually resolves.

---

## MINOR

| Finding | Fix | Commit |
|---|---|---|
| `render.validate` accepted any scheme ending `.html` | Deleted the `href.endswith(".html")` clause. Every link on a validated page is http(s) or one of the fixed relative nav targets; `archive/index.html`'s `<date>.html` links are on the one page `validate()` is never called on. Tests cover `javascript:`, `data:`, `file:` and `vbscript:` payloads ending in `.html`, plus a test that the pages' own nav links still validate. | `98a9f77` |
| `date.fromisoformat(path.stem)` failed on any stray file in `data/editions/` | New `cli._edition_days()` skips non-date filenames with a warning; both call sites use it. Tests: a rebuild and a live run with `2026-09-07.json.json`, `backup.json` and `notes.json` present. | `98a9f77` |
| `dedup` direct `entry["url_key"]` indexing | `Memory._load` skips unparseable / non-object / keyless lines and logs the count. Deliberately narrow: an entry with a broken `date` or `tokens` is still *kept* for the absolute layers 1 and 2, and only the advisory layer-3 check skips it — dropping a line weakens the never-repeat promise, so the bar for dropping is high. `recent_titles` tolerates a missing title. Tests cover all of it, including the logged count. | `98a9f77` |
| `git pull --rebase` exit code discarded | Checked; on failure `git rebase --abort` runs so the working tree is left clean for the next scheduled run, then `PublishError` names the conflict (and the abort, if that failed too). Tests: injected-runner cases for the abort path, the abort-also-failed path, and that a clean rebase still retries the push — plus one test that drives a genuinely conflicted rebase through the **real git binary** on real local repos in `tmp_path` (no network, no real push; only `pull --rebase` and `rebase --abort` reach git) and then proves the next commit succeeds. | `db8c214` |
| `banned_terms` could fail open | Hard error at `config.load` and in `ladder`. (Reported under I2 above.) | `1ed6d16` |
| `feeds/editorial.yaml` missing `polls` | Added — the filter matches whole words, so `\bpoll\b` never matched the commoner plural. Test runs against the live YAML, not a fixture. | `04c755e` |
| Spec §8 escalation never implemented | `Health.record_tier` now stores `{at, tier}` and returns how many tier-4-or-worse runs fall inside the rolling 7 days. New `Health.recent_tier_alarms()` does the counting; old bare-integer entries are still read but never counted, because an escalation must be provable rather than guessed. `cli` calls `record_tier` only **after** `publish.push` returns, and raises an escalated toast plus an `ERROR` log line at the threshold. Tests: 7 in `test_alert.py` (one deep reach is not an escalation; two inside the week are; tier 5 counts; tiers 1–3 never do; older than the window does not; legacy bare integers; corrupt entries) and 4 in `test_cli.py` (escalated alert fires, does not fire on one, does not fire on a stale one, and a **failed push records no tier at all**). | `8f74173` |
| `logs\run.log` grew forever | New `rotate_log.bat` keeps the most recent 2000 lines once the file passes 1 MB; `publish.bat` calls it *before* opening its append redirect, so nothing holds a handle on the file while it is rewritten. It always exits 0 — housekeeping must never stop a publish. `tests/test_launcher.py` drives the real `cmd.exe` over temp files, including a path with spaces (the live root is `E:\Satcey Happy News`), and asserts the ordering inside `publish.bat`. Also verified by hand end-to-end: 6000 lines → 2000 kept, tail preserved, `rc=0`. | `60ea82d` |

---

## Regression checks

None of the protected behaviours changed. Their tests all still pass:

* `validate()` still rejects a page with no story, a whitespace-only summary, and any non-http(s)
  link — and is still never called on `archive/index.html`.
* `git add` still filters to existing paths and still raises on a non-zero exit.
* `Memory.remember()` still loads the cache before writing, and is still called only after a story
  actually publishes.
* `fetch_all` still never raises for any input, including malformed and non-dict entries.
* `Memory.is_blocked` still consults only exact url and title keys; the Jaccard layer never blocks on
  its own.
* The edition file is still rolled back to its pre-run snapshot if rendering, validation or the push
  fails, so a failed slot is genuinely retried.
* Tier 4 keeps `evergreen=False`; only tier 5 uses the reserve; tier 1 stays priority-only.
* Everything reaching HTML is still escaped — `_updated_heading` escapes the parts it interpolates,
  and `_archive_heading` escapes its fallback.
* No dark mode. `assets/style.css` is untouched; palette still `--g:#D7E4C8` / `--pl:#F1F6EA`.
* One story per timeframe; the front page still shows the last 7 days.

`git diff --stat 1e558b3..HEAD` touches no generated output: `index.html`, `archive/*.html`,
`assets/style.css`, `design/`, `data/` are all unchanged. The live `data/health.json` (which holds a
legacy bare-integer `tiers` entry) still reads correctly under the new code.

---

## Full suite

```
$ python -m pytest
222 passed, 45 warnings in 5.71s
```

(The 45 warnings are a pre-existing `DeprecationWarning` from `feedparser`'s own `html.py`, unrelated
to this work.)

## Commits

```
61e2316 docs(cli): record the lock's placement and its cost to the fast path
60ea82d fix: rotate logs/run.log instead of letting it grow forever
8f74173 feat: implement the spec's rolling-week tier escalation
04c755e fix: block the plural "polls" in the politics filter
db8c214 fix: check git pull --rebase and abort a conflicted rebase
98a9f77 fix: three one-bad-input-freezes-everything defects
3116885 fix(I3): pin tzdata, without which a clean install dies at import
1ed6d16 fix(I2): reject a published URL that came from no candidate
2d331dc fix(I1): single-instance lock so two runs cannot drop each other's slot
2c59017 fix(C2): the reader's staleness signal now names the day
e26fe9c fix(C1): a truncated edition file froze the page forever, silently
```

## Notes for the operator

* `pip install -r requirements.txt` should be re-run so `tzdata` is explicitly installed rather than
  incidentally present.
* Nothing was pushed. `index.html` will pick up the dated `Last updated` heading on the next
  scheduled run, which rebuilds every page as part of its normal work.
