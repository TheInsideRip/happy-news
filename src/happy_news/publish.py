"""Commit and push the rendered page. One of only two modules that knows
where this system runs."""
from __future__ import annotations

import subprocess
from pathlib import Path

TRACKED = ["index.html", "archive", "data", "assets"]


class PublishError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(args, cwd=str(cwd), capture_output=True,
                               text=True, encoding="utf-8", timeout=120)
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def push(root: Path, message: str, *, runner=None) -> None:
    run = runner or _run
    root = Path(root)

    run(["git", "add", *TRACKED], root)

    code, out = run(["git", "commit", "-m", message], root)
    if code != 0 and "nothing to commit" not in out.lower():
        raise PublishError(f"commit failed: {out.strip()}")

    code, out = run(["git", "push"], root)
    if code == 0:
        return

    run(["git", "pull", "--rebase"], root)
    code, out = run(["git", "push"], root)
    if code != 0:
        raise PublishError(f"push failed after rebase: {out.strip()}")
