"""Tests for the Linux dashboard/serve systemd sweep in ``hermes uninstall`` (#141305).

The gateway uninstall only removes the gateway unit name, so a pre-existing
``hermes-dashboard.service`` / ``hermes-serve*.service`` survived the uninstall and a
``Restart=always`` unit kept restarting a ``venv/bin/hermes`` the uninstaller had deleted.

These tests drive ``remove_dashboard_systemd_units`` with the systemd calls and the
ownership resolution stubbed: no real unit is stopped, disabled or unlinked. The removal
of the unit file happens on ``tmp_path``.
"""
from __future__ import annotations

import subprocess as _real_subprocess
import types
from pathlib import Path

import pytest

from hermes_cli import gateway, uninstall

HOME = Path("/home/dev/.hermes")
FOREIGN_HOME = "/home/other/.hermes"


class _Proc:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def _linux(monkeypatch: pytest.MonkeyPatch, *, euid: int = 1000) -> None:
    """The sweep only runs on Linux against this process's home and uid."""
    monkeypatch.setattr(uninstall, "sys", types.SimpleNamespace(platform="linux"))
    monkeypatch.setattr(uninstall, "get_hermes_home", lambda: HOME)
    monkeypatch.setattr(uninstall.os, "geteuid", lambda: euid, raising=False)
    monkeypatch.setattr(
        gateway, "_systemctl_cmd",
        lambda system=False: ["systemctl"] if system else ["systemctl", "--user"])


def _subprocess(monkeypatch: pytest.MonkeyPatch, calls: list, *,
                units: list[str], fragment: Path | None = None) -> None:
    """Record every systemctl argv; answer ``list-units`` and ``show`` like systemd would."""
    def run(cmd, **kwargs):
        calls.append(cmd)
        if "list-units" in cmd:
            return _Proc("".join(f"{unit} loaded active running Hermes\n" for unit in units))
        if "show" in cmd:
            return _Proc("" if fragment is None else f"{fragment}\n")
        return _Proc()

    monkeypatch.setattr(
        uninstall, "subprocess",
        types.SimpleNamespace(run=run, TimeoutExpired=_real_subprocess.TimeoutExpired))


def _homes(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str | None]) -> None:
    from hermes_cli import update_fleet_scope

    monkeypatch.setattr(
        update_fleet_scope, "systemd_unit_hermes_home",
        lambda scope_cmd, unit: mapping.get(unit))


def _verbs(calls: list, unit: str) -> list[str]:
    return [cmd[2] for cmd in calls if cmd[0] == "systemctl" and cmd[1] == "--user" and cmd[2] in
            ("stop", "disable") and cmd[-1] == unit]


def test_owned_dashboard_unit_is_stopped_disabled_and_deleted(monkeypatch, tmp_path):
    unit_file = tmp_path / "hermes-dashboard.service"
    unit_file.write_text("[Service]\nExecStart=/x/venv/bin/hermes dashboard\nRestart=always\n")
    calls: list = []
    _linux(monkeypatch)
    _subprocess(monkeypatch, calls, units=["hermes-dashboard.service"], fragment=unit_file)
    _homes(monkeypatch, {"hermes-dashboard.service": str(HOME)})

    assert uninstall.remove_dashboard_systemd_units() == [unit_file]
    assert _verbs(calls, "hermes-dashboard.service") == ["stop", "disable"]
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert not unit_file.exists()


def test_unit_owned_by_another_home_is_left_alone(monkeypatch, tmp_path):
    unit_file = tmp_path / "hermes-dashboard.service"
    unit_file.write_text("[Service]\nRestart=always\n")
    calls: list = []
    _linux(monkeypatch)
    _subprocess(monkeypatch, calls, units=["hermes-dashboard.service"], fragment=unit_file)
    _homes(monkeypatch, {"hermes-dashboard.service": FOREIGN_HOME})

    assert uninstall.remove_dashboard_systemd_units() == []
    assert not [cmd for cmd in calls if "stop" in cmd or "disable" in cmd]
    assert unit_file.exists()


def test_unreadable_home_is_reported_instead_of_removed(monkeypatch, tmp_path):
    unit_file = tmp_path / "hermes-dashboard.service"
    unit_file.write_text("[Service]\nRestart=always\n")
    calls: list = []
    _linux(monkeypatch)
    _subprocess(monkeypatch, calls, units=["hermes-dashboard.service"], fragment=unit_file)
    _homes(monkeypatch, {"hermes-dashboard.service": None})

    assert uninstall.remove_dashboard_systemd_units() == []
    assert not [cmd for cmd in calls if "stop" in cmd or "disable" in cmd]
    assert unit_file.exists()


def test_gateway_unit_is_not_part_of_this_sweep(monkeypatch, tmp_path):
    """The gateway has its own remover; sweeping it here would run stop/disable twice."""
    calls: list = []
    _linux(monkeypatch)
    _subprocess(monkeypatch, calls, units=["hermes-gateway.service"], fragment=tmp_path / "g.service")
    _homes(monkeypatch, {"hermes-gateway.service": str(HOME)})

    assert uninstall.remove_dashboard_systemd_units() == []


def test_profile_scoped_dashboard_unit_is_swept(monkeypatch, tmp_path):
    unit = "hermes-dashboard-work.service"
    unit_file = tmp_path / unit
    unit_file.write_text("[Service]\nRestart=always\n")
    calls: list = []
    _linux(monkeypatch)
    _subprocess(monkeypatch, calls, units=[unit], fragment=unit_file)
    _homes(monkeypatch, {unit: str(HOME / "profiles" / "work")})

    # HOME is the default root here, so a profile's unit is foreign to it and stays.
    assert uninstall.remove_dashboard_systemd_units() == []
    assert unit_file.exists()


def test_serve_unit_of_this_home_is_swept(monkeypatch, tmp_path):
    unit = "hermes-serve.service"
    unit_file = tmp_path / unit
    unit_file.write_text("[Service]\nRestart=always\n")
    calls: list = []
    _linux(monkeypatch)
    _subprocess(monkeypatch, calls, units=[unit], fragment=unit_file)
    _homes(monkeypatch, {unit: str(HOME)})

    assert uninstall.remove_dashboard_systemd_units() == [unit_file]
    assert not unit_file.exists()


def test_masked_unit_without_fragment_path_is_stopped_but_named(monkeypatch):
    """A masked unit has ``/dev/null`` as its fragment: stop/disable it and report its name."""
    calls: list = []
    _linux(monkeypatch)
    _subprocess(monkeypatch, calls, units=["hermes-dashboard.service"], fragment=None)
    _homes(monkeypatch, {"hermes-dashboard.service": str(HOME)})

    assert uninstall.remove_dashboard_systemd_units() == ["hermes-dashboard.service"]
    assert _verbs(calls, "hermes-dashboard.service") == ["stop", "disable"]


def test_system_scope_is_swept_only_as_root(monkeypatch):
    monkeypatch.setattr(gateway, "_systemctl_cmd",
                        lambda system=False: ["systemctl"] if system else ["systemctl", "--user"])
    monkeypatch.setattr(uninstall.os, "geteuid", lambda: 1000, raising=False)
    assert uninstall._systemd_scope_commands() == [(False, ["systemctl", "--user"])]

    monkeypatch.setattr(uninstall.os, "geteuid", lambda: 0, raising=False)
    assert uninstall._systemd_scope_commands() == [
        (False, ["systemctl", "--user"]), (True, ["systemctl"])]


def test_other_platforms_clean_up_nothing(monkeypatch):
    calls: list = []
    monkeypatch.setattr(uninstall, "sys", types.SimpleNamespace(platform="darwin"))
    _subprocess(monkeypatch, calls, units=["hermes-dashboard.service"])

    assert uninstall.remove_dashboard_systemd_units() == []
    assert calls == []
