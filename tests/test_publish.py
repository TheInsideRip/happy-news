import pytest
from happy_news import publish


def _root_with_index(tmp_path):
    """A realistic root: index.html always exists by the time push() runs
    (render() writes it earlier in the pipeline). archive/data/assets may
    or may not exist yet."""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    return tmp_path


def test_push_runs_add_commit_push(tmp_path):
    root = _root_with_index(tmp_path)
    calls = []

    def runner(args, cwd):
        calls.append(args)
        return 0, ""

    publish.push(root, "msg", runner=runner)
    verbs = [a[1] for a in calls]
    assert verbs == ["add", "commit", "push"]

    add_call = calls[0]
    assert add_call[2:] == ["index.html"], (
        "only paths that actually exist under root may be passed to git add"
    )


def test_rejected_push_rebases_and_retries_once(tmp_path):
    root = _root_with_index(tmp_path)
    calls = []

    def runner(args, cwd):
        calls.append(args)
        if args[1] == "push" and len([a for a in calls if a[1] == "push"]) == 1:
            return 1, "rejected: non-fast-forward"
        return 0, ""

    publish.push(root, "msg", runner=runner)
    verbs = [a[1] for a in calls]
    assert verbs == ["add", "commit", "push", "pull", "push"]

    push_calls = [a for a in calls if a[1] == "push"]
    pull_calls = [a for a in calls if a[1] == "pull"]
    assert len(push_calls) == 2, "must push exactly twice: once, then once more after rebase"
    assert len(pull_calls) == 1, "must rebase exactly once before retrying"


def test_second_push_failure_raises(tmp_path):
    root = _root_with_index(tmp_path)
    calls = []

    def runner(args, cwd):
        calls.append(args)
        return (1, "rejected") if args[1] == "push" else (0, "")

    with pytest.raises(publish.PublishError):
        publish.push(root, "msg", runner=runner)

    push_calls = [a for a in calls if a[1] == "push"]
    pull_calls = [a for a in calls if a[1] == "pull"]
    assert len(push_calls) == 2, "must not keep retrying push beyond one retry"
    assert len(pull_calls) == 1, "must rebase exactly once, never loop"


def test_nothing_to_commit_is_not_an_error(tmp_path):
    root = _root_with_index(tmp_path)

    def runner(args, cwd):
        if args[1] == "commit":
            return 1, "nothing to commit, working tree clean"
        return 0, ""

    publish.push(root, "msg", runner=runner)  # must not raise


def test_missing_tracked_paths_are_excluded_from_git_add(tmp_path):
    """Real git fails hard on a literal pathspec that doesn't match any
    files, and stages NOTHING AT ALL when that happens -- not even paths
    that do exist. Verified directly against the real git binary:

        $ git add index.html archive data assets   # archive/, data/ absent
        fatal: pathspec 'archive' did not match any files
        exit code: 128
        $ git diff --cached --name-only
        (nothing staged -- not even index.html)

    So push() must filter TRACKED down to paths that exist under root
    *before* ever calling `git add`, rather than relying on git to skip
    missing paths (it does not).
    """
    root = tmp_path
    (root / "index.html").write_text("hello", encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "x.css").write_text("", encoding="utf-8")
    # "archive" and "data" deliberately do not exist.

    calls = []

    def runner(args, cwd):
        calls.append(args)
        return 0, ""

    publish.push(root, "msg", runner=runner)

    add_call = next(a for a in calls if a[1] == "add")
    staged = add_call[2:]
    assert "archive" not in staged
    assert "data" not in staged
    assert "index.html" in staged
    assert "assets" in staged


def test_git_add_failure_raises_publish_error_and_stops_the_run(tmp_path):
    """A non-zero exit from `git add` must never be discarded. It must
    raise before commit/push are attempted, so a staging failure can never
    masquerade as a harmless 'nothing to commit' run."""
    root = _root_with_index(tmp_path)
    calls = []

    def runner(args, cwd):
        calls.append(args)
        if args[1] == "add":
            # faithful reproduction of real git's exit code and message for
            # a bad pathspec (see docstring above)
            return 128, "fatal: pathspec 'archive' did not match any files"
        return 0, ""

    with pytest.raises(publish.PublishError):
        publish.push(root, "msg", runner=runner)

    verbs = [a[1] for a in calls]
    assert verbs == ["add"], "commit/push must never run after a staging failure"


def test_push_raises_when_nothing_exists_to_stage(tmp_path):
    """An empty root (none of TRACKED exists) must be surfaced loudly, not
    silently treated as a successful no-op run."""
    calls = []

    def runner(args, cwd):
        calls.append(args)
        return 0, ""

    with pytest.raises(publish.PublishError):
        publish.push(tmp_path, "msg", runner=runner)

    assert calls == [], "must not shell out to git when there is nothing to stage"
