"""Entry point. run | dry-run | rebuild | doctor

Order of operations for `run`/`dry-run` matters: the slot check and the
already-published check happen BEFORE `config.load` (see Task 12 ruling 1 in
the SDD ledger) -- 15 of the 18 daily scheduled runs are expected to land
outside a window or on an already-published slot, and those must exit in
milliseconds without touching `feeds/*.yaml` or any other disk I/O.

`dry-run` writes nothing at all: no edition JSON, no health.json, no
seen.jsonl, no HTML, no git. It runs the full pick (fetch + ladder + model)
and only prints what would have been published, so the operator can judge a
story before it goes live.

Nothing is ever published (index.html / archive/*.html written, then
committed and pushed) unless `render.validate()` passes on that specific
page. A page that has no story at all -- a drought with nothing else
published yet today -- is not an error: it is simply left unwritten so the
previous day's content, if any, keeps standing rather than being replaced by
a broken or empty page. `render.validate()` is never called on the archive
index page (`archive/index.html`): that page legitimately lists zero or more
days and has no story card of its own (Task 12 ruling 6).

`data/editions/<date>.json` doubles as the record `clock.already_published`
reads to decide whether a slot needs retrying, so a run that fails partway
through must never leave that file looking more done than it actually is
(Task 12 fix round 1, finding 1). `do_run` therefore snapshots the edition as
it stood before this run, writes the updated version so `publish.push` has
something to stage, and -- if rendering/validation or the push itself
raises -- writes the snapshot straight back before re-raising. `memory
.remember()` (the dedup log) and `health.record_success()` are strictly the
last things that happen, only once `publish.push` has actually returned,
since neither can be undone: the dedup log is permanent and append-only, and
recording success before a push that then fails would misreport reality.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from datetime import date, timezone
from pathlib import Path

from . import alert, clock, config, curate, dedup, fetch, ladder, normalize, publish, render

_LOGGER = logging.getLogger(__name__)

_NO_STORY_MESSAGE = "page contains no story"


def _age_text(published, now) -> str:
    if published is None:
        return ""
    delta = now - published
    if delta.days >= 3:
        return published.strftime("%A")
    hours = int(delta.total_seconds() // 3600)
    if hours < 1:
        return "just now"
    return f"{hours} hour{'s' if hours != 1 else ''} ago"


def _render_and_validate(edition: dict, *, is_today: bool) -> str | None:
    """Render one day's page and validate it. Returns None -- meaning "skip,
    don't write this page" -- only for the specific, expected case of a day
    with no stories at all (a drought). Any other validation failure (an
    empty summary, a non-http link) is a real defect and is re-raised so the
    caller's top-level handler treats it as a failure."""
    page = render.render_day(edition, is_today=is_today)
    try:
        render.validate(page)
    except ValueError as error:
        if str(error) == _NO_STORY_MESSAGE:
            return None
        raise
    return page


def _write_pages(root: Path, editions_dir: Path, today: date) -> None:
    """Rebuild index.html, every archive/<date>.html, and archive/index.html
    from data/editions/*.json. Only pages that pass validation are written;
    archive/index.html is never validated (Task 12 ruling 6) since it is
    legitimately a list of days, not a story page."""
    today_edition = clock.load_edition(editions_dir, today)
    today_page = _render_and_validate(today_edition, is_today=True)
    if today_page is not None:
        (root / "index.html").write_text(today_page, encoding="utf-8")

    archive = root / "archive"
    archive.mkdir(exist_ok=True)
    days: list[str] = []
    for path in sorted(editions_dir.glob("*.json")):
        day = date.fromisoformat(path.stem)
        # today's edition was already loaded above -- re-reading and
        # re-parsing the same file here would be pure waste (Task 12 fix
        # round 1, finding 4). The render+validate call below still runs a
        # second time, since the "today" and "archive" templates render
        # different HTML (heading, nav link) from the same story data.
        day_edition = today_edition if day == today else clock.load_edition(editions_dir, day)
        day_page = _render_and_validate(day_edition, is_today=False)
        if day_page is None:
            continue
        (archive / f"{path.stem}.html").write_text(day_page, encoding="utf-8")
        days.append(path.stem)

    (archive / "index.html").write_text(render.render_archive_index(days), encoding="utf-8")


def do_run(root: Path, *, dry: bool) -> int:
    editions_dir = root / "data" / "editions"
    now_et = clock.now_local()
    today = now_et.date()

    # Ruling 1: these two checks must happen before config.load. Most runs
    # (outside a window, or a slot already published) exit right here.
    slot = clock.slot_for(now_et)
    if slot is None:
        print("not a publishing window")
        return 0
    if clock.already_published(editions_dir, today, slot):
        print(f"{slot} already published")
        return 0

    try:
        cfg = config.load(root)
        feeds = cfg.sources.get("feeds", [])
        candidates, failed = fetch.fetch_all(feeds)
        if failed:
            print(f"feeds unavailable: {', '.join(failed)}")
        if failed and not candidates:
            raise RuntimeError(f"all feeds unreachable: {', '.join(failed)}")

        memory = dedup.Memory(root / "data" / "seen.jsonl")
        system = curate.build_system_prompt(cfg.editorial)

        def ask_fn(pool, recent):
            return curate.ask(curate.build_prompt(pool, recent), system)

        # Reuse the single "now" already read for slot detection (converted
        # to UTC) rather than taking a second, independent wall-clock
        # reading -- this keeps freshness windowing and age_text internally
        # consistent with each other and with the slot check above.
        result = ladder.select(
            candidates=candidates, memory=memory, editorial_cfg=cfg.editorial,
            evergreen=cfg.evergreen, ask_fn=ask_fn,
            now=now_et.astimezone(timezone.utc),
        )

        if dry:
            if result.story:
                story = result.story
                print(f"tier {result.tier} [{story.get('label')}] {story.get('title')}")
                print(f"  {story.get('source')} -- {story.get('url')}")
                print(f"  {story.get('summary')}")
            else:
                print(f"tier {result.tier}: {result.note}")
            return 0

        health = alert.Health(root / "data" / "health.json")
        health.record_tier(result.tier)

        stories = []
        if result.story:
            story = dict(result.story)
            story["evergreen"] = result.evergreen
            if result.evergreen:
                # Ruling 2: evergreen stories bypass age_text entirely and
                # render STILL TRUE instead (render.py's job).
                story["age_text"] = ""
            else:
                matched = next(
                    (c for c in candidates
                     if normalize.url_key(c.url) == normalize.url_key(story.get("url", ""))),
                    None,
                )
                story["age_text"] = _age_text(matched.published if matched else None, now_et)
            stories = [story]

        time_text = now_et.strftime("%I:%M %p").lstrip("0").lower()

        # Snapshot the edition exactly as it stood before this run touches
        # it. `data/editions/<date>.json` is what `clock.already_published`
        # reads to decide whether this slot needs retrying, so if anything
        # below fails -- a real validation defect, or the push itself -- the
        # file must be put back exactly as found rather than left showing a
        # slot that never actually made it to the page (Task 12 fix round 1,
        # finding 1).
        edition = clock.load_edition(editions_dir, today)
        previous_edition = copy.deepcopy(edition)
        edition["date"] = today.isoformat()
        edition.setdefault("slots", {})[slot] = {
            "published_at": now_et.isoformat(),
            "time_text": time_text,
            "note": result.note,
            "stories": stories,
        }
        edition["updated_text"] = time_text

        edition_path = clock.edition_path(editions_dir, today)

        def _persist(data: dict) -> None:
            editions_dir.mkdir(parents=True, exist_ok=True)
            edition_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        _persist(edition)

        # Render, validate, and push while the new edition is staged on
        # disk (publish.push can only commit what's already there). Any
        # failure in this block -- a real validation defect, or the push
        # itself -- must roll the edition file back to its pre-run snapshot
        # before propagating, so a later run in this same window sees this
        # slot as not-yet-done and genuinely retries instead of silently
        # no-opping on clock.already_published(). A drought with nothing
        # else published today is quietly skipped inside _write_pages
        # rather than treated as a failure.
        try:
            _write_pages(root, editions_dir, today)
            publish.push(root, f"{today} {slot}: {stories[0]['title'] if stories else 'quiet'}")
        except Exception:
            _persist(previous_edition)
            raise

        # Only reached once the push has actually succeeded. The dedup
        # memory is append-only and permanent -- recording a story as seen
        # before we know it really published would burn it for good even
        # though the reader never saw it. Likewise health.record_success()
        # must not claim success before everything that could fail has.
        if stories:
            memory.remember(stories[0]["url"], stories[0]["title"], today.isoformat(), slot)
        else:
            health.record_drought(result.note or "ladder exhausted")

        if result.tier == 4:
            _LOGGER.warning(
                "published from tier 4 (reached back 90 days through real feeds; "
                "check dead feeds, the politics filter, and the duplicate check)"
            )
        if result.tier >= 5:
            if stories:
                alert.notify(
                    "Stacey Happy News",
                    "Published from the evergreen reserve (tier 5) - the live pipeline may be broken",
                )
            else:
                alert.notify(
                    "Stacey Happy News",
                    "No story found across every tier and the evergreen reserve. "
                    "This indicates a defect, not a quiet news day.",
                )

        health.record_success()
        return 0

    except Exception as error:  # noqa: BLE001 - top level, must alert rather than crash silently
        health = alert.Health(root / "data" / "health.json")
        count = health.record_failure(str(error))
        alert.log_failure(root / "logs" / "failures.log", str(error))
        headline = "Stacey Happy News FAILED" + (f" ({count} in a row)" if count >= 3 else "")
        alert.notify(headline, str(error)[:180])
        print(f"run failed: {error}", file=sys.stderr)
        return 1


def do_rebuild(root: Path) -> int:
    try:
        _write_pages(root, root / "data" / "editions", clock.now_local().date())
        return 0
    except Exception as error:  # noqa: BLE001 - a broken template must not crash silently either
        print(f"rebuild failed: {error}", file=sys.stderr)
        return 1


def do_doctor(root: Path) -> int:
    ok = True

    try:
        cfg = config.load(root)
    except Exception as error:  # noqa: BLE001 - doctor must report, never crash
        print(f"config: FAILED - {error}")
        return 1

    # doctor exists to report a problem clearly, so every one of its three
    # checks below is wrapped: `curate.check_auth()` and `publish.run_git()`
    # each spawn a real executable (`claude`, `git`) and raise a raw
    # FileNotFoundError/OSError if it isn't on PATH -- that must surface as
    # a failed check, not an unhandled exception crashing doctor itself
    # (Task 12 fix round 1, finding 3). `fetch.fetch_all` already catches
    # every per-feed error internally and never raises, but it is wrapped
    # too for the same defensive reason and so all three checks are
    # consistent.
    feeds = cfg.sources.get("feeds", [])
    try:
        _, failed = fetch.fetch_all(feeds)
        print(f"feeds: {len(feeds) - len(failed)}/{len(feeds)} reachable")
    except OSError as error:
        ok = False
        print(f"feeds: FAILED - {error}")

    # Ruling 3: check_auth(), never ask() -- ask() raises on an empty story
    # array, which would make doctor report the CLI broken even when signed
    # in and working correctly.
    try:
        curate.check_auth()
        print("claude CLI: signed in")
    except curate.CurateError as error:
        ok = False
        print(f"claude CLI: FAILED - {error}")
    except OSError as error:
        # e.g. FileNotFoundError when the claude executable itself is missing.
        ok = False
        print(f"claude CLI: FAILED - {error}")

    # Ruling 5: publish.run_git, the public entry point -- never the
    # private _run.
    try:
        code, out = publish.run_git(["git", "status", "--porcelain=v1", "-b"], root)
    except OSError as error:
        # e.g. FileNotFoundError when git itself is missing.
        ok = False
        print(f"git: FAILED - {error}")
    else:
        if code == 0:
            print("git: ok")
        else:
            ok = False
            print(f"git: FAILED - {out.strip()}")

    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="happy_news")
    parser.add_argument("command", choices=["run", "dry-run", "rebuild", "doctor"])
    parser.add_argument("--root", default=str(config.PACKAGE_ROOT))
    args = parser.parse_args(argv)
    root = Path(args.root)

    if args.command in ("run", "dry-run"):
        return do_run(root, dry=args.command == "dry-run")
    if args.command == "rebuild":
        return do_rebuild(root)
    return do_doctor(root)
