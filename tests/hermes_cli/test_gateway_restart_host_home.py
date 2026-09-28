"""The Windows host-gateway relaunch must keep the scrubbed host home.

The detached watcher is already started with the default-root env. On Windows
the respawn overlay is merged last, and it used to stamp the updater process's
own HERMES_HOME over that scrub — so a named profile's update relaunched the
host gateway inside the named profile and the multiplexer refused it (#126470).
"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock

import hermes_cli.gateway as gateway

_PROFILE_HOME = "C:/Users/me/AppData/Local/hermes/profiles/work"
_OVERLAY_RE = re.compile(r"_respawn_env_overlay = (\{.*\})")


def _embedded_overlay(argv: list[str]) -> dict:
    script = argv[2]
    match = _OVERLAY_RE.search(script)
    assert match, "watcher script did not embed the respawn overlay"
    return json.loads(match.group(1))


def _spawn(monkeypatch, *, host: bool) -> dict:
    captured: dict = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = list(argv)
        return MagicMock()

    monkeypatch.setattr(gateway.sys, "platform", "win32")
    monkeypatch.setattr(gateway.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        gateway, "_host_gateway_watcher_env", lambda: {"HERMES_HOME": "C:/hermes-root"},
    )
    monkeypatch.setattr(
        "hermes_cli.gateway_windows.windowless_gateway_restart_spec",
        lambda argv: (
            list(argv),
            "C:/hermes",
            {
                "HERMES_HOME": _PROFILE_HOME,
                "VIRTUAL_ENV": "C:/hermes/venv",
                "PYTHONPATH": "C:/hermes",
            },
        ),
    )
    argv = [
        "C:/hermes/venv/Scripts/python.exe",
        "-m",
        "hermes_cli.main",
        "gateway",
        "run",
    ]
    assert gateway._spawn_gateway_restart_watcher(123, argv, host=host)
    return _embedded_overlay(captured["argv"])


def test_host_restart_overlay_does_not_replace_scrubbed_home(monkeypatch):
    overlay = _spawn(monkeypatch, host=True)

    assert "HERMES_HOME" not in overlay
    assert overlay["VIRTUAL_ENV"] == "C:/hermes/venv"
    assert overlay["PYTHONPATH"] == "C:/hermes"


def test_named_profile_restart_overlay_keeps_its_home(monkeypatch):
    overlay = _spawn(monkeypatch, host=False)

    assert overlay["HERMES_HOME"] == _PROFILE_HOME
    assert overlay["VIRTUAL_ENV"] == "C:/hermes/venv"
