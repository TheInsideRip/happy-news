"""Build the page. Every value that reaches HTML is escaped -- feed and model
text is untrusted input."""
from __future__ import annotations

import html
import re
from datetime import date, datetime

from .clock import SLOT_ORDER

SLOT_TIMES = [("8:00", "morning"), ("2:00", "afternoon"), ("7:00", "evening")]

TURTLE = (
    '<symbol id="turtle" viewBox="0 0 100 80">'
    '<ellipse cx="70" cy="21" rx="9" ry="6" transform="rotate(-34 70 21)"/>'
    '<ellipse cx="70" cy="59" rx="9" ry="6" transform="rotate(34 70 59)"/>'
    '<ellipse cx="27" cy="22" rx="8" ry="5.5" transform="rotate(34 27 22)"/>'
    '<ellipse cx="27" cy="58" rx="8" ry="5.5" transform="rotate(-34 27 58)"/>'
    '<ellipse cx="16" cy="40" rx="6" ry="3"/>'
    '<ellipse cx="84" cy="40" rx="9.5" ry="7"/>'
    '<ellipse cx="48" cy="40" rx="30" ry="23"/>'
    '<g fill="none" stroke="#fff" stroke-width="1.7" opacity=".45">'
    '<ellipse cx="48" cy="40" rx="8" ry="7"/>'
    '<ellipse cx="48" cy="24" rx="7" ry="5.5"/>'
    '<ellipse cx="48" cy="56" rx="7" ry="5.5"/>'
    '<ellipse cx="30" cy="40" rx="6.5" ry="7"/>'
    '<ellipse cx="66" cy="40" rx="6.5" ry="7"/>'
    "</g></symbol>"
)
FLOWER = (
    '<symbol id="flower" viewBox="0 0 100 100">'
    + "".join(
        f'<ellipse cx="50" cy="27" rx="11.5" ry="19" transform="rotate({d} 50 50)"/>'
        for d in (0, 72, 144, 216, 288)
    )
    + '<circle cx="50" cy="50" r="8.5" fill="#fff" opacity=".5"/></symbol>'
)
LEAF = (
    '<symbol id="leaf" viewBox="0 0 100 60">'
    '<path d="M2 30 C 30 -4, 72 -4, 98 30 C 72 64, 30 64, 2 30 Z"/></symbol>'
)


def _e(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _format_time(value) -> str:
    """Format an ISO-8601 timestamp as e.g. '8:03 am'. Empty string if it
    can't be parsed -- a malformed or missing timestamp must never crash the
    page, only fall back to no time shown."""
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return ""
    return moment.strftime("%I:%M %p").lstrip("0").lower()


def _day_stamp(value) -> str:
    """'Sunday 7 Sep' from an ISO date string. Empty string if it can't be
    parsed -- a malformed date must degrade the heading, never crash the page."""
    try:
        day = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return ""
    # %-d is a glibc strftime extension; it raises ValueError on Windows.
    return f"{day.strftime('%A')} {day.day} {day.strftime('%b')}"


def _updated_heading(edition: dict, current: str | None) -> str:
    """The reader's only staleness signal, and the one line on the page that
    has to be able to say "this is old" all by itself.

    It used to read `Last updated 5:10 pm` -- no date. The most likely
    real-world failure is the laptop being off or asleep: no run happens, so
    there is no toast and no log line either, and a page a week stale was
    byte-identical to a fresh one. Naming the day makes the page itself carry
    the evidence, with no run required. It also stops the top block being the
    only undated thing on a front page that now date-stamps every earlier day.

    `updated_text` is normally stamped by the publish step; when it's missing
    (e.g. this function is exercised on its own) fall back to the newest
    slot's own published time rather than silently dropping the line."""
    updated = edition.get("updated_text") or ""
    if not updated and current:
        updated = _format_time(edition.get("slots", {}).get(current, {}).get("published_at"))
    parts = [part for part in (_day_stamp(edition.get("date")), updated) if part]
    if not parts:
        return "Last updated"
    return "Last updated " + ", ".join(_e(part) for part in parts)


def _archive_heading(value) -> str:
    """'Monday, September 7' -- the dated heading used for a past day, both on
    its own archive page and for each earlier day on the front page."""
    try:
        day = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return _e(value)
    # %-d is a glibc strftime extension; it raises ValueError on Windows.
    return f"{day.strftime('%A, %B')} {day.day}"


def _times_strip(current: str | None) -> str:
    cells = []
    for label, slot in SLOT_TIMES:
        cls = ' class="on"' if slot == current else ""
        cells.append(f"<span{cls}>{label}</span>")
    return '<div class="sn-times">' + "<i>·</i>".join(cells) + "</div>"


def _story_html(story: dict) -> str:
    stamp = "STILL TRUE" if story.get("evergreen") else _e(story.get("age_text", ""))
    meta = f'{_e(story.get("source"))} · {stamp}' if stamp else _e(story.get("source"))
    return (
        '<article class="plate">'
        '<svg class="leaf" viewBox="0 0 100 60" fill="currentColor" aria-hidden="true"><use href="#leaf"/></svg>'
        f'<p class="cat">{_e(story.get("label", "world"))}</p>'
        f'<h2 class="hl"><a href="{_e(story.get("url"))}" target="_blank" rel="noopener noreferrer">{_e(story.get("title"))}</a></h2>'
        f'<p class="meta">{meta}</p>'
        f'<p class="sum">{_e(story.get("summary"))}</p>'
        "</article>"
    )


def _slot_html(name: str, block: dict) -> str:
    bloom = '<svg class="bloom" viewBox="0 0 100 100" fill="currentColor" aria-hidden="true"><use href="#flower"/></svg>'
    when = _e(block.get("time_text") or _format_time(block.get("published_at")))
    body = (
        "".join(_story_html(s) for s in block.get("stories", []))
        or f'<p class="waiting">{_e(block.get("note"))}</p>'
    )
    return (
        '<section class="slot">'
        f'<p class="slot-label">{bloom}{name.capitalize()} <b>{when}</b></p>'
        f"{body}</section>"
    )


def render_day(edition: dict, *, is_today: bool) -> str:
    slots = edition.get("slots", {})
    present = [s for s in SLOT_ORDER if s in slots]
    current = present[0] if present else None
    body = "".join(_slot_html(name, slots[name]) for name in present)

    if is_today:
        heading = _updated_heading(edition, current)
    else:
        heading = _archive_heading(edition.get("date"))

    nav = '<a href="archive/">Archive</a>' if is_today else '<a href="../">Today</a>'
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stacey Happy News</title>
<link rel="stylesheet" href="{'assets' if is_today else '../assets'}/style.css">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Newsreader:opsz,wght@6..72,400&family=Alegreya+Sans:wght@400;700&display=swap">
</head><body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">{TURTLE}{FLOWER}{LEAF}</svg>
<div class="sn-bg" aria-hidden="true">
<svg width="150" height="120" viewBox="0 0 100 80" fill="var(--st)" opacity=".13" style="top:220px;left:-40px"><use href="#turtle"/></svg>
<svg width="46" height="46" viewBox="0 0 100 100" fill="var(--br)" opacity=".10" style="top:140px;right:8px"><use href="#flower"/></svg>
</div>
<h1 class="sn-title">Stacey<br>Happy News</h1>
<div class="sn-rule"></div>
{_times_strip(current if is_today else None)}
<p class="sn-updated">{heading}</p>
<div class="day">{body}</div>
<p class="sn-foot">{nav}</p>
</body></html>"""


def _day_slots_html(edition: dict) -> tuple[str, str | None]:
    """Render one edition's slot sections. Returns (html, newest-present-slot)
    -- shared by render_day and render_front so both build a day's story
    plates identically."""
    slots = edition.get("slots", {})
    present = [s for s in SLOT_ORDER if s in slots]
    current = present[0] if present else None
    body = "".join(_slot_html(name, slots[name]) for name in present)
    return body, current


def render_front(editions: list[dict]) -> str:
    """Render the front page: `editions[0]` is today, and any further
    elements are previous days, already in reverse-chronological (newest
    first) order -- the caller decides how many (the brief: today plus up to
    six previous, i.e. the last 7 days; older days stay in the archive only).

    This is one continuous page, not several render_day() pages concatenated
    -- there is a single masthead, times strip and stylesheet link at the
    top. Each earlier day gets its own rule-and-date heading, reusing the
    exact rule/heading pattern already used once at the top of every page,
    so the boundary between days reads as a natural continuation of the
    existing design while scrolling rather than a new page bolted on.

    render_day itself is untouched: archive pages keep rendering exactly one
    day each.
    """
    if not editions:
        raise ValueError("render_front requires at least one edition (today)")

    today_edition, *earlier_editions = editions

    today_body, today_current = _day_slots_html(today_edition)
    today_heading = _updated_heading(today_edition, today_current)

    sections = [f'<p class="sn-updated">{today_heading}</p><div class="day">{today_body}</div>']

    for edition in earlier_editions:
        body, _ = _day_slots_html(edition)
        heading = _archive_heading(edition.get("date"))
        sections.append(
            '<div class="sn-rule day-rule"></div>'
            f'<p class="sn-updated">{heading}</p>'
            f'<div class="day">{body}</div>'
        )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stacey Happy News</title>
<link rel="stylesheet" href="assets/style.css">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Newsreader:opsz,wght@6..72,400&family=Alegreya+Sans:wght@400;700&display=swap">
</head><body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">{TURTLE}{FLOWER}{LEAF}</svg>
<div class="sn-bg" aria-hidden="true">
<svg width="150" height="120" viewBox="0 0 100 80" fill="var(--st)" opacity=".13" style="top:220px;left:-40px"><use href="#turtle"/></svg>
<svg width="46" height="46" viewBox="0 0 100 100" fill="var(--br)" opacity=".10" style="top:140px;right:8px"><use href="#flower"/></svg>
</div>
<h1 class="sn-title">Stacey<br>Happy News</h1>
<div class="sn-rule"></div>
{_times_strip(today_current)}
{"".join(sections)}
<p class="sn-foot"><a href="archive/">Archive</a></p>
</body></html>"""


def render_archive_index(days: list[str]) -> str:
    items = "".join(
        f'<li><a href="{_e(d)}.html">{_e(date.fromisoformat(d).strftime("%A, %B "))}{date.fromisoformat(d).day}</a></li>'
        for d in sorted(days, reverse=True)
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stacey Happy News — Archive</title>
<link rel="stylesheet" href="../assets/style.css">
</head><body>
<h1 class="sn-title">Archive</h1>
<div class="sn-rule"></div>
<ul class="archive-list">{items}</ul>
<p class="sn-foot"><a href="../">Today</a></p>
</body></html>"""


_HREF = re.compile(r'href="([^"]+)"')
_SUM = re.compile(r'<p class="sum">(.*?)</p>', re.DOTALL)


def validate(page: str) -> None:
    if 'class="plate"' not in page:
        raise ValueError("page contains no story")
    # A summary that is empty *or whitespace-only* must be rejected: the
    # model is untrusted, and "   " renders as a visible, apparently-valid
    # <p class="sum">   </p> that carries no readable text. Checking the
    # rendered block's content for at least one non-whitespace character
    # (rather than matching the literal empty-tag string) catches both.
    for summary in _SUM.findall(page):
        if not summary.strip():
            raise ValueError("page contains an empty summary")
    for href in _HREF.findall(page):
        if href.startswith(("http://", "https://")):
            continue
        if href.startswith(("assets/", "../assets/", "archive/", "../", "#")) or href.endswith(".html"):
            continue
        raise ValueError(f"page contains a non-http link: {href}")
