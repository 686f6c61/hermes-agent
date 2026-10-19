"""Home scoping for ``hermes update``'s fleet restart across filesystem boundaries (#141516).

``HERMES_HOME`` is a pathname: the gateway of an LXC container inherits the host's
``/root/.hermes`` verbatim, so string equality alone called it ours and the restart sweep
could signal another installation's gateway. These tests pin the filesystem identity probe
that the scope verdict now consults, without touching a real ``/proc``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import dashboard_procs
from hermes_cli import update_fleet_scope as scope

HOST_HOME = "/srv/hermes-host/.hermes"
CONTAINER_PID = 424242
HOST_PID = 31337


@pytest.fixture
def homes(monkeypatch):
    """Every PID reads *HOST_HOME*: the shape a container gateway produces."""

    def _home(pid):
        return {CONTAINER_PID: HOST_HOME, HOST_PID: HOST_HOME}.get(pid)

    monkeypatch.setattr(dashboard_procs, "_hermes_home_for_pid", _home)
    return _home


def _identities(monkeypatch, mapping):
    monkeypatch.setattr(scope, "_path_identity", lambda path: mapping.get(str(path)))


def _container_view(monkeypatch, own=(10, 100), theirs=(20, 200), container_readable=True):
    mapping = {HOST_HOME: own, f"/proc/{HOST_PID}/root{HOST_HOME}": own}
    if container_readable:
        mapping[f"/proc/{CONTAINER_PID}/root{HOST_HOME}"] = theirs
    _identities(monkeypatch, mapping)


def test_a_container_gateway_on_a_matching_pathname_is_not_owned(homes, monkeypatch):
    _container_view(monkeypatch)
    assert scope.gateway_pid_in_update_scope(CONTAINER_PID, {Path(HOST_HOME)}) is False


def test_the_host_gateway_resolving_to_the_same_file_is_owned(homes, monkeypatch):
    _container_view(monkeypatch)
    assert scope.gateway_pid_in_update_scope(HOST_PID, {Path(HOST_HOME)}) is True


def test_an_unreadable_proc_root_keeps_the_pathname_verdict(homes, monkeypatch):
    """macOS/Windows have no procfs; a probe that cannot answer must not flip the verdict."""
    _container_view(monkeypatch, container_readable=False)
    assert scope.gateway_pid_in_update_scope(HOST_PID, {Path(HOST_HOME)}) is True
    assert scope.home_path_shared_with_pid(CONTAINER_PID, HOST_HOME) is None


def test_a_home_outside_the_scope_is_foreign_without_a_probe(monkeypatch):
    def _boom(pid):
        return "/srv/other-install/.hermes"

    monkeypatch.setattr(dashboard_procs, "_hermes_home_for_pid", _boom)
    _identities(monkeypatch, {})
    assert scope.gateway_pid_in_update_scope(CONTAINER_PID, {Path(HOST_HOME)}) is False


def test_an_unreadable_home_is_still_unknown(monkeypatch):
    monkeypatch.setattr(dashboard_procs, "_hermes_home_for_pid", lambda pid: None)
    monkeypatch.setattr(scope, "_ledger_gateway_home", lambda pid: None)
    assert scope.gateway_pid_in_update_scope(CONTAINER_PID, {Path(HOST_HOME)}) is None


def test_the_partition_keeps_the_container_pid_and_names_the_reason(homes, monkeypatch):
    _container_view(monkeypatch)
    monkeypatch.setattr(scope, "update_scope_homes", lambda: {Path(HOST_HOME)})
    owned, foreign = scope.partition_gateway_pids_by_scope([HOST_PID, CONTAINER_PID])
    assert owned == [HOST_PID]
    assert foreign == [(CONTAINER_PID, f"{HOST_HOME} (same pathname, different filesystem)")]


def test_a_pid_that_cannot_exist_is_not_probed(monkeypatch):
    _identities(monkeypatch, {})
    assert scope.home_path_shared_with_pid(0, HOST_HOME) is None
