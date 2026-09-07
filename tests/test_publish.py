import shutil
import subprocess

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


# ---------------------------------------------------------------------------
# `git pull --rebase`'s exit code used to be discarded.
#
# A conflicted rebase leaves the repository mid-rebase, and from that moment
# every later commit fails -- so every later run fails -- until someone runs
# `git rebase --abort` by hand. One transient conflict froze the page for
# good, with the only evidence a traceback in run.log.
# ---------------------------------------------------------------------------


def test_a_failed_rebase_is_aborted_and_raises(tmp_path):
    root = _root_with_index(tmp_path)
    calls = []

    def runner(args, cwd):
        calls.append(args)
        if args[1] == "push":
            return 1, "! [rejected] main -> main (fetch first)"
        if args[1] == "pull":
            return 1, ("CONFLICT (content): Merge conflict in index.html\n"
                       "error: could not apply 1a2b3c4... 2026-09-07 morning")
        return 0, ""

    with pytest.raises(publish.PublishError) as exc:
        publish.push(root, "msg", runner=runner)

    assert "abort" in str(exc.value).lower()
    verbs = [a[1] for a in calls]
    assert verbs == ["add", "commit", "push", "pull", "rebase"], verbs
    assert calls[-1] == ["git", "rebase", "--abort"]
    assert verbs.count("push") == 1, "must not push on top of a failed rebase"


def test_a_failed_rebase_abort_is_reported_too(tmp_path):
    root = _root_with_index(tmp_path)

    def runner(args, cwd):
        if args[1] == "push":
            return 1, "rejected"
        if args[1] == "pull":
            return 1, "CONFLICT"
        if args[1] == "rebase":
            return 1, "fatal: No rebase in progress?"
        return 0, ""

    with pytest.raises(publish.PublishError) as exc:
        publish.push(root, "msg", runner=runner)

    assert "abort also failed" in str(exc.value)


def test_a_successful_rebase_still_retries_the_push(tmp_path):
    """The abort path must not fire on a clean rebase."""
    root = _root_with_index(tmp_path)
    calls = []

    def runner(args, cwd):
        calls.append(args)
        if args[1] == "push" and len([a for a in calls if a[1] == "push"]) == 1:
            return 1, "rejected"
        return 0, ""

    publish.push(root, "msg", runner=runner)

    verbs = [a[1] for a in calls]
    assert verbs == ["add", "commit", "push", "pull", "push"]
    assert "rebase" not in verbs


# ---------------------------------------------------------------------------
# The same thing against the real git binary, on real local repositories in
# tmp_path. No network and no real `git push`: add/commit/push are faked, and
# only `pull --rebase` and `rebase --abort` reach real git.
# ---------------------------------------------------------------------------


def _git(args, cwd):
    # stdin=DEVNULL: under pytest's capture the inherited stdin handle can be
    # invalid on Windows (WinError 6), and git must never wait on input here
    # anyway.
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", timeout=60,
                          stdin=subprocess.DEVNULL)


def _init(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], path)
    _git(["config", "user.email", "test@example.invalid"], path)
    _git(["config", "user.name", "Test"], path)
    _git(["config", "commit.gpgsign", "false"], path)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")
def test_a_real_conflicted_rebase_leaves_the_repo_clean_and_committable(tmp_path):
    upstream = tmp_path / "upstream"
    _init(upstream)
    (upstream / "index.html").write_text("original\n", encoding="utf-8")
    _git(["add", "index.html"], upstream)
    _git(["commit", "-m", "base"], upstream)

    work = tmp_path / "work"
    clone = _git(["clone", str(upstream), str(work)], tmp_path)
    assert clone.returncode == 0, clone.stderr
    _git(["config", "user.email", "test@example.invalid"], work)
    _git(["config", "user.name", "Test"], work)
    _git(["config", "commit.gpgsign", "false"], work)

    # diverge on the same line, so `pull --rebase` must conflict
    (upstream / "index.html").write_text("theirs\n", encoding="utf-8")
    _git(["add", "index.html"], upstream)
    _git(["commit", "-m", "theirs"], upstream)

    (work / "index.html").write_text("ours\n", encoding="utf-8")
    _git(["add", "index.html"], work)
    _git(["commit", "-m", "ours"], work)

    def runner(args, cwd):
        # Only the rebase machinery reaches real git; nothing is ever pushed.
        if args[1] in ("pull", "rebase"):
            completed = _git(args[1:], cwd)
            return completed.returncode, (completed.stdout or "") + (completed.stderr or "")
        if args[1] == "push":
            return 1, "! [rejected] main -> main (fetch first)"
        return 0, ""

    with pytest.raises(publish.PublishError):
        publish.push(work, "2026-09-07 morning: something", runner=runner)

    git_dir = work / ".git"
    assert not (git_dir / "rebase-merge").exists(), "repo left mid-rebase"
    assert not (git_dir / "rebase-apply").exists(), "repo left mid-rebase"

    status = _git(["status", "--porcelain=v1"], work)
    assert status.stdout.strip() == "", f"working tree not clean: {status.stdout!r}"

    # The real proof: the next run can still commit. Before the fix the repo
    # stayed mid-rebase and every subsequent commit failed forever.
    (work / "index.html").write_text("next run\n", encoding="utf-8")
    _git(["add", "index.html"], work)
    commit = _git(["commit", "-m", "next run"], work)
    assert commit.returncode == 0, commit.stdout + commit.stderr
