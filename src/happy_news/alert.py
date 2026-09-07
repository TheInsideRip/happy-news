"""Make failure visible to the operator before it is visible to the reader."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_HISTORY = 200

# Spec section 8: "Two tier-4-or-worse runs in a rolling week is treated as a
# broken system, not bad luck." Tier 4 means the ladder had to reach back 90
# days through real feeds; tier 5 means it fell to the timeless reserve or
# found nothing at all.
TIER_ALARM = 4
ESCALATION_WINDOW_DAYS = 7
ESCALATION_THRESHOLD = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tier_of(entry) -> tuple[int | None, datetime | None]:
    """Read one entry from health.json's `tiers` list.

    Entries used to be bare integers with no timestamp, so nothing could ever
    ask "how many in the last week?" -- which is why the spec's escalation was
    never implemented. Old bare integers are still read (they still say which
    tier), but they carry no date and so can never fall inside a rolling
    window."""
    if isinstance(entry, bool):  # bool is an int subclass; never a tier
        return None, None
    if isinstance(entry, int):
        return entry, None
    if not isinstance(entry, dict):
        return None, None
    tier = entry.get("tier")
    if isinstance(tier, bool) or not isinstance(tier, int):
        return None, None
    try:
        moment = datetime.fromisoformat(str(entry.get("at")))
    except (TypeError, ValueError):
        return tier, None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return tier, moment


class Health:
    def __init__(self, path: Path):
        self.path = Path(path)

    @staticmethod
    def _default() -> dict:
        return {"consecutive_failures": 0, "last_success": None,
                "failures": [], "droughts": [], "tiers": []}

    def _read(self) -> dict:
        if not self.path.exists():
            return self._default()
        try:
            with self.path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # A crash mid-write (or any other on-disk corruption) must
            # degrade to a fresh start, not take down the run.
            return self._default()
        if not isinstance(data, dict):
            return self._default()
        # Ensure all expected keys exist (for backward compatibility with old files)
        for key in ("failures", "droughts", "tiers"):
            if key not in data:
                data[key] = []
        if "consecutive_failures" not in data:
            data["consecutive_failures"] = 0
        if "last_success" not in data:
            data["last_success"] = None
        return data

    def _write(self, data: dict) -> None:
        # Ensure all expected keys exist (for backward compatibility with old files)
        for key in ("failures", "droughts", "tiers"):
            if key not in data:
                data[key] = []
        for key in ("failures", "droughts", "tiers"):
            data[key] = data[key][-MAX_HISTORY:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file in the same directory and rename over the
        # target so a crash mid-write can never leave a truncated
        # health.json behind -- os.replace is atomic on both POSIX and
        # Windows (NTFS) when source and destination share a volume.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.remove(tmp_name)
            except OSError:
                pass
            raise

    def record_success(self) -> None:
        data = self._read()
        data["consecutive_failures"] = 0
        data["last_success"] = _now()
        self._write(data)

    def record_failure(self, reason: str) -> int:
        data = self._read()
        data["consecutive_failures"] += 1
        data["failures"].append({"at": _now(), "reason": reason})
        self._write(data)
        return data["consecutive_failures"]

    def record_drought(self, reason: str) -> None:
        """A drought is not a failure and must not touch the failure counter."""
        data = self._read()
        data["droughts"].append({"at": _now(), "reason": reason})
        self._write(data)

    def record_tier(self, tier: int) -> int:
        """Record the tier a run actually published from, with a timestamp.

        Two things were wrong before. It wrote a bare integer, so the history
        carried no dates and nothing could ever ask the spec's question
        ("two tier-4-or-worse runs in a rolling week"); and it was called
        before the push, so a run that never reached the reader still left a
        tier on the record. Both made the escalation unimplementable.

        Returns how many tier-4-or-worse runs fall inside the rolling week,
        counting this one -- so the caller can escalate at the threshold."""
        data = self._read()
        data["tiers"].append({"at": _now(), "tier": int(tier)})
        self._write(data)
        return self.recent_tier_alarms(history=data["tiers"])

    def recent_tier_alarms(self, *, days: int = ESCALATION_WINDOW_DAYS,
                           threshold: int = TIER_ALARM, history=None) -> int:
        """How many runs at or above `threshold` published within `days`.

        Undated entries (the old bare-integer format) are outside every
        rolling window and never counted -- an escalation must be provable,
        not guessed."""
        entries = self._read()["tiers"] if history is None else history
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = 0
        for entry in entries:
            tier, at = _tier_of(entry)
            if tier is None or at is None:
                continue
            if tier >= threshold and at >= cutoff:
                count += 1
        return count

    def consecutive_failures(self) -> int:
        return self._read()["consecutive_failures"]


def log_failure(log_path: Path, reason: str) -> None:
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()}\t{reason}\n")


def notify(title: str, message: str) -> None:
    """Windows toast. Never raises -- a broken notifier must not break a run."""
    # Escape single quotes in title and message for PowerShell
    safe_title = title.replace("'", "''")
    safe_message = message.replace("'", "''")

    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] > $null; "
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        f"$t.GetElementsByTagName('text').Item(0).AppendChild($t.CreateTextNode('{safe_title}')) > $null; "
        f"$t.GetElementsByTagName('text').Item(1).AppendChild($t.CreateTextNode('{safe_message}')) > $null; "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Stacey Happy News')"
        ".Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, timeout=20)
    except Exception:  # noqa: BLE001 - notification failure must never break a run
        pass
