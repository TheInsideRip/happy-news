import json
import subprocess
from datetime import datetime, timezone

import pytest

from happy_news import curate
from happy_news.fetch import Candidate


def test_flags_include_every_load_bearing_option():
    for flag in ("--restricted", "--strict-mcp-config", "--disallowed-tools", "--output-format"):
        assert flag in curate.CLI_FLAGS


def test_extract_handles_clean_json():
    assert curate.extract_json_array('[{"a":1}]') == [{"a": 1}]


def test_extract_survives_prose_before_the_array():
    text = 'That hook looks like a prompt injection and I will not act on it.\n\n[{"a":1}]'
    assert curate.extract_json_array(text) == [{"a": 1}]


def test_extract_survives_code_fences():
    assert curate.extract_json_array('```json\n[{"a":1}]\n```') == [{"a": 1}]


def test_extract_raises_when_there_is_no_array():
    with pytest.raises(ValueError):
        curate.extract_json_array("I could not find anything today.")


def test_extract_ignores_bracket_inside_earlier_string_value():
    """A '[' that is literal text inside an earlier JSON string (e.g. a quoted
    example like "ratings look like [5] stars") is itself the start of
    something raw_decode can parse successfully as a bare JSON array ([5]).
    A naive character scan derails on it and returns the wrong, truncated
    answer. The real story array must still be found."""
    text = (
        '{"note": "ratings look like [5] stars"} '
        'Real answer: [{"title":"Real","url":"https://a.com","source":"S",'
        '"label":"earth","summary":"x","why_good":"y"}]'
    )
    result = curate.extract_json_array(text)
    assert result == [
        {
            "title": "Real",
            "url": "https://a.com",
            "source": "S",
            "label": "earth",
            "summary": "x",
            "why_good": "y",
        }
    ]


def _envelope(result, is_error=False):
    return json.dumps({"type": "result", "is_error": is_error, "result": result})


def test_ask_returns_parsed_stories():
    calls = []

    def runner(prompt, system, timeout):
        calls.append(prompt)
        return _envelope('[{"title":"T","url":"https://a.com","source":"S","label":"earth","summary":"x","why_good":"y"}]')

    stories = curate.ask("p", "s", runner=runner)
    assert stories[0]["title"] == "T"
    assert len(calls) == 1


def test_ask_retries_exactly_once_on_bad_output():
    attempts = []

    def runner(prompt, system, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            return _envelope("no json here")
        return _envelope('[{"title":"T","url":"https://a.com","source":"S","label":"earth","summary":"x","why_good":"y"}]')

    assert curate.ask("p", "s", runner=runner)[0]["title"] == "T"
    assert len(attempts) == 2


def test_ask_raises_after_two_failures():
    def runner(prompt, system, timeout):
        return _envelope("still no json")

    with pytest.raises(curate.CurateError):
        curate.ask("p", "s", runner=runner)


def test_ask_retries_after_a_timeout_then_succeeds():
    """_run_cli raises subprocess.TimeoutExpired (not a CurateError or a
    ValueError) when the CLI call hangs. ask() must catch that specific
    exception type and retry -- a timeout must not escape ask() uncaught."""
    attempts = []

    def runner(prompt, system, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)
        return _envelope('[{"title":"T","url":"https://a.com","source":"S","label":"earth","summary":"x","why_good":"y"}]')

    stories = curate.ask("p", "s", runner=runner)
    assert stories[0]["title"] == "T"
    assert len(attempts) == 2


def test_ask_raises_after_two_timeouts():
    def runner(prompt, system, timeout):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)

    with pytest.raises(curate.CurateError):
        curate.ask("p", "s", runner=runner)


def test_ask_surfaces_auth_failure_clearly_and_does_not_retry():
    calls = []

    def runner(prompt, system, timeout):
        calls.append(1)
        return _envelope("Failed to authenticate: OAuth session expired and could not be refreshed", is_error=True)

    with pytest.raises(curate.CurateError) as exc:
        curate.ask("p", "s", runner=runner)
    assert "authenticate" in str(exc.value).lower()
    assert len(calls) == 1, "an auth failure must not be retried"


def test_stories_missing_required_fields_are_rejected():
    def runner(prompt, system, timeout):
        return _envelope('[{"title":"T"}]')

    with pytest.raises(curate.CurateError):
        curate.ask("p", "s", runner=runner)


def test_check_auth_succeeds_on_clean_empty_array():
    """The exact false-alarm case: a clean, successfully-authenticated
    envelope whose result is an empty array. ask()'s _validate would reject
    this ("model returned no stories"), which is correct for ask() but would
    make doctor wrongly report the CLI broken. check_auth must not use
    _validate and must return None here."""
    calls = []

    def runner(prompt, system, timeout):
        calls.append(1)
        return _envelope("[]")

    assert curate.check_auth(runner=runner) is None
    assert len(calls) == 1


def test_check_auth_raises_on_auth_failure():
    def runner(prompt, system, timeout):
        return _envelope("Failed to authenticate: OAuth session expired", is_error=True)

    with pytest.raises(curate.CurateError):
        curate.check_auth(runner=runner)


def test_check_auth_raises_curate_error_on_malformed_envelope():
    """A non-JSON stdout (a genuinely broken CLI install) must surface as
    CurateError, not a raw json.JSONDecodeError -- the doctor command (a
    later task) calls check_auth and treats CurateError as 'the CLI is
    unhappy'. The malformed text must be visible in the message."""

    def runner(prompt, system, timeout):
        return "not json at all, something crashed"

    with pytest.raises(curate.CurateError) as exc:
        curate.check_auth(runner=runner)
    assert "not json at all, something crashed" in str(exc.value)


# ---------------------------------------------------------------------------
# _run_cli: the real subprocess.run call, uninjected. Every other test in
# this file replaces _run_cli wholesale via runner=, so nothing else ever
# inspects the actual argument list -- if --model or --system-prompt or the
# stdin wiring were dropped, nothing would go red without this test.
# ---------------------------------------------------------------------------


def test_run_cli_builds_the_expected_subprocess_call(monkeypatch):
    captured = {}

    class FakeCompleted:
        stdout = '{"type": "result", "is_error": false, "result": "[]"}'

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    curate._run_cli("the candidate prompt text", "the system rulebook text", 42)

    args = captured["args"]
    kwargs = captured["kwargs"]

    assert args[0] == curate.CLAUDE
    assert "-p" in args

    for flag in curate.CLI_FLAGS:
        assert flag in args, f"missing load-bearing flag {flag!r}"

    # Named explicitly (not just via the CLI_FLAGS loop above) because these
    # are the flags this call takes ~51,000 input tokens down to 339 for --
    # a silent drop of either must fail loudly here.
    assert "--model" in args
    assert "sonnet" in args
    assert "--system-prompt" in args
    system_index = args.index("--system-prompt")
    assert args[system_index + 1] == "the system rulebook text"

    # The prompt must travel over stdin, never as a command-line argument
    # (that is the whole point of the fix -- Windows argv length limits).
    assert "the candidate prompt text" not in args
    assert kwargs.get("input") == "the candidate prompt text"

    assert kwargs.get("timeout") == 42
    assert kwargs.get("capture_output") is True


# ---------------------------------------------------------------------------
# build_prompt / build_system_prompt: previously untested, so a regression
# in either could ship silently.
# ---------------------------------------------------------------------------


def test_build_prompt_includes_every_candidate_and_its_blurb():
    candidates = [
        Candidate(
            "First Good Thing",
            "https://a.com/1",
            "SourceA",
            datetime(2026, 9, 1, tzinfo=timezone.utc),
            "A hopeful blurb about the first thing.",
        ),
        Candidate(
            "Second Good Thing",
            "https://a.com/2",
            "SourceB",
            datetime(2026, 9, 2, tzinfo=timezone.utc),
            "A hopeful blurb about the second thing.",
        ),
    ]

    prompt = curate.build_prompt(candidates, [])

    assert "First Good Thing" in prompt
    assert "A hopeful blurb about the first thing." in prompt
    assert "Second Good Thing" in prompt
    assert "A hopeful blurb about the second thing." in prompt


def test_build_prompt_lists_recent_titles_under_the_do_not_repeat_heading():
    prompt = curate.build_prompt([], ["An Old Story Already Published"])

    assert "do not pick the same event again" in prompt.lower()
    assert "An Old Story Already Published" in prompt
    # the recent title must actually appear after the heading, not before it
    heading_index = prompt.lower().index("do not pick the same event again")
    title_index = prompt.index("An Old Story Already Published")
    assert title_index > heading_index


def test_build_prompt_does_not_crash_on_a_candidate_with_no_published_date():
    """fetch.py logs how many items it sees with no publish date -- they are
    real and reach build_prompt. If the code called .isoformat() on None
    unconditionally this would raise AttributeError."""
    undated = Candidate("Undated Story", "https://a.com/3", "SourceC", None, "")

    prompt = curate.build_prompt([undated], [])

    assert "Undated Story" in prompt


def test_build_system_prompt_includes_every_editorial_label():
    labels = [
        "earth", "ocean", "animals", "agriculture", "people", "health",
        "science", "space", "technology", "peace", "government", "world",
    ]
    prompt = curate.build_system_prompt({"labels": labels})

    for label in labels:
        assert label in prompt


def test_build_system_prompt_bans_politics_and_asks_for_three_ranked_candidates():
    prompt = curate.build_system_prompt({"labels": ["earth", "world"]})
    collapsed = " ".join(prompt.split())  # the source text wraps mid-sentence

    assert "Banned without exception: elections, polls, campaigns, candidates" in collapsed
    assert "Return THREE ranked candidates" in collapsed
