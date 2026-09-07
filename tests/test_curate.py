import json
import subprocess

import pytest

from happy_news import curate


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
