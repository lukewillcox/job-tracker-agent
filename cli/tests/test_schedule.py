"""Tests for the launchd schedule (Task 7): a weekly Prospects agent."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from jobtracker_cli import schedule as sched


@pytest.fixture
def mac(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(sched, "is_macos", lambda: True)
    # redirect the plist paths into tmp and stub launchctl calls
    monkeypatch.setattr(sched, "_PLIST", tmp_path / "scan.plist")
    monkeypatch.setattr(sched, "_PROSPECTS_PLIST", tmp_path / "prospects.plist")
    monkeypatch.setattr(sched.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(sched.shutil, "which", lambda _: "/usr/local/bin/jobtracker")
    return tmp_path


def test_weekly_prospects_agent_installed(mac: Path) -> None:
    assert sched.install_prospects_schedule() is True
    plist = plistlib.loads((mac / "prospects.plist").read_bytes())
    assert plist["Label"] == "com.lukewillcox.jobtracker.prospects"
    assert plist["ProgramArguments"][1:] == ["prospects", "--quiet"]
    assert plist["StartInterval"] == 7 * 24 * 3600


def test_install_schedule_also_installs_prospects(mac: Path) -> None:
    assert sched.install_schedule("daily") is True
    # both agents written
    assert (mac / "scan.plist").exists()
    assert (mac / "prospects.plist").exists()
    scan = plistlib.loads((mac / "scan.plist").read_bytes())
    assert scan["ProgramArguments"][1:] == ["scan", "--quiet"]
    assert scan["StartInterval"] == 24 * 3600


def test_remove_schedule_removes_both(mac: Path) -> None:
    sched.install_schedule("weekly")
    sched.remove_schedule()
    assert not (mac / "scan.plist").exists()
    assert not (mac / "prospects.plist").exists()


def test_non_macos_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sched, "is_macos", lambda: False)
    assert sched.install_prospects_schedule() is False
    assert sched.install_schedule("daily") is False


def test_instance_isolation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import importlib

    import jobtracker_cli.config as config
    import jobtracker_cli.schedule as schedule

    monkeypatch.setenv("JOBTRACKER_INSTANCE", "Test Friend!")
    try:
        importlib.reload(config)
        importlib.reload(schedule)
        assert config.INSTANCE == "testfriend"
        assert config.CONFIG_DIR.name == ".jobtracker-testfriend"
        assert config._KEYRING_SERVICE == "jobtracker-testfriend"
        assert schedule._LABEL == "com.lukewillcox.jobtracker.testfriend"
        assert schedule._ENV == {"EnvironmentVariables": {"JOBTRACKER_INSTANCE": "testfriend"}}
    finally:
        monkeypatch.delenv("JOBTRACKER_INSTANCE")
        importlib.reload(config)
        importlib.reload(schedule)
    assert config.CONFIG_DIR.name == ".jobtracker"
