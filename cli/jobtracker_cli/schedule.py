"""macOS launchd schedule for automatic scans.

Writes a LaunchAgent plist that runs `jobtracker scan` on an interval. Mac-only;
on other platforms scheduling is a no-op and the user runs `jobtracker scan`.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

_LABEL = "com.lukewillcox.jobtracker"
_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"

# scan frequency -> seconds between runs
_INTERVALS = {
    "daily": 24 * 3600,
    "every_2_days": 2 * 24 * 3600,
    "weekly": 7 * 24 * 3600,
}


def is_macos() -> bool:
    return sys.platform == "darwin"


def install_schedule(frequency: str) -> bool:
    """Install/replace the LaunchAgent. Returns True if scheduled."""

    if not is_macos() or frequency == "off":
        return False
    interval = _INTERVALS.get(frequency)
    if interval is None:
        return False
    exe = shutil.which("jobtracker") or "jobtracker"
    _PLIST.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": _LABEL,
        "ProgramArguments": [exe, "scan", "--quiet"],
        "StartInterval": interval,
        "RunAtLoad": False,
        "StandardErrorPath": str(Path.home() / ".jobtracker" / "scan.log"),
        "StandardOutPath": str(Path.home() / ".jobtracker" / "scan.log"),
    }
    with _PLIST.open("wb") as f:
        plistlib.dump(plist, f)
    _bootout()
    subprocess.run(["launchctl", "bootstrap", _gui_domain(), str(_PLIST)], check=False)
    return True


def remove_schedule() -> None:
    if not is_macos():
        return
    _bootout()
    _PLIST.unlink(missing_ok=True)


def _gui_domain() -> str:
    import os

    return f"gui/{os.getuid()}"


def _bootout() -> None:
    subprocess.run(["launchctl", "bootout", f"{_gui_domain()}/{_LABEL}"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
