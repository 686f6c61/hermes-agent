"""win32 dashboard-cleanup stops are a deferred handoff, not a failed respawn (#131864).

The updater's end-of-update cleanup stops a unit-less ``hermes serve``/``hermes dashboard``
and — on POSIX — respawns it from the per-PID argv snapshot taken before the kill. On win32
that snapshot is skipped, so no respawn is ever attempted: every killed backend used to land
in ``failed_respawn_pids``, book the planned serve ``failed``, flip ``restart.incomplete`` and
exit 1, even though code, deps, build, gateway restart and fleet verification all succeeded.

The fix keeps the promise semantics on POSIX (#109290, #126149) and, on win32, reads the
cleanup stop as what it is: the relaunch handed back to the process owner.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from hermes_cli.update_inventory import RuntimeRecord, match_runtime_outcomes, report_unaccounted_runtimes


def _plan(*runtimes):
    plan = types.SimpleNamespace(runtimes=list(runtimes))
    return plan


def _serve(profile: str, pid: int, kind: str = "serve") -> RuntimeRecord:
    return RuntimeRecord(
        kind=kind, profile=profile, pid=pid,
        supervisor="manual-serve", restart_via="respawn-argv",
        detail={"create_time": 1750000000.0, "host": "127.0.0.1", "port": 9119},
    )


def test_failed_respawn_reads_deferred_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    outcomes = match_runtime_outcomes(
        _plan(_serve("default", 900)),
        restarted_services=[], relaunched_profiles=[],
        externally_supervised_profiles=[], killed_pids=set(), failed_units=[],
        stale_serve_pids=set(), failed_respawn_pids={900},
    )
    assert outcomes[0]["outcome"] == "deferred"
    assert report_unaccounted_runtimes(outcomes) is False


def test_failed_respawn_still_reads_failed_off_windows(monkeypatch):
    # POSIX keeps the broken-promise verdict: a respawn was attempted and failed.
    monkeypatch.setattr(sys, "platform", "linux")
    outcomes = match_runtime_outcomes(
        _plan(_serve("default", 900)),
        restarted_services=[], relaunched_profiles=[],
        externally_supervised_profiles=[], killed_pids=set(), failed_units=[],
        stale_serve_pids=set(), failed_respawn_pids={900},
    )
    assert outcomes[0]["outcome"] == "failed"


def _stub_fleet_tail(monkeypatch, stopped_pids):
    from hermes_cli import update_cmd, update_cmd_fleet as fleet
    import hermes_cli.update_receipt as update_receipt

    monkeypatch.setattr(fleet, "_print_legacy_units_warning", lambda: None)
    monkeypatch.setattr(
        "hermes_cli.update_cmd_maint._refresh_dashboard_after_update",
        lambda **kw: set(stopped_pids),
    )
    monkeypatch.setattr(update_cmd, "_surviving_pre_update_serve_runtimes", lambda plan: [])
    monkeypatch.setattr(
        "hermes_cli.gateway_migrate.maybe_auto_migrate_after_update", lambda: None
    )
    monkeypatch.setattr(update_receipt, "collect_fleet_versions", lambda **kw: [])


def _receipt():
    from hermes_cli import update_cmd
    import hermes_cli.update_receipt as update_receipt

    return json.loads(
        (update_cmd.get_hermes_home() / "logs/update_receipts/latest.json").read_text(encoding="utf-8-sig")
    )


@pytest.mark.usefixtures("isolated_source_completion")
def test_win32_cleanup_stop_does_not_fail_the_update(monkeypatch):
    # The reported shape: unit-less serve stopped by the win32 cleanup, no respawn
    # attempted, update must still exit 0 with the serve row handed back ("deferred").
    monkeypatch.setattr(sys, "platform", "win32")
    _stub_fleet_tail(monkeypatch, {21132})
    import hermes_cli.update_receipt as update_receipt
    from hermes_cli import update_cmd_fleet as fleet

    restart = fleet._GatewayRestartOutcome(
        incomplete=False, phase_errors=[], pre_restart_gateway_pids=[], restarted_services=[],
        failed_or_stale_units=[], relaunched_profiles=[], externally_supervised_profiles=[],
        killed_pids=set(),
    )
    plan = _plan(_serve("default", 21132))
    update_receipt.begin_update_receipt()

    fleet._verify_fleet_after_update(
        restart, _pre_update_plan=plan, _windows_gateway_resume=None, update_complete=True
    )

    assert restart.incomplete is False
    receipt = _receipt()
    assert receipt["outcome"] == "success"
    by_pid = {row["pid"]: row["outcome"] for row in receipt["runtime_outcomes"]}
    assert by_pid == {21132: "deferred"}


@pytest.mark.usefixtures("isolated_source_completion")
def test_posix_cleanup_stop_still_fails_the_update(monkeypatch):
    # Off win32 a cleanup-stopped serve is a respawn promise that broke (#109290): the
    # update exits 1 and the receipt stays partial.
    monkeypatch.setattr(sys, "platform", "linux")
    _stub_fleet_tail(monkeypatch, {21132})
    import hermes_cli.update_receipt as update_receipt
    from hermes_cli import update_cmd_fleet as fleet

    restart = fleet._GatewayRestartOutcome(
        incomplete=False, phase_errors=[], pre_restart_gateway_pids=[], restarted_services=[],
        failed_or_stale_units=[], relaunched_profiles=[], externally_supervised_profiles=[],
        killed_pids=set(),
    )
    plan = _plan(_serve("default", 21132))
    update_receipt.begin_update_receipt()

    with pytest.raises(SystemExit) as failure:
        fleet._verify_fleet_after_update(
            restart, _pre_update_plan=plan, _windows_gateway_resume=None, update_complete=True
        )
    assert failure.value.code == 1
    assert restart.incomplete is True
    receipt = _receipt()
    assert receipt["outcome"] == "partial"
    by_pid = {row["pid"]: row["outcome"] for row in receipt["runtime_outcomes"]}
    assert by_pid == {21132: "failed"}
