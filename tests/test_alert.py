import json
from happy_news.alert import Health, log_failure


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
