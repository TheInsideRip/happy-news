# Stacey Happy News — Design Spec

**Date:** 2026-09-07 (revised: local runtime; one story per timeframe; look approved)
**Repo:** `TheInsideRip/happy-news` (public) — hosting only
**Live URL:** `https://theinsiderip.github.io/happy-news/`
**Runs on:** this Windows machine, via Task Scheduler, using the `claude` CLI
**Status:** Approved design, ready for implementation planning

---

## 1. Purpose

A small, fast, mobile-first web page that publishes genuinely good news three times a
day. Its audience is one person, checking on a phone, three times a day, looking for a
bright spot. Everything below serves that.

The work runs on this machine, matching the existing `TIR_*` / `CFB_*` / `MLB_*` task
pattern. GitHub is used only to host the finished page so it is reachable from a phone
anywhere. There is no API key and no running cost.

### Success criteria

1. The page opens on a phone in under one second and is readable without zooming.
2. Three sections accumulate over the course of each day, **one story each**; a single
   check at any hour catches everything published so far that day, with no scrolling.
3. Over any 30-day window, **no story URL and no story headline ever repeats**.
4. No story reads as political combat (see §3.3).
5. When a run fails or is missed, the reader can see the page is stale and the operator
   is alerted (§8). Silent staleness is the failure mode this design most guards against.

### Non-goals (deliberately excluded)

No images. No search. No comments, accounts, email, or push notifications. No CMS or
admin UI. No custom domain. No social posting. No JavaScript framework. No analytics.
These are excluded to keep the page fast and the system small; any of them can be added
later as a separate piece of work.

---

## 2. Architecture

```
 Windows Task Scheduler  (08:00 / 14:00 / 19:00 local, + missed-run catch-up)
        |
        v
   publish.bat  ->  python -m happy_news run
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
   dedup.py     block seen links + headlines; demote near-matches
        |
        v
  editorial.py  drop banned-politics candidates (cheap prefilter)
        |            (nothing left? ladder.py widens the net and retries -- see 3.4)
        |
        v
   curate.py    ~80 candidates -> claude CLI -> 3 ranked picks, 1 published
        |
        v
  editorial.py  hard filter re-applied to the model's output (code, not prompt)
        |
        v
   dedup.py     re-check picks, then append to the permanent memory
        |
        v
   render.py    build index.html + archive page, validate BEFORE writing
        |
        v
  publish.py    git commit + push -> GitHub Pages serves it
        |
        v
   alert.py     on failure: Windows notification + failure log
```

**Portability is a requirement, not an accident.** Only two modules know where the
system is running: `curate.py` (how the model is called) and `publish.py` (how the
result is pushed). Everything else is plain Python with no knowledge of Task Scheduler
or GitHub. Moving to cloud execution later means swapping one function in `curate.py`
for an API call and adding a workflow file — not a rewrite. This is a deliberate
concession to the "assess and adjust" decision recorded below.

**Rejected alternatives.** *GitHub Actions + Anthropic API key* would be immune to the
laptop being off or the login expiring, at roughly $1–4/month. Rejected for now in
favour of zero cost and consistency with the existing local task setup, with the
explicit intent to reconsider if missed runs prove annoying in practice. *A JavaScript
page loading a JSON data file* would be easier to restyle later, but shows a blank
screen if anything fails; we pre-render plain HTML instead.

---

## 3. Editorial rules

These rules are the product. They live in `feeds/editorial.yaml` and in the prompt, and
the hard filters are enforced **in code after the model answers**, not merely requested
in the prompt.

### 3.1 Categories

Eight, deliberately wide. The narrow four-category list in the first draft made the
system fragile: one bad night for environmental feeds and there was nothing to publish.
Breadth is the cheapest insurance against a dry run, and at one story per timeframe
there is no cost to having more places to look.

| Category | Covers |
|---|---|
| `environment` | Climate wins, clean energy, conservation, restoration, **and all animal news** — wildlife recovery, species rebounds, rescues, habitat protection, animal-welfare law |
| `science` | Space, discovery, archaeology, palaeontology, newly described species, research that produced a result |
| `health` | Treatments approved, diseases pushed back, surgical and diagnostic firsts, public-health wins |
| `technology` | Inventions and deployments that measurably help people or the planet |
| `people` | Human interest, community, kindness, generosity, ordinary people doing something good |
| `culture` | Art and heritage restored or returned to its country, languages revived, landmarks saved, records set |
| `government` | **Outcomes only** — see §3.3 |
| `sport` | **Human moments only** — comebacks, sportsmanship, barriers broken. Never results, standings, transfers, or odds. |

`environment` is expected to dominate simply because animal and conservation news is the
richest and most reliably positive vein available. That is fine and not a flaw.

`sport` is the one category most likely to be cut on taste; nothing else depends on it.

### 3.2 What counts as good news

A story qualifies only if it reports something that **has actually happened or is
measurably underway** — not a plan, a pledge, a forecast, or a study suggesting
something might work someday. Prefer concrete, finished, verifiable outcomes.

Rejected regardless of framing: anything whose core is suffering, disaster, crime, or
loss, even when the article ends hopefully. A rescue after a tragedy is still a tragedy
story.

### 3.3 The politics rule — "outcomes only, no combat"

**Allowed:** a law that measurably helps people, a peace or trade agreement signed, a
treaty ratified, a corruption conviction, a public program that demonstrably worked, a
court ruling that is final and beneficial, a city or agency that fixed something.

**Banned, without exception:** elections, polls, campaigns, candidates, personalities,
scandals, resignations, accusations, predictions, and anything framed as a fight, a
race, or a contest.

Skews global rather than US-partisan. US domestic stories are allowed when they meet the
outcomes-only bar.

**Implementation.** Two lists plus an override rule, all in `editorial.yaml`:

- `banned_terms` — matched case-insensitively on word boundaries in headline and
  summary. Seed list: `election`, `electoral`, `ballot`, `poll`, `polling`, `campaign`,
  `candidate`, `primaries`, `caucus`, `midterm`, `incumbent`, `approval rating`,
  `partisan`, `filibuster`, `shutdown`, `impeach`, `indict`, `scandal`, `subpoena`,
  `slams`, `blasts`, `rips`, `hits back`, `feud`, `spat`, `clash`, `sues`,
  `files suit`, `Democrat`, `Republican`, `GOP`, `left-wing`, `right-wing`.
- `outcome_overrides` — phrases that rescue an otherwise-banned candidate because they
  mark a finished outcome: `court ruled`, `court upheld`, `judge ordered`, `convicted`,
  `treaty ratified`, `agreement signed`, `law took effect`, `bill signed into law`,
  `settlement reached`.
- **Rule:** reject if any `banned_term` matches **and** no `outcome_override` matches.

This list is expected to be tuned during the first few weeks. It is data, not code, so
tuning it requires no code change. The false-positive risk is real and accepted: a
slightly over-eager filter costs us a story, while an under-eager one costs the product
its whole reason for existing.

### 3.4 One story per timeframe

**Exactly one story per edition. Three a day. No more.**

This is the most consequential decision in the spec. Three editions at five stories
would demand 105 non-repeating stories a week, and the good-news ecosystem does not
produce that — "never repeat" turned it into a hard ceiling rather than a stretch goal.
At **21 a week** the arithmetic inverts: the same wide net now feeds a far pickier
filter, the model reads ~80 candidates and returns the single best one, and volume stops
being the binding constraint. Quality becomes the only thing being optimised.

Two useful side effects: the whole day fits on one phone screen without scrolling, and
the dedup memory grows at roughly a fifth of the previous rate.

#### The escalation ladder

**A drought is a malfunction, not a news shortage.** At one story per timeframe across
eight categories, "nothing good happened anywhere on earth" is not a state the world
produces. If the system reports one, the cause is almost certainly local: dead feeds, an
over-firing politics filter, or an over-eager duplicate check. The design treats it that
way — the ladder reaches a long way before giving up, and giving up raises an alarm.

The key realisation: **because nothing is ever repeated, a story only has to be *unseen*,
not *fresh*.** A genuinely good piece from nine days ago that she has never read is worth
more than a mediocre one from this morning. Reaching backwards is therefore nearly free,
and it is the main reason droughts should be almost impossible.

| Tier | Window | Sources | Escalation |
|---|---|---|---|
| 1 | 48 hours | Priority feeds | Normal operation |
| 2 | 7 days | All feeds | Silent, routine |
| 3 | 21 days | All feeds + soft-duplicate candidates released for model judging | Logged |
| 4 | 90 days | All feeds + evergreen reserve | **Logged as a warning** |
| 5 | — | Evergreen reserve only | **Logged as an error, alert raised** |

The quality bar never moves. Only the size of the haystack does.

**Tier 5 — the evergreen reserve.** A curated pool of roughly 100 timeless good stories:
species pulled back from the brink, a disease driven to near-eradication, the ozone layer
healing, a river brought back to life. Each is a real article she has never seen, and
each is still true. These render with **`STILL TRUE`** in place of a timestamp rather
than being dressed up as today's news — the honesty is what makes it work, and it reads
as a feature rather than a fudge.

**Display of older stories.** Anything over three days old shows its date ("BBC ·
Tuesday") instead of a relative time, so nothing is quietly implied to be fresher than
it is.

**Reaching tier 4 or 5 is a diagnostic event.** The alert names the likely cause by
checking, in order: how many feeds returned nothing, how many candidates the politics
filter removed, and how many the duplicate check removed. Two tier-4-or-worse runs in a
rolling week is treated as a broken system, not bad luck.

**If even tier 5 is empty** — which means the reserve is exhausted or the code is
broken — the slot is written empty with its reason, and the page renders a quiet line:
*"A quiet morning. Nothing new made the cut."* An empty slot **does not count as
published** for §4.1's purposes, so later runs inside the same window still try. Once the
window closes, the empty slot stands for the day.

---

## 4. Components

Each module is independently testable and has one job.

| Module | Responsibility | Depends on |
|---|---|---|
| `config.py` | Load `sources.yaml` / `editorial.yaml`, read env, expose typed settings | — |
| `clock.py` | Determine the current slot in local Eastern time; answer "should this run publish?" | config |
| `fetch.py` | Fetch and parse RSS feeds concurrently, tolerate individual failures | config |
| `normalize.py` | Canonical URL keys, title keys, token sets | — |
| `dedup.py` | The permanent memory: read/append `seen.jsonl`, decide "have we shown this?" | normalize |
| `editorial.py` | Good-news and politics filters, applied both pre- and post-model | config |
| `ladder.py` | Own the tier progression: widen window, then sources, then release soft duplicates, then evergreen | config, fetch, dedup |
| `curate.py` | Build the prompt, invoke the `claude` CLI, validate output, retry once | config, editorial |
| `render.py` | Generate `index.html`, archive day pages, `archive/index.html`; validate before returning | — |
| `publish.py` | Stage, commit, rebase, push to GitHub | — |
| `alert.py` | Windows notification + failure log when a run fails | — |
| `cli.py` | Entry point: `run`, `dry-run`, `rebuild`, `doctor` | all |

### 4.1 clock.py — slots and catch-up

Windows Task Scheduler fires at local time and handles daylight saving itself, so none
of the UTC arithmetic a cloud scheduler would need is required here. `clock.py` still
owns slot logic for two reasons: it makes duplicate and catch-up runs harmless, and it
keeps the move to cloud execution cheap.

Slot windows, in local time (`America/New_York` via Python's built-in `zoneinfo`, so the
logic is correct even if the machine's timezone changes):

| Slot | Target | Accepts a run between |
|---|---|---|
| `morning` | 08:00 | 08:00 – 13:59 |
| `afternoon` | 14:00 | 14:00 – 18:59 |
| `evening` | 19:00 | 19:00 – 23:59 |

The windows are deliberately wide and contiguous. Task Scheduler is configured to run a
missed task as soon as possible, so a laptop that was asleep until 11:30 still delivers
a morning edition rather than nothing.

Logic on every run:

1. Compute `now` in `America/New_York`.
2. If `now` falls in no window, exit 0 — "not a publishing window."
3. If `data/editions/<today>.json` already contains this slot **with a story**, exit 0 —
   "already published." An empty slot recorded during a drought (§3.4) does not count;
   the run proceeds and may fill it.
4. Otherwise, publish.

### 4.2 dedup.py — the "never twice" guarantee

Memory lives in `data/seen.jsonl`, one JSON object per line, appended forever. JSON
Lines is chosen so each run adds a handful of lines and the git diff stays clean.

```json
{"url_key":"reuters.com/world/humpback-whale-numbers-recover","title_key":"9f2c...","tokens":["antarctic","humpback","numbers","recover","whale"],"title":"Humpback whale numbers recover in Antarctic","date":"2026-09-07","slot":"morning"}
```

Four layers. **Only the first two can block a story outright.**

| Layer | Method | Effect |
|---|---|---|
| 1. Same link | Exact match on `url_key` | **Hard block, absolute** |
| 2. Same headline | Exact match on `title_key` | **Hard block, absolute** |
| 3. Reworded | Jaccard similarity of `tokens` ≥ **0.75** against the last 18 months | **Soft** — demoted, not removed |
| 4. Same event | The model is shown the last 60 published headlines and asked whether this is the same event | Decides the soft cases |

**Why layer 3 is soft — a defect caught during review.** With the originally specified
0.60 threshold, these two headlines are 0.67 similar:

> "Sea turtle numbers recover in **Florida**"
> "Sea turtle numbers recover in **Australia**"

Four shared tokens out of six — two entirely different stories, one silently destroyed.
A mechanical word-overlap test cannot tell a rewording from a genuinely similar event,
and a hard block built on one will quietly starve the page and look like a news shortage.
So layer 3 now (a) uses a stricter 0.75 threshold, and (b) only **demotes** a candidate
to the back of the queue. A demoted candidate is released for the model to judge at
tier 3 of the ladder (§3.4), and layer 4 makes the actual same-or-different call.

**Net effect:** the guarantees the reader cares about — never the same link, never the
same headline — remain absolute, while the fuzzy layer can no longer cause a drought on
its own.

Duplicates *within* a single run (two feeds carrying the same story) are collapsed by
layers 1–2, then ranked by layer 3.

**Honest limitation:** layers 1 and 2 are perfect. Layer 4 is very good, not perfect. The
same event written up by two outlets with genuinely different wording can still slip
through. This is a known, accepted gap — and the mirror-image risk, blocking two
different stories that merely sound alike, is the one the change above removes.

**Key construction (normalize.py):**

- `url_key` — lowercase host with `www.` removed, path with trailing slash and fragment
  removed, query string kept but with tracking parameters dropped (`utm_*`, `fbclid`,
  `gclid`, `ref`, `source`, `mc_cid`, `mc_eid`, `at_*`, `cmp`, `ito`). Non-tracking
  parameters are kept, because some sites route by `?p=123`.
- `title_key` — SHA-1 of the title lowercased, punctuation stripped, whitespace
  collapsed.
- `tokens` — title lowercased, stopwords and words under three characters removed,
  deduplicated, sorted.

**Growth:** 3 stories a day, about 1,100 a year, at ~200 bytes each — roughly 220KB per
year. A non-issue indefinitely. Layer 3 only compares against the last 18 months; layers
1 and 2 compare against all of history, forever.

### 4.3 curate.py — invoking the model

The `claude` CLI is invoked headless as a subprocess. Verified working shape on this
machine (`C:\Users\kaimo\.local\bin\claude.exe`):

```
claude -p <prompt-from-stdin-or-arg>
       --output-format json
       --model sonnet
       --disallowed-tools "*"
```

`--output-format json` returns an envelope, confirmed by live test:

```json
{"type":"result","subtype":"success","is_error":false,"result":"<the model's text>",
 "session_id":"...","num_turns":1,"total_cost_usd":0,"usage":{...}}
```

`curate.py` therefore does three things in order: parse the envelope, check
`is_error` (the CLI exits non-zero and sets this on auth failure — see §8), then parse
the model's JSON out of `result`.

- **Model:** `sonnet`. Selection and short summarisation do not need Opus, and this runs
  ~90 times a month against a shared subscription budget.
- **Tools disabled.** The model is given text and asked for text. It must not read
  files, run commands, or search. This is enforced with `--disallowed-tools`, not
  requested in the prompt.
- **Input:** the editorial rulebook, the last 60 published headlines, and ~80 surviving
  candidates (title, source, publication time, feed summary truncated to 300
  characters). Passed via a temp file rather than a command-line argument, because the
  prompt is far past any safe Windows command-line length.
- **Output:** a strict JSON array of **three ranked candidates**, best first. Per story:
  `title`, `url`, `source`, `category`, `summary` (2–3 warm sentences in plain English,
  no jargon), `why_good` (one line, recorded for auditing, not displayed). Only one is
  published — the first that survives the §3.3 hard filter and a final dedup check.
  Asking for three costs almost nothing and stops a single post-filter rejection from
  wasting the whole run.
- **Retry:** one retry on non-zero exit or unparseable output. A second failure ends the
  run and triggers an alert (§8).
- **Timeout:** 180 seconds per attempt; a hung CLI must not leave a task running all day.
- **Prompt-injection posture:** feed content is untrusted input. The prompt states that
  candidate text is data to be judged, never instructions to follow, and the output is
  schema-validated and re-filtered in code afterwards, so a malicious headline cannot
  change system behaviour.

### 4.4 render.py — the page

Approved look: **"Scute shell, garden-bed spine"** — see `design/scute-garden.html`,
which is the visual reference the implementation must match.

`index.html` shows **today**, newest timeframe on top, one story each:

```
Stacey Happy News
────
8:00 · 2:00 · [7:00]          <- current slot marked
Last updated 7:04 pm

 ❀ EVENING  7:04 pm
 │  ╭──────────────────────────╮
 ┣──│ GOVERNMENT               │   <- "scute" plate: a turtle
 │  │ Headline, linking out    │      shell plate, ridge down
 │  │ AP · 3 hours ago         │      the middle
 │  │ Two or three sentences.  │
 │  ╰──────────────────────────╯
 ❀ AFTERNOON  2:11 pm
 │  ╭──────────────────────────╮
 ┣──│ ...                      │
 │  ╰──────────────────────────╯
 ❀ MORNING  8:03 am
    ╰──────────────────────────╯

 Archive
```

Structural elements each encode something real rather than decorating: the **stem** is
the day, a **bloom** opens each timeframe, a **leaf** joins each story to the day, and
the **plate** is a turtle scute. Turtles and flowers sit in the background at low opacity.

**Design tokens** (light, then dark):

| Role | Light | Dark |
|---|---|---|
| Ground | `#EFF3E7` | `#132019` |
| Plate | `#E4ECD8` | `#1D2C23` |
| Plate edge | `#CBDAB8` | `#31493A` |
| Ink | `#16291D` | `#E7EFE3` |
| Muted | `#5D7566` | `#93A996` |
| Accent (berry) | `#7B2D4E` | `#EE93AC` |
| Stem | `#6E9159` | `#6C9A5C` |

**Type:** Fraunces (masthead and headlines), Newsreader (story text), Alegreya Sans
(labels, times, sources). Loaded from Google Fonts with real fallback stacks.

- **The "Last updated" line is required, not decorative.** It is the reader's only
  signal that the machine is healthy. If the page is stale, it says so plainly rather
  than looking like a normal day with less news.
- Mobile-first CSS in `assets/style.css`. System font stack, ~17px base, generous
  line-height, `max-width: 38rem`, respects `prefers-color-scheme` for dark mode.
- No images, no JavaScript, no external requests. The page is self-contained apart from
  one stylesheet.
- Links open in a new tab with `rel="noopener noreferrer"`. All model-produced text is
  HTML-escaped on render.
- At midnight the next run writes a fresh `index.html`; the finished day already exists
  at `archive/YYYY-MM-DD.html`.
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
  health.json             # last successful run, consecutive-failure counter, drought log
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

`stories` holds exactly one entry, or is empty during a drought — in which case `note`
carries the quiet line the page displays (§3.4) and the slot does not count as published
(§4.1).

---

## 6. Scheduling

Three Windows Scheduled Tasks, matching the shape of the existing `TIR_AutoPublish_*`
entries:

| Task name | Trigger |
|---|---|
| `HappyNews_Morning` | Daily 08:00 |
| `HappyNews_Afternoon` | Daily 14:00 |
| `HappyNews_Evening` | Daily 19:00 |

Each runs `E:\Satcey Happy News\publish.bat <slot>` with these settings:

- **Run task as soon as possible after a scheduled start is missed** — enabled. This is
  what turns "laptop was asleep at 8" into "morning edition at 11:30" instead of nothing.
- **Wake the computer to run this task** — enabled. Recovers sleeping-laptop runs
  outright; does nothing if the machine is fully powered off.
- **Run whether user is logged on or not** — enabled.
- Stop the task if it runs longer than 15 minutes.

Task Scheduler handles local time and daylight saving natively, so no UTC mapping is
needed. `clock.py`'s already-published check makes a catch-up run that overlaps a normal
run harmless.

**Stated expectation:** the page updates within a few minutes of 8:00 am, 2:00 pm, and
7:00 pm when the machine is on or asleep, and not at all while it is powered off. That
last case is the accepted cost of running locally, and §8 makes it visible rather than
silent.

---

## 7. Credentials

**There is no API key.** The `claude` CLI authenticates with the existing Claude
subscription via a stored OAuth session.

**Known risk, discovered during design:** a live test on 2026-09-07 returned
`Failed to authenticate: OAuth session expired and could not be refreshed`. The
standalone CLI's credentials are separate from the desktop app's, and they had lapsed.

- **Fix:** run `claude` interactively once and sign in. Regular 3×/day use is expected
  to keep the session refreshed thereafter.
- **This is the single most likely cause of long-term silent failure**, which is why
  §8's alerting and §4.4's "Last updated" line are requirements rather than polish.
- `cli.py doctor` performs a cheap authenticated round-trip and reports pass/fail, so
  the session can be checked without waiting for a scheduled run to break.

Nothing secret is committed. The repository is public; `.gitignore` excludes `.env` and
all local logs.

---

## 8. Failure handling

| Failure | Behaviour |
|---|---|
| One or more feeds unreachable | Log and continue with the feeds that worked |
| All feeds unreachable | Fail the run, alert |
| `claude` CLI auth expired | Fail the run, alert with the specific remedy ("run `claude` and sign in") |
| CLI returns invalid output or non-zero | Retry once, then fail the run and alert |
| CLI exceeds the 180s timeout | Kill it, retry once, then fail and alert |
| Render validation fails | Abort before committing; nothing is published |
| Git push conflict | `git pull --rebase` and retry once |
| Ladder reached tier 4 | Publish, but log a warning naming the likely cause (dead feeds / politics filter / duplicate check counts) |
| Ladder reached tier 5 | Publish from the evergreen reserve, **raise an alert** — the live pipeline is not working |
| Two tier-4-or-worse runs in a rolling week | Escalated alert: treated as a broken system, not bad luck |
| Ladder exhausted, zero stories | Write an empty slot with its reason, record a drought in `health.json`, **raise an alert** — at one story across eight categories this indicates a defect, not a quiet news day |
| Machine powered off at slot time | Task Scheduler catch-up publishes on next wake if still inside the window (§4.1) |
| Any failed run | Windows toast notification + a line in `logs/failures.log` |
| 3 consecutive failed runs | Escalated notification — the system is broken, not merely unlucky |

**"Failed run" means a run that entered a publishing window and then errored.** Runs
that exit early — outside a window, or slot already published — are not failures and
never touch the counter. A successful publish resets the counter to zero.

**Staleness is visible in two independent places:** to the operator via notification and
log, and to the reader via the "Last updated" line on the page itself. Neither depends
on the other working.

---

## 9. Testing

`pytest`, with **no network access and no CLI invocation in any test**. All feed XML and
model responses are saved fixtures.

| Test file | Covers |
|---|---|
| `test_clock.py` | Slot detection at 07:59 / 08:00 / 13:59 / 14:00 / 23:59; both DST changeover weekends; already-published short-circuit |
| `test_normalize.py` | Tracking-parameter stripping, `www.`, trailing slashes, fragments, casing, non-tracking params preserved |
| `test_dedup.py` | Exact URL match, exact title match, Jaccard boundaries at 0.74 / 0.75 / 0.76, **the Florida/Australia turtle pair must NOT be blocked**, soft-demotion does not remove, within-run collapsing, 18-month window edge |
| `test_ladder.py` | Each tier fires only when the one above returns nothing; the quality bar is identical at every tier; tier 4 and 5 raise the right alerts; evergreen items render `STILL TRUE`; an exhausted ladder writes an empty slot that does not count as published |
| `test_editorial.py` | Each banned term fires; each outcome override rescues; false-positive guards (`primary school`, `clash of colours`) |
| `test_curate.py` | Mocked subprocess: valid envelope parses, `is_error: true` handled, malformed JSON triggers exactly one retry, timeout kills and retries, schema violations rejected |
| `test_render.py` | Golden-file comparison for a full day, a single-slot day, a short edition with a note, an empty archive, and HTML-escaping of hostile story text |

`cli.py dry-run` builds the page locally, prints what would publish, and writes nothing —
so the output can be reviewed before it ever goes live. `cli.py doctor` checks CLI auth,
feed reachability, and git push access in one command.

---

## 10. Repository layout

```
happy-news/                         (= E:\Satcey Happy News)
  .nojekyll
  .gitignore
  README.md
  requirements.txt
  publish.bat                       # what Task Scheduler runs
  index.html                        # generated
  assets/style.css                  # hand-written
  archive/
    index.html                      # generated
    2026-09-07.html                 # generated
  data/
    seen.jsonl
    health.json
    editions/2026-09-07.json
  logs/                             # gitignored
    failures.log
  feeds/
    sources.yaml                    # the feed list
    editorial.yaml                  # categories, banned terms, overrides
    evergreen.yaml                  # the tier-5 reserve (~100 timeless stories)
  src/happy_news/
    __init__.py config.py clock.py fetch.py normalize.py
    dedup.py editorial.py ladder.py curate.py render.py publish.py alert.py cli.py
  tests/
    fixtures/ test_*.py
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
| Storage | $0 |
| Model usage | $0 in cash — consumes the existing Claude subscription's usage allowance, shared with other work on this machine |
| Maintenance | Occasional tuning of `editorial.yaml`; re-authenticating the CLI if the session lapses |

Reconsider the GitHub Actions + API key route (~$1–4/month) if missed runs or auth
lapses prove annoying in practice. §2 keeps that move cheap by design.

---

## 12. Prerequisites before implementation

1. **Sign the CLI in.** Run `claude` in a terminal and complete sign-in; confirm with
   `cli.py doctor` once it exists. Blocking — nothing works until this is done.
2. **Create the public repository** `TheInsideRip/happy-news` with Pages enabled on
   branch `main`, folder `/`. Awaiting explicit go-ahead; nothing will be created on
   GitHub without it.

Neither blocks writing the implementation plan.
