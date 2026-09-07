"""Commit and push the rendered page. One of only two modules that knows
where this system runs."""
from __future__ import annotations

import subprocess
from pathlib import Path

TRACKED = ["index.html", "archive", "data", "assets"]


class PublishError(RuntimeError):
    pass


def run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run a git subprocess and capture combined stdout/stderr. Public so
    other modules (cli.py's `doctor` command) can run one-off git checks
    without reaching into a private helper."""
    completed = subprocess.run(args, cwd=str(cwd), capture_output=True,
                               text=True, encoding="utf-8", timeout=120)
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


# Backward-compatible private alias -- push() and any other in-module caller
# may keep using the old name.
_run = run_git


def _existing_paths(root: Path, paths: list[str]) -> list[str]:
    """`paths` filtered down to the ones that actually exist under root, in
    the given order.

    Real git fails a literal `git add` outright -- exit 128, nothing staged
    at all, not even paths that do exist -- the moment any one pathspec
    doesn't match a file. So we must never hand git a path we haven't
    confirmed exists.
    """
    return [p for p in paths if (root / p).exists()]


def _existing_tracked(root: Path) -> list[str]:
    return _existing_paths(root, TRACKED)


def push(root: Path, message: str, *, runner=None) -> None:
    run = runner or run_git
    root = Path(root)

    to_stage = _existing_tracked(root)
    if not to_stage:
        raise PublishError(
            "nothing to stage: none of the tracked paths "
            f"({', '.join(TRACKED)}) exist under {root}"
        )

    code, out = run(["git", "add", *to_stage], root)
    if code != 0:
        raise PublishError(f"git add failed: {out.strip()}")

    code, out = run(["git", "commit", "-m", message], root)
    if code != 0 and "nothing to commit" not in out.lower():
        raise PublishError(f"commit failed: {out.strip()}")

    code, out = run(["git", "push"], root)
    if code == 0:
        return

    # `git pull --rebase`'s exit code used to be discarded. A conflicted
    # rebase leaves the repository mid-rebase, and from that moment every
    # later commit fails -- so every later run fails -- until someone runs
    # `git rebase --abort` by hand. One transient conflict froze the page for
    # good. Abort it here so the working tree is left clean and the next
    # scheduled run genuinely retries.
    rebase_code, rebase_out = run(["git", "pull", "--rebase"], root)
    if rebase_code != 0:
        abort_code, abort_out = run(["git", "rebase", "--abort"], root)
        detail = rebase_out.strip()
        if abort_code != 0:
            detail = f"{detail} (rebase --abort also failed: {abort_out.strip()})"
        raise PublishError(f"pull --rebase failed, rebase aborted: {detail}")

    code, out = run(["git", "push"], root)
    if code != 0:
        raise PublishError(f"push failed after rebase: {out.strip()}")


# Only ["data"] -- the never-repeat memory (data/seen.jsonl), the health
# record (data/health.json), and the day's edition (data/editions/<date>.json).
DATA_ONLY = ["data"]


def push_data(root: Path, message: str, *, runner=None) -> None:
    """A second, smaller commit-and-push covering only data/.

    cli.do_run cannot call `memory.remember()` or `health.record_success()`
    until AFTER the main push() above has actually succeeded -- the dedup
    log is permanent and append-only, and recording success before a push
    that might still fail would misreport reality. That ordering means
    seen.jsonl and health.json are always written after push() already made
    its commit, so they are left uncommitted until the *next* run's push
    picks them up: the GitHub copy of the never-repeat memory permanently
    trails the local copy by one run. This second push closes that gap.

    It exists purely as a backup: the local files are authoritative and the
    system only ever reads them locally, so the caller (cli.do_run) treats
    any failure here as a warning, never a run failure. This function is a
    deliberate near-duplicate of push() above rather than sharing its body,
    so that a change here can never alter the first, load-bearing push."""
    run = runner or run_git
    root = Path(root)

    to_stage = _existing_paths(root, DATA_ONLY)
    if not to_stage:
        return  # nothing under data/ yet -- not an error, just nothing to do

    code, out = run(["git", "add", *to_stage], root)
    if code != 0:
        raise PublishError(f"git add failed: {out.strip()}")

    code, out = run(["git", "commit", "-m", message], root)
    if code != 0 and "nothing to commit" not in out.lower():
        raise PublishError(f"commit failed: {out.strip()}")

    code, out = run(["git", "push"], root)
    if code == 0:
        return

    # Same conflicted-rebase handling as push(): a rejected push must not be
    # allowed to leave the repo mid-rebase, or every later commit -- from
    # either push() or push_data() -- fails until someone runs
    # `git rebase --abort` by hand.
    rebase_code, rebase_out = run(["git", "pull", "--rebase"], root)
    if rebase_code != 0:
        abort_code, abort_out = run(["git", "rebase", "--abort"], root)
        detail = rebase_out.strip()
        if abort_code != 0:
            detail = f"{detail} (rebase --abort also failed: {abort_out.strip()})"
        raise PublishError(f"pull --rebase failed, rebase aborted: {detail}")

    code, out = run(["git", "push"], root)
    if code != 0:
        raise PublishError(f"push failed after rebase: {out.strip()}")
