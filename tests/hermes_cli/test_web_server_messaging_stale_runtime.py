"""A stopped gateway's per-platform verdict is history, not current state.

``gateway_state.json`` preserves platform entries across restarts, so a gateway that once ran
WITHOUT a Telegram token and then stopped leaves ``fatal / No bot token configured`` behind. The
Channels payload must not repeat that after the user saved credentials: with no live gateway the
platform reads ``gateway_stopped`` and carries no error (Desktop Messaging page report).
"""
import json
import os

import pytest


_VALID_BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_1234"


@pytest.fixture
def client(monkeypatch, _isolate_hermes_home):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import hermes_state
    from hermes_constants import get_hermes_home
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    home = get_hermes_home()
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    (home / ".env").write_text(f"TELEGRAM_BOT_TOKEN={_VALID_BOT_TOKEN}\nTELEGRAM_ALLOWED_USERS=42\n", encoding="utf-8")
    (home / "config.yaml").write_text("platforms:\n  telegram:\n    enabled: true\n", encoding="utf-8")
    (home / "gateway_state.json").write_text(json.dumps({
        "kind": "gateway", "pid": 999_999_999, "start_time": 1.0, "gateway_state": "stopped",
        "exit_reason": "shutdown", "updated_at": "2026-01-01T00:00:00+00:00",
        "platforms": {"telegram": {
            "state": "fatal", "error_code": "missing_credentials",
            "error_message": "No bot token configured",
            "writer_pid": 999_999_999, "writer_start_time": 1.0,
        }},
    }), encoding="utf-8")
    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return c


def test_stopped_gateway_does_not_report_stale_platform_error(client):
    payload = client.get("/api/messaging/platforms").json()
    telegram = next(p for p in payload["platforms"] if p["id"] == "telegram")

    assert telegram["configured"] is True
    assert telegram["gateway_running"] is False
    # The saved token is current; the dead gateway's "no token" verdict is not.
    assert telegram["state"] == "gateway_stopped"
    assert telegram["error_code"] is None
    assert telegram["error_message"] is None


def test_operator_stopped_gateway_does_not_report_retained_startup_failure(client):
    """``hermes gateway stop`` keeps the last ``startup_failed`` + ``exit_reason`` on disk with
    ``desired_state: stopped``; the Channels page must read that as stopped, exactly like
    ``/api/status`` does, not wear a "Start failed" badge with the stale reason (#112517)."""
    from hermes_constants import get_hermes_home

    (get_hermes_home() / "gateway_state.json").write_text(json.dumps({
        "kind": "gateway", "pid": 999_999_999, "start_time": 1.0,
        "gateway_state": "startup_failed", "desired_state": "stopped",
        "exit_reason": "Port 8642 already in use", "updated_at": "2026-01-01T00:00:00+00:00",
        "platforms": {},
    }), encoding="utf-8")

    payload = client.get("/api/messaging/platforms").json()
    telegram = next(p for p in payload["platforms"] if p["id"] == "telegram")

    assert telegram["gateway_running"] is False
    assert telegram["state"] == "gateway_stopped"
    assert telegram["error_code"] is None
    assert telegram["error_message"] is None


def _write_host_multiplexer_record(home, *, served_profiles):
    """The host profile's record as a multiplexed gateway writes it: live launch-process PID,
    adapters keyed ``host:telegram``, plus the flat ``telegram`` residue the standalone-era
    gateway left behind (dead writer; never pruned — the live gateway rewrites the snapshot)."""
    host = home / "profiles" / "host"
    host.mkdir(parents=True, exist_ok=True)
    (host / ".env").write_text(
        f"TELEGRAM_BOT_TOKEN={_VALID_BOT_TOKEN}\nTELEGRAM_ALLOWED_USERS=42\n", encoding="utf-8")
    (host / "config.yaml").write_text("platforms:\n  telegram:\n    enabled: true\n", encoding="utf-8")
    record = {
        "kind": "gateway", "pid": os.getpid(), "hermes_home": str(host),
        "gateway_state": "running",
        "platforms": {
            "telegram": {"state": "disconnected", "writer_pid": 999_999_999, "writer_start_time": 1.0,
                          "updated_at": "2026-09-26T00:00:00+00:00"},
            "host:telegram": {"state": "connected", "writer_pid": os.getpid(),
                               "updated_at": "2026-10-11T18:00:00+00:00"},
        },
    }
    if served_profiles is not None:
        record["served_profiles"] = served_profiles
    (host / "gateway_state.json").write_text(json.dumps(record), encoding="utf-8")
    return host


@pytest.fixture
def host_scoped_client(monkeypatch, _isolate_hermes_home):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import hermes_state
    from gateway import status
    from hermes_constants import get_hermes_home
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    host = _write_host_multiplexer_record(get_hermes_home(), served_profiles=["default", "host"])
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", host / "state.db")
    real_cmdline = status._read_process_cmdline
    monkeypatch.setattr(status, "_read_process_cmdline", lambda pid: (
        "python -m hermes_cli.main --profile host gateway run" if pid == os.getpid() else real_cmdline(pid)))
    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return c


def _telegram(payload):
    return next(p for p in payload["platforms"] if p["id"] == "telegram")


def test_multiplex_host_reads_its_rekeyed_platform_not_the_stale_flat_key(host_scoped_client):
    """The launch profile of a multiplexed gateway wins the own-record liveness rung, so its
    adapters must be read re-keyed from ``host:telegram``; the stale flat ``telegram`` entry from
    the standalone era (dead writer, never pruned) must not win the card (#136734)."""
    payload = host_scoped_client.get("/api/messaging/platforms", params={"profile": "host"}).json()
    telegram = _telegram(payload)

    assert telegram["gateway_running"] is True
    assert telegram["state"] == "connected"
    assert telegram["error_message"] is None


def test_standalone_host_profile_still_reads_its_own_flat_keys(monkeypatch, _isolate_hermes_home):
    """A named profile running its own (non-multiplexed) gateway writes flat keys; without the
    multiplexer's ``served_profiles`` stamp the reader must keep the flat read — the re-key
    projection is scoped to records that are actually this profile's multiplexer."""
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import hermes_state
    from gateway import status
    from hermes_constants import get_hermes_home
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    host = _write_host_multiplexer_record(get_hermes_home(), served_profiles=None)
    (host / "gateway_state.json").write_text(json.dumps({
        "kind": "gateway", "pid": os.getpid(), "hermes_home": str(host),
        "gateway_state": "running",
        "platforms": {
            "telegram": {"state": "connected", "writer_pid": os.getpid(),
                          "updated_at": "2026-10-11T18:00:00+00:00"},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", host / "state.db")
    real_cmdline = status._read_process_cmdline
    monkeypatch.setattr(status, "_read_process_cmdline", lambda pid: (
        "python -m hermes_cli.main --profile host gateway run" if pid == os.getpid() else real_cmdline(pid)))
    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    payload = c.get("/api/messaging/platforms", params={"profile": "host"}).json()
    telegram = _telegram(payload)

    assert telegram["gateway_running"] is True
    assert telegram["state"] == "connected"


def test_multiplex_record_serving_other_profiles_does_not_invent_a_rekey(monkeypatch, _isolate_hermes_home):
    """``served_profiles`` without this profile is not a multiplexer for it: the flat key stays the
    only evidence the record holds, so the projection must not run on it."""
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import hermes_state
    from gateway import status
    from hermes_constants import get_hermes_home
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    host = _write_host_multiplexer_record(get_hermes_home(), served_profiles=["default", "coder"])
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", host / "state.db")
    real_cmdline = status._read_process_cmdline
    monkeypatch.setattr(status, "_read_process_cmdline", lambda pid: (
        "python -m hermes_cli.main --profile host gateway run" if pid == os.getpid() else real_cmdline(pid)))
    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    payload = c.get("/api/messaging/platforms", params={"profile": "host"}).json()
    telegram = _telegram(payload)

    # The stale flat entry is the only telegram row in the record; it wins the read.
    assert telegram["state"] == "disconnected"
