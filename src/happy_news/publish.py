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


def _existing_tracked(root: Path) -> list[str]:
    """TRACKED paths that actually exist under root, in TRACKED order.

    Real git fails a literal `git add` outright -- exit 128, nothing staged
    at all, not even paths that do exist -- the moment any one pathspec
    doesn't match a file. So we must never hand git a path we haven't
    confirmed exists.
    """
    return [p for p in TRACKED if (root / p).exists()]


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
