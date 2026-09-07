"""Make failure visible to the operator before it is visible to the reader."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

MAX_HISTORY = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Health:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"consecutive_failures": 0, "last_success": None,
                    "failures": [], "droughts": [], "tiers": []}
        with self.path.open(encoding="utf-8") as handle:
            data = json.load(handle)
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
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

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

    def record_tier(self, tier: int) -> None:
        data = self._read()
        data["tiers"].append(tier)
        self._write(data)

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
