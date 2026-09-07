"""The Windows launcher's housekeeping.

publish.bat appended every run's output to logs\\run.log -- 18 runs a day,
forever, with nothing ever trimming it. On the one laptop this system runs
on, a log that eventually fills the disk takes the page down with it.

These tests run rotate_log.bat through the real cmd.exe on temp files. They
touch no network, no `claude` CLI and no git.
"""
import os
import subprocess

import pytest

from happy_news import config

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows launcher only")

ROTATE = config.PACKAGE_ROOT / "rotate_log.bat"


def _rotate(log_path, max_bytes, keep_lines):
    # cmd /s /c "<whole command line>" is the only form that survives two
    # quoted paths (both the script and the log live under paths with spaces
    # here, as they do in the live "E:\Satcey Happy News" install). publish.bat
    # itself uses `call "..." "..."` from inside a batch file, which quotes
    # correctly on its own.
    # Passed as one raw command line, not a list: list2cmdline would escape
    # the inner quotes and cmd would never see them.
    command = f'cmd /s /c ""{ROTATE}" "{log_path}" {max_bytes} {keep_lines}"'
    return subprocess.run(
        command, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )


def _write_lines(path, count, prefix="line"):
    path.write_text("\n".join(f"{prefix} {n}" for n in range(count)) + "\n",
                    encoding="utf-8")
    return path


def test_an_oversized_log_is_trimmed_to_the_most_recent_lines(tmp_path):
    log = _write_lines(tmp_path / "run.log", 5000)
    before = log.stat().st_size

    result = _rotate(log, max_bytes=1000, keep_lines=100)
    assert result.returncode == 0, result.stdout + result.stderr

    lines = [l for l in log.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    assert len(lines) == 100
    # the TAIL is kept -- that is what an operator reads after a failure
    assert lines[-1] == "line 4999"
    assert lines[0] == "line 4900"
    assert log.stat().st_size < before


def test_a_log_under_the_threshold_is_left_untouched(tmp_path):
    log = _write_lines(tmp_path / "run.log", 10)
    before = log.read_bytes()

    result = _rotate(log, max_bytes=1048576, keep_lines=5)
    assert result.returncode == 0, result.stdout + result.stderr

    assert log.read_bytes() == before


def test_a_missing_log_is_a_quiet_no_op(tmp_path):
    missing = tmp_path / "run.log"
    result = _rotate(missing, max_bytes=10, keep_lines=5)
    assert result.returncode == 0
    assert not missing.exists()


def test_a_path_with_spaces_is_handled(tmp_path):
    """The live root is "E:\\Satcey Happy News"."""
    folder = tmp_path / "Satcey Happy News" / "logs"
    folder.mkdir(parents=True)
    log = _write_lines(folder / "run.log", 3000)

    result = _rotate(log, max_bytes=1000, keep_lines=50)
    assert result.returncode == 0, result.stdout + result.stderr

    lines = [l for l in log.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    assert len(lines) == 50
    assert lines[-1] == "line 2999"


def test_publish_bat_rotates_before_it_opens_the_append_redirect(tmp_path):
    """Order matters: the redirect holds an append handle on the file, so the
    rotation has to happen first."""
    text = (config.PACKAGE_ROOT / "publish.bat").read_text(encoding="utf-8")
    assert "rotate_log.bat" in text, "publish.bat must call the rotation"
    assert text.index("rotate_log.bat") < text.index("python -m happy_news run")
