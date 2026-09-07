# Satcey Happy News — Design Spec

**Date:** 2026-09-07
**Repo:** `TheInsideRip/happy-news` (public)
**Live URL:** `https://theinsiderip.github.io/happy-news/`
**Status:** Approved design, ready for implementation planning

---

## 1. Purpose

A small, fast, mobile-first web page that publishes genuinely good news three times a
day. Its audience is one person, checking on a phone, three times a day, looking for a
bright spot. Everything below serves that.

The system runs entirely inside GitHub Actions. There is no server to maintain and no
hosting cost. The only external dependency is the Anthropic API.

### Success criteria

1. The page opens on a phone in under one second and is readable without zooming.
2. Three sections accumulate over the course of each day; a single check at any hour
   catches everything published so far that day.
3. Over any 30-day window, **no story URL and no story headline ever repeats**.
4. No story reads as political combat (see §3.3).
5. At least 95% of scheduled slots publish, within roughly 20 minutes of the target time.

### Non-goals (deliberately excluded)

No images. No search. No comments, accounts, email, or push notifications. No CMS or
admin UI. No custom domain. No social posting. No JavaScript framework. No analytics.
These are excluded to keep the page fast and the system small; any of them can be
added later as a separate piece of work.

---

## 2. Architecture

```
 GitHub Actions cron
        |
        v
   clock.py ------ not a publishing window? --> exit 0
        |          slot already published?   --> exit 0
        v
   fetch.py     pull ~35-50 RSS feeds  -> ~150-300 raw candidates
        |
        v
  normalize.py  canonical URL + title keys
        |
        v
   dedup.py     drop anything ever published (3 mechanical layers)
        |
        v
  editorial.py  drop banned-politics candidates (cheap prefilter)
        |
        v
   curate.py    ~80 candidates -> Claude -> 3-5 picks + written summaries
        |
        v
  editorial.py  hard filter re-applied to Claude's output (code, not prompt)
        |
        v
   dedup.py     re-check picks, then append to the permanent memory
        |
        v
   render.py    build index.html + archive page, validate BEFORE writing
        |
        v
  publish.py    git commit + push -> GitHub Pages serves it
```

**Rejected alternatives.** A separate host (Cloudflare Workers, Vercel) would give
punctual-to-the-minute scheduling, but costs money and adds a second system to keep
alive — not worth it for a ±15 minute difference. A JavaScript page loading a JSON
data file would be easier to restyle later, but shows a blank screen if anything
fails. We pre-render plain HTML: it loads instantly, on any connection, with scripting
irrelevant.

---

## 3. Editorial rules

These rules are the product. They live in `feeds/editorial.yaml` and in the Claude
prompt, and the hard filters are enforced **in code after Claude answers**, not merely
requested in the prompt.

### 3.1 Categories

| Category | Covers |
|---|---|
| `environment` | Climate wins, clean energy, conservation, restoration, **and all animal news** — wildlife recovery, species rebounds, rescues, habitat protection, animal-welfare law |
| `technology` | Inventions and deployments that measurably help people or the planet |
| `people` | Human interest, community, health and medical advances, science that helps people |
| `government` | **Outcomes only** — see §3.3 |

### 3.2 What counts as good news

A story qualifies only if it reports something that **has actually happened or is
measurably underway** — not a plan, a pledge, a forecast, or a study suggesting
something might work someday. Prefer concrete, finished, verifiable outcomes.

Rejected regardless of framing: anything whose core is suffering, disaster, crime, or
loss, even when the article ends hopefully. A rescue after a tragedy is still a
tragedy story.

### 3.3 The politics rule — "outcomes only, no combat"

**Allowed:** a law that measurably helps people, a peace or trade agreement signed, a
treaty ratified, a corruption conviction, a public program that demonstrably worked, a
court ruling that is final and beneficial, a city or agency that fixed something.

**Banned, without exception:** elections, polls, campaigns, candidates, personalities,
scandals, resignations, accusations, predictions, and anything framed as a fight, a
race, or a contest.

Skews global rather than US-partisan. US domestic stories are allowed when they meet
the outcomes-only bar.

**Implementation.** Two lists plus an override rule, all in `editorial.yaml`:

- `banned_terms` — matched case-insensitively on word boundaries in headline and
  summary. Seed list: `election`, `electoral`, `ballot`, `poll`, `polling`,
  `campaign`, `candidate`, `primaries`, `caucus`, `midterm`, `incumbent`,
  `approval rating`, `partisan`, `filibuster`, `shutdown`, `impeach`, `indict`,
  `scandal`, `subpoena`, `slams`, `blasts`, `rips`, `hits back`, `feud`, `spat`,
  `clash`, `sues`, `files suit`, `Democrat`, `Republican`, `GOP`, `left-wing`,
  `right-wing`.
- `outcome_overrides` — phrases that rescue an otherwise-banned candidate because they
  mark a finished outcome: `court ruled`, `court upheld`, `judge ordered`,
  `convicted`, `treaty ratified`, `agreement signed`, `law took effect`,
  `bill signed into law`, `settlement reached`.
- **Rule:** reject if any `banned_term` matches **and** no `outcome_override` matches.

This list is expected to be tuned during the first few weeks. It is data, not code, so
tuning it requires no code change. The false-positive risk is real and accepted: a
slightly over-eager filter costs us a story, while an under-eager one costs the
product its whole reason for existing.

### 3.4 Edition size and thin runs

Target **3–5 stories per edition**. Three editions a day at six stories would demand
126 non-repeating stories a week — far more than the good-news ecosystem produces.
Short and excellent beats long and padded.

**Minimum is 3, target is 5.** When a run cannot reach the minimum, it escalates in
this order and **never lowers the quality bar**:

1. Widen the time window from 24 hours to 72 hours.
2. Pull from the full feed list rather than the priority subset.
3. Publish whatever it has. At a count of 1 or 2, attach the quiet one-line note
   *"A quieter stretch today."* At 3 or more, no note appears.
4. If it finds **zero** qualifying stories, write nothing to the edition file for that
   slot and record the reason in the health log (§8). Because the slot stays unfilled,
   later cron fires **within the same window** will try again — a quiet 8:00 can still
   become a good 9:30. If the window closes with the slot still empty, that slot is
   skipped for the day and the page simply does not gain a section.

---

## 4. Components

Each module is independently testable and has one job.

| Module | Responsibility | Depends on |
|---|---|---|
| `config.py` | Load `sources.yaml` / `editorial.yaml`, read env, expose typed settings | — |
| `clock.py` | Determine the current slot in Eastern time; answer "should this run publish?" | config |
| `fetch.py` | Fetch and parse RSS feeds concurrently, tolerate individual failures | config |
| `normalize.py` | Canonical URL keys, title keys, token sets | — |
| `dedup.py` | The permanent memory: read/append `seen.jsonl`, decide "have we shown this?" | normalize |
| `editorial.py` | Good-news and politics filters, applied both pre- and post-Claude | config |
| `curate.py` | Build the prompt, call Claude, validate structured output, retry once | config, editorial |
| `render.py` | Generate `index.html`, archive day pages, and `archive/index.html`; validate before returning | — |
| `publish.py` | Stage, commit, rebase, push | — |
| `cli.py` | Entry point: `run`, `dry-run`, `rebuild` | all |

### 4.1 clock.py — slots and daylight saving

GitHub's scheduler only understands UTC, and 8am Eastern is a different UTC hour in
summer than in winter. Rather than fight that, **the workflow fires more often than
needed and the script decides.**

Slot windows, in `America/New_York` (via Python's built-in `zoneinfo`):

| Slot | Target | Accepts a run between |
|---|---|---|
| `morning` | 08:00 ET | 08:00 – 10:59 ET |
| `afternoon` | 14:00 ET | 14:00 – 16:59 ET |
| `evening` | 19:00 ET | 19:00 – 21:59 ET |

Logic on every run:

1. Compute `now` in `America/New_York`.
2. If `now` falls in no window, exit 0 — "not a publishing window."
3. If `data/editions/<today>.json` already contains this slot, exit 0 — "already
   published."
4. Otherwise, publish.

The three-hour windows absorb GitHub's lateness. The already-published check makes
duplicate runs harmless. DST is handled once, correctly, by `zoneinfo`.

### 4.2 dedup.py — the "never twice" guarantee

Memory lives in `data/seen.jsonl`, one JSON object per line, appended forever. JSON
Lines is chosen so each run adds a handful of lines and the git diff stays clean.

```json
{"url_key":"reuters.com/world/humpback-whale-numbers-recover","title_key":"9f2c...","tokens":["antarctic","humpback","numbers","recover","whale"],"title":"Humpback whale numbers recover in Antarctic","date":"2026-09-07","slot":"morning"}
```

Four layers, checked in order:

| Layer | Method | Guarantee |
|---|---|---|
| 1. Same link | Exact match on `url_key` | **Absolute** |
| 2. Same headline | Exact match on `title_key` | **Absolute** |
| 3. Reworded | Jaccard similarity of `tokens` ≥ **0.60** against the last 18 months | Catches most rewordings |
| 4. Same event, different words | Claude is shown the last 60 published headlines and asked to reject same-event repeats | Catches most of the rest |

Duplicates *within* a single run (two feeds carrying the same story) are collapsed by
layers 1–3 before Claude ever sees them.

**Honest limitation:** layers 1 and 2 are perfect. Layers 3 and 4 are very good, not
perfect. The same event written up by two outlets with genuinely different wording can
slip through. This is a known, accepted gap.

**Key construction (normalize.py):**

- `url_key` — lowercase host with `www.` removed, path with trailing slash and
  fragment removed, query string kept but with tracking parameters dropped
  (`utm_*`, `fbclid`, `gclid`, `ref`, `source`, `mc_cid`, `mc_eid`, `at_*`, `cmp`,
  `ito`). Non-tracking parameters are kept, because some sites route by `?p=123`.
- `title_key` — SHA-1 of the title lowercased, punctuation stripped, whitespace
  collapsed.
- `tokens` — title lowercased, stopwords and words under three characters removed,
  deduplicated, sorted.

**Growth:** roughly 9–15 stories a day, about 4,000 a year, at ~200 bytes each — under
1MB per year. A non-issue for a decade. Layer 3 only compares against the last 18
months; layers 1 and 2 compare against all of history, forever.

### 4.3 curate.py — the Claude call

- **Model:** `claude-sonnet-5`. Selection and short summarisation do not need Opus, and
  Sonnet is materially cheaper for a job that runs 90 times a month. Exact model ID and
  pricing to be confirmed against the `claude-api` skill at implementation time.
- **Input:** the editorial rulebook, the last 60 published headlines, and ~80 surviving
  candidates (title, source, publication time, feed summary truncated to 300
  characters).
- **Output:** structured, via tool-use/JSON-schema so parsing cannot drift. Per story:
  `title`, `url`, `source`, `category`, `summary` (2–3 warm sentences in plain English,
  no jargon), and `why_good` (one line, recorded for auditing, not displayed).
- **Retry:** one retry on network failure or schema-invalid output. A second failure
  ends the run; the next backup cron picks up the slot.
- **Estimated tokens:** ~9,000 in, ~700 out per run.

### 4.4 render.py — the page

`index.html` shows **today**, newest section on top:

```
Satcey Happy News            Sunday, September 7

  EVENING  · 7:04 pm
    [category] Headline linking out
    Source · 2 hours ago
    Two or three warm sentences.
    ...

  AFTERNOON · 2:11 pm
    ...

  MORNING · 8:03 am
    ...

  Updated 3x daily · Archive
```

- Mobile-first CSS in `assets/style.css`. System font stack, ~17px base, generous
  line-height, `max-width: 38rem`, respects `prefers-color-scheme` for dark mode.
- No images, no JavaScript, no external requests. The page is self-contained apart from
  one stylesheet.
- Links open in a new tab with `rel="noopener noreferrer"`.
- At midnight ET the next run writes a fresh `index.html`; the finished day already
  exists at `archive/YYYY-MM-DD.html`.
- `archive/index.html` is a reverse-chronological list of days.
- **Validation before write:** the HTML must parse, contain at least one story, have no
  empty summaries, and every URL must be `http`/`https`. Rendering happens to a scratch
  file and is validated before anything is committed, so a broken page can never reach
  the reader.
- `cli.py rebuild` regenerates every page from `data/editions/*.json`, so a styling
  change re-renders the entire history.

---

## 5. Data formats

```
data/
  seen.jsonl              # permanent dedup memory, append-only (see §4.2)
  health.json             # consecutive-failure counter and last-run record
  editions/
    2026-09-07.json       # one file per day, the source of truth for rendering
```

`data/editions/2026-09-07.json`:

```json
{
  "date": "2026-09-07",
  "slots": {
    "morning": {
      "published_at": "2026-09-07T08:03:41-04:00",
      "note": null,
      "stories": [
        {
          "title": "Humpback whale numbers recover in Antarctic waters",
          "url": "https://example.com/whales",
          "source": "BBC",
          "category": "environment",
          "summary": "Two or three warm sentences.",
          "published_utc": "2026-09-07T09:12:00Z"
        }
      ]
    }
  }
}
```

`note` carries the quiet "A quieter stretch today." line when a run publishes short.

---

## 6. Scheduling

`.github/workflows/publish.yml`:

```yaml
on:
  schedule:
    - cron: "0,30 0,1,12,13,14,18,19,20,23 * * *"
  workflow_dispatch:
concurrency:
  group: publish
  cancel-in-progress: false
permissions:
  contents: write
```

That is 18 short runs a day. Roughly three do real work; the rest exit within seconds
after `clock.py` says "not a publishing window" or "already published." The extra fires
exist because GitHub genuinely does skip scheduled runs under load, and on a public
repository Actions minutes are free, so redundancy costs nothing.

`workflow_dispatch` allows a manual run from the GitHub UI or phone.

**Stated expectation:** publication lands within roughly 20 minutes of 8:00 am, 2:00 pm,
and 7:00 pm Eastern. Not to the minute. GitHub's scheduler does not offer that, and this
design does not pretend otherwise.

---

## 7. Secrets

`ANTHROPIC_API_KEY` is stored **only** as a GitHub Actions repository secret. It is
never committed, never logged, and never written to any generated file. `.gitignore`
excludes `.env`. The repository is public, so this rule is absolute.

---

## 8. Failure handling

| Failure | Behaviour |
|---|---|
| One or more feeds unreachable | Log and continue with the feeds that worked |
| All feeds unreachable | Fail the run; the next backup cron retries |
| Claude call fails or returns invalid output | Retry once, then fail the run; backup cron retries |
| Render validation fails | Abort before committing; nothing is published |
| Git push conflict | `git pull --rebase` and retry once |
| Zero qualifying stories | Publish nothing for the slot, record the reason in `health.json` |
| 3 consecutive failed runs | Open a GitHub issue (only one open at a time), so the failure surfaces via GitHub rather than via the reader |

**"Failed run" means a run that entered a publishing window and then errored.** The
majority of the 18 daily fires exit early — outside a window, or slot already published
— and those are not failures and never touch the counter. A successful publish resets
the counter to zero. A zero-story run (§3.4, step 4) is not a failure either; it is
recorded separately in `health.json` so a persistent drought is still visible.

---

## 9. Testing

`pytest`, with **no network access in any test**. All feed XML and Claude responses are
saved fixtures.

| Test file | Covers |
|---|---|
| `test_clock.py` | Slot detection at 07:59 / 08:00 / 10:59 / 11:00 ET; both DST changeover weekends; already-published short-circuit |
| `test_normalize.py` | Tracking-parameter stripping, `www.`, trailing slashes, fragments, casing, non-tracking params preserved |
| `test_dedup.py` | Exact URL match, exact title match, Jaccard boundaries at 0.59 / 0.60 / 0.61, within-run collapsing, 18-month window edge |
| `test_editorial.py` | Each banned term fires; each outcome override rescues; false-positive guards (`primary school`, `clash of colours`) |
| `test_curate.py` | Mocked API: valid response parses, malformed JSON triggers exactly one retry, schema violations rejected |
| `test_render.py` | Golden-file comparison for a full day, a single-slot day, a short edition with a note, and an empty archive |

`cli.py dry-run` builds the page locally, prints what would publish, and writes nothing
— so the output can be reviewed before it ever goes live.

---

## 10. Repository layout

```
happy-news/
  .nojekyll
  .gitignore
  README.md
  requirements.txt
  index.html                        # generated
  assets/style.css                  # hand-written
  archive/
    index.html                      # generated
    2026-09-07.html                 # generated
  data/
    seen.jsonl
    health.json
    editions/2026-09-07.json
  feeds/
    sources.yaml                    # the feed list
    editorial.yaml                  # categories, banned terms, overrides
  src/happy_news/
    __init__.py config.py clock.py fetch.py normalize.py
    dedup.py editorial.py curate.py render.py publish.py cli.py
  tests/
    fixtures/ test_*.py
  .github/workflows/publish.yml
  docs/superpowers/specs/
```

GitHub Pages serves from `main` at `/` with `.nojekyll`, matching the existing
`cfb-dashboard` and `nfl-dashboard` setup. `src/`, `tests/`, and `docs/` are therefore
publicly readable. That is acceptable: no secrets live in the repository.

---

## 11. Cost

| Item | Cost |
|---|---|
| GitHub Pages hosting | $0 |
| GitHub Actions (public repo) | $0 |
| Storage | $0 |
| Anthropic API | ~$1–4 / month, to be confirmed against current pricing at build time |
| Maintenance | None expected after launch, beyond occasional tuning of `editorial.yaml` |

---

## 12. Prerequisites before implementation

1. An Anthropic API key from `console.anthropic.com` (separate from a Claude
   subscription), added as the repository secret `ANTHROPIC_API_KEY`.
2. The public repository `TheInsideRip/happy-news` created, with Pages enabled on
   branch `main`, folder `/`.

Both are user actions. Neither blocks writing the implementation plan.
