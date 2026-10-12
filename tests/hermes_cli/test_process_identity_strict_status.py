"""The strict ledger check must not call ``psutil.Process.status()`` on Windows (#137045).

``ledger_entries(verified_only=True)`` — reached from ``shared_profile_warning``, which every
``GET /api/status`` runs — asks the strict branch once per ledger entry. ``psutil.Process.status()``
costs ~36 ms per process on Windows, and psutil's Windows implementation returns only STOPPED or
RUNNING, so the zombie comparison the strict branch makes can never come out true there. The
non-strict branch already skips the call on Windows; these tests pin the same behaviour for the strict
one without weakening the checks that do prove liveness.
"""
from __future__ import annotations

import os

import psutil
import pytest

from hermes_cli import process_identity

_PID = 4242
_CREATE_TIME = 1234.0


class RecordingProc:
    """Stands in for ``psutil.Process``: records every ``status()`` call."""

    def __init__(self, *, create_time: float = _CREATE_TIME, running: bool = True,
                 status: str = "running") -> None:
        self.create_time_value = create_time
        self.running = running
        self.status_value = status
        self.status_calls = 0

    def create_time(self) -> float:
        return self.create_time_value

    def is_running(self) -> bool:
        return self.running

    def status(self) -> str:
        self.status_calls += 1
        return self.status_value


@pytest.fixture
def proc(monkeypatch):
    proc = RecordingProc()
    monkeypatch.setattr(psutil, "Process", lambda _pid: proc)
    monkeypatch.setattr(psutil, "STATUS_ZOMBIE", "zombie", raising=False)
    return proc


def test_strict_check_skips_status_on_windows(monkeypatch, proc):
    monkeypatch.setattr(os, "name", "nt")
    assert process_identity._pid_alive_matches(_PID, _CREATE_TIME, strict=True) is True
    assert proc.status_calls == 0


def test_strict_check_skips_status_for_a_reused_pid_on_windows(monkeypatch, proc):
    monkeypatch.setattr(os, "name", "nt")
    assert process_identity._pid_alive_matches(_PID, 9999.0, strict=True) is False
    assert proc.status_calls == 0


def test_strict_check_still_reads_status_off_windows(monkeypatch):
    zombie = RecordingProc(status="zombie")
    monkeypatch.setattr(psutil, "Process", lambda _pid: zombie)
    monkeypatch.setattr(psutil, "STATUS_ZOMBIE", "zombie", raising=False)
    assert os.name != "nt", "this test documents the non-Windows branch"
    assert process_identity._pid_alive_matches(_PID, _CREATE_TIME, strict=True) is False
    assert zombie.status_calls == 1


def test_strict_check_still_rejects_a_stopped_process_off_windows(monkeypatch, proc):
    monkeypatch.setattr(psutil, "Process", lambda _pid: proc)
    monkeypatch.setattr(os, "name", "nt")
    proc.running = False
    assert process_identity._pid_alive_matches(_PID, _CREATE_TIME, strict=True) is False
    assert proc.status_calls == 0


def test_non_strict_check_also_skips_status_on_windows(monkeypatch, proc):
    monkeypatch.setattr(os, "name", "nt")
    assert process_identity._pid_alive_matches(_PID, _CREATE_TIME) is True
    assert proc.status_calls == 0
