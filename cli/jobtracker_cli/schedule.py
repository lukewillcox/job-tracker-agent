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

from jobtracker_cli.config import CONFIG_DIR, INSTANCE

_SFX = f".{INSTANCE}" if INSTANCE else ""
_LABEL = f"com.lukewillcox.jobtracker{_SFX}"
_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
# A separate agent runs the weekly Prospects search (Requirement 2.1), so its
# cadence is independent of the scan frequency.
_PROSPECTS_LABEL = f"com.lukewillcox.jobtracker{_SFX}.prospects"
_PROSPECTS_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{_PROSPECTS_LABEL}.plist"
_WEEK_SECONDS = 7 * 24 * 3600
# a test instance's scheduled runs must use that instance, not the main one
_ENV: dict[str, object] = (
    {"EnvironmentVariables": {"JOBTRACKER_INSTANCE": INSTANCE}} if INSTANCE else {}
)

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
        "StandardErrorPath": str(CONFIG_DIR / "scan.log"),
        **_ENV,
        "StandardOutPath": str(Path.home() / ".jobtracker" / "scan.log"),
    }
    with _PLIST.open("wb") as f:
        plistlib.dump(plist, f)
    _bootout(_LABEL)
    subprocess.run(["launchctl", "bootstrap", _gui_domain(), str(_PLIST)], check=False)

    # always install a weekly Prospects agent alongside scans
    install_prospects_schedule(exe)
    return True


def install_prospects_schedule(exe: str | None = None) -> bool:
    """Install/replace the weekly Prospects LaunchAgent. Returns True if scheduled."""

    if not is_macos():
        return False
    exe = exe or shutil.which("jobtracker") or "jobtracker"
    _PROSPECTS_PLIST.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": _PROSPECTS_LABEL,
        "ProgramArguments": [exe, "prospects", "--quiet"],
        "StartInterval": _WEEK_SECONDS,
        "RunAtLoad": False,
        "StandardErrorPath": str(CONFIG_DIR / "prospects.log"),
        **_ENV,
        "StandardOutPath": str(Path.home() / ".jobtracker" / "prospects.log"),
    }
    with _PROSPECTS_PLIST.open("wb") as f:
        plistlib.dump(plist, f)
    _bootout(_PROSPECTS_LABEL)
    subprocess.run(["launchctl", "bootstrap", _gui_domain(), str(_PROSPECTS_PLIST)], check=False)
    return True


def remove_schedule() -> None:
    if not is_macos():
        return
    _bootout(_LABEL)
    _bootout(_PROSPECTS_LABEL)
    _PLIST.unlink(missing_ok=True)
    _PROSPECTS_PLIST.unlink(missing_ok=True)


def _gui_domain() -> str:
    import os

    return f"gui/{os.getuid()}"


def _bootout(label: str = _LABEL) -> None:
    subprocess.run(["launchctl", "bootout", f"{_gui_domain()}/{label}"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
