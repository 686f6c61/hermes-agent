"""An "Always Approve" clicked in a gateway-routed profile must be saved where that profile reads.

The gate reads ``approvals.*_confirm`` inside the routed turn, which runs under
``set_hermes_home_override(profiles/<name>)``, but the resume handler runs from the adapter's
button/text resolver — another task, with no override set — and ``save_config_value`` writes
``get_hermes_home()/config.yaml``. So every "always" click rewrote the root config that the
profile never reads, the profile kept prompting, and the reply still promised an opt-out. These
tests pin the write to the home the prompt was raised under, for both gates that persist a
preference (destructive slashes and /reload-mcp).
"""

from __future__ import annotations

import sys
import types

import pytest

import gateway.run as gw
from hermes_constants import (
    get_hermes_home,
    get_process_hermes_home,
    reset_hermes_home_override,
    set_hermes_home_override,
)


class _Source:
    platform = "telegram"


class _Event:
    source = _Source()


def _runner(*, config: dict | None = None):
    """Bare object carrying only what _maybe_confirm_destructive_slash touches."""
    obj = types.SimpleNamespace()
    obj._read_user_config = lambda: config if config is not None else {
        "approvals": {"destructive_slash_confirm": True}
    }
    obj._session_key_for_source = lambda source: "sess-1"
    obj._typed_command_prefix_for = lambda platform: "/"
    captured: dict = {}

    async def _request_slash_confirm(*, event, command, title, message, handler):
        captured["handler"] = handler
        return "prompted"

    obj._request_slash_confirm = _request_slash_confirm
    obj._captured = captured
    return obj


@pytest.fixture
def saved_homes(monkeypatch):
    """Stub ``cli.save_config_value`` and record the Hermes home each write lands in."""
    calls: list = []

    module = types.ModuleType("cli")

    def save_config_value(key_path, value):
        calls.append((key_path, value, str(get_hermes_home())))
        return True

    module.save_config_value = save_config_value
    monkeypatch.setitem(sys.modules, "cli", module)
    return calls


async def _gate_destructive(runner):
    async def _execute():
        return "✨ fresh"

    with_scope = set_hermes_home_override(runner._profile_home) if runner._profile_home else None
    try:
        return await gw.GatewayRunner._maybe_confirm_destructive_slash(
            runner,
            event=_Event(),
            command="new",
            title="/new",
            detail="Discards history.",
            execute=_execute,
        )
    finally:
        if with_scope is not None:
            reset_hermes_home_override(with_scope)


@pytest.mark.asyncio
async def test_always_persists_into_the_routed_profile_home(tmp_path, saved_homes):
    profile_home = tmp_path / "profiles" / "brain"
    profile_home.mkdir(parents=True)
    runner = _runner()
    runner._profile_home = profile_home

    # The prompt is raised inside the routed turn's scope; that scope is gone by the time the
    # adapter resolves the button.
    out = await _gate_destructive(runner)
    assert out == "prompted"
    resolved = await runner._captured["handler"]("always")

    assert saved_homes == [("approvals.destructive_slash_confirm", False, str(profile_home))]
    assert "✨ fresh" in resolved
    assert "will run without confirmation" in resolved


@pytest.mark.asyncio
async def test_always_without_a_profile_override_keeps_the_process_home(saved_homes):
    runner = _runner()
    runner._profile_home = None

    await _gate_destructive(runner)
    await runner._captured["handler"]("always")

    assert saved_homes == [
        ("approvals.destructive_slash_confirm", False, str(get_process_hermes_home()))
    ]


@pytest.mark.asyncio
async def test_reload_mcp_always_persists_into_the_routed_profile_home(tmp_path, saved_homes):
    from gateway.slash_commands import GatewaySlashCommandsMixin

    profile_home = tmp_path / "profiles" / "brain"
    profile_home.mkdir(parents=True)

    runner = types.SimpleNamespace()
    runner._read_user_config = lambda: {"approvals": {}}
    runner._session_key_for_source = lambda source: "sess-1"
    captured: dict = {}
    reloaded: list = []

    async def _request_slash_confirm(*, event, command, title, message, handler):
        captured["handler"] = handler
        return "prompted"

    async def _execute_mcp_reload(event):
        reloaded.append(True)
        return "MCP servers reloaded."

    runner._request_slash_confirm = _request_slash_confirm
    runner._execute_mcp_reload = _execute_mcp_reload

    token = set_hermes_home_override(profile_home)
    try:
        prompt = await GatewaySlashCommandsMixin._handle_reload_mcp_command(runner, _Event())
    finally:
        reset_hermes_home_override(token)
    assert prompt == "prompted"

    resolved = await captured["handler"]("always")

    assert saved_homes == [("approvals.mcp_reload_confirm", False, str(profile_home))]
    assert reloaded == [True]
    assert "MCP servers reloaded." in resolved
