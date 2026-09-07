import json
import subprocess

from happy_news.alert import Health, log_failure, notify


def test_failures_accumulate_then_reset(tmp_path):
    health = Health(tmp_path / "health.json")
    assert health.record_failure("feeds down") == 1
    assert health.record_failure("feeds down") == 2
    health.record_success()
    assert health.consecutive_failures() == 0


def test_drought_is_recorded_separately_from_failure(tmp_path):
    path = tmp_path / "health.json"
    health = Health(path)
    health.record_drought("ladder exhausted")
    assert health.consecutive_failures() == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["droughts"][-1]["reason"] == "ladder exhausted"


def test_tier_history_is_kept(tmp_path):
    path = tmp_path / "health.json"
    health = Health(path)
    health.record_tier(4)
    health.record_tier(1)
    assert json.loads(path.read_text(encoding="utf-8"))["tiers"][-2:] == [4, 1]


def test_log_failure_appends_a_line(tmp_path):
    log = tmp_path / "failures.log"
    log_failure(log, "auth expired")
    log_failure(log, "feeds down")
    assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_reading_old_health_json_with_missing_keys(tmp_path):
    path = tmp_path / "health.json"
    # Simulate an old health.json with only some keys
    path.write_text('{"consecutive_failures": 1, "last_success": null}', encoding="utf-8")
    health = Health(path)
    # This should not raise KeyError when _write tries to access droughts/tiers/failures
    health.record_failure("test reason")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["consecutive_failures"] == 2
    assert "droughts" in data
    assert "tiers" in data
    assert "failures" in data


def test_record_drought_does_not_touch_a_nonzero_failure_streak(tmp_path):
    """A mutant that makes record_drought behave like record_success --
    silently wiping a real failure streak -- must fail this test. Starting
    from zero (as the original test did) can't catch that; it only ever
    sees 0 -> 0."""
    health = Health(tmp_path / "health.json")
    health.record_failure("feeds down")
    health.record_failure("feeds down")
    assert health.consecutive_failures() == 2

    health.record_drought("ladder exhausted")

    assert health.consecutive_failures() == 2


def test_corrupt_health_json_degrades_to_fresh_default(tmp_path):
    """A crash mid-write leaves a truncated file. Reading it must not blow
    up with json.JSONDecodeError -- it must degrade to a fresh default."""
    path = tmp_path / "health.json"
    path.write_text('{"consecutive_failures": 3, "fail', encoding="utf-8")  # truncated

    health = Health(path)

    assert health.consecutive_failures() == 0
    # and the instance must still be usable afterward
    assert health.record_failure("x") == 1


def test_write_is_atomic_and_leaves_no_temp_file_behind(tmp_path):
    """_write must go through a temp-file-then-rename so a crash mid-write
    can never leave a truncated health.json on disk."""
    path = tmp_path / "health.json"
    health = Health(path)

    health.record_success()

    leftover = [p.name for p in tmp_path.iterdir() if p.name != "health.json"]
    assert leftover == [], f"temp files left behind: {leftover}"
    # and the final file is valid, complete JSON
    json.loads(path.read_text(encoding="utf-8"))


def test_notify_never_raises_when_the_subprocess_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("powershell not found")

    monkeypatch.setattr(subprocess, "run", boom)

    notify("Stacey Happy News", "feeds are down")  # must not raise


def test_notify_doubles_single_quotes_for_the_powershell_literal(monkeypatch):
    """The title/message are interpolated into a PowerShell single-quoted
    string literal. A bare `'` would terminate the literal early and
    corrupt (or fail to run) the script, so every `'` must become `''`.
    No real toast may fire -- subprocess.run is monkeypatched out."""
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return None

    monkeypatch.setattr(subprocess, "run", fake_run)

    notify("it's broken", "can't fetch feeds")

    assert "args" in captured, "notify() must still invoke subprocess.run"
    script = captured["args"][-1]
    assert "it''s broken" in script
    assert "can''t fetch feeds" in script
    # the unescaped single-quote form must never appear
    assert "it's broken" not in script
    assert "can't fetch feeds" not in script
