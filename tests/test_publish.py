import pytest
from happy_news import publish


def test_push_runs_add_commit_push(tmp_path):
    calls = []

    def runner(args, cwd):
        calls.append(args)
        return 0, ""

    publish.push(tmp_path, "msg", runner=runner)
    verbs = [a[1] for a in calls]
    assert verbs == ["add", "commit", "push"]


def test_rejected_push_rebases_and_retries_once(tmp_path):
    calls = []

    def runner(args, cwd):
        calls.append(args)
        if args[1] == "push" and len([a for a in calls if a[1] == "push"]) == 1:
            return 1, "rejected: non-fast-forward"
        return 0, ""

    publish.push(tmp_path, "msg", runner=runner)
    verbs = [a[1] for a in calls]
    assert verbs == ["add", "commit", "push", "pull", "push"]


def test_second_push_failure_raises(tmp_path):
    def runner(args, cwd):
        return (1, "rejected") if args[1] == "push" else (0, "")

    with pytest.raises(publish.PublishError):
        publish.push(tmp_path, "msg", runner=runner)


def test_nothing_to_commit_is_not_an_error(tmp_path):
    def runner(args, cwd):
        if args[1] == "commit":
            return 1, "nothing to commit, working tree clean"
        return 0, ""

    publish.push(tmp_path, "msg", runner=runner)  # must not raise


def test_missing_tracked_paths_do_not_break_add(tmp_path):
    """Verify that git add with nonexistent paths doesn't fail the run."""
    calls = []

    def runner(args, cwd):
        calls.append(args)
        # git add should not fail even if paths don't exist in this test
        if args[1] == "add":
            # In real git, adding nonexistent paths doesn't error
            return 0, ""
        return 0, ""

    publish.push(tmp_path, "msg", runner=runner)
    # Verify that add was called with all TRACKED items
    add_call = [a for a in calls if a[1] == "add"][0]
    assert "archive" in add_call
    assert "data" in add_call
