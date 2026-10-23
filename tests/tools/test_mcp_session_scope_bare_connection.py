"""An ACP session that attaches editor MCP servers runs its turns inside its own registry tool scope
(``gateway/session_local_mcp._borrowed`` binds ``session_tool_scope``), and ``_mcp_registry_scope``
hands that scope to every MCP lookup. Config-declared servers, though, were registered by a
single-profile process under the bare name, so the session scope resolved ``(scope, name)``, found
nothing there and answered "MCP server '<name>' is not connected" in 0.00 s without ever attempting a
connect (#143502). A bare key is the profile's own connection — ``rekey_unscoped_connections`` moves
every one of them under ``(launch scope, name)`` as soon as the process serves profiles — so a
session-bound scope inside it must reach them, while a connection the scope owns still wins and a
server the scope really lacks still resolves to its own key.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def ledgers(monkeypatch):
    """Clean MCP connection ledgers in a single-profile process (no routed profile served)."""
    from tools.mcp_tool_common import _core

    names = ("_servers", "_server_tool_scopes", "_server_scope_keys", "_lazy_server_configs",
             "_server_connecting", "_server_connect_errors")
    saved = {n: type(getattr(_core, n))(getattr(_core, n)) for n in names}
    for name in names:
        getattr(_core, name).clear()
    monkeypatch.setattr("agent.secret_scope.serves_routed_profile", lambda: False)
    yield _core
    for name in names:
        getattr(_core, name).clear()
        getattr(_core, name).update(saved[name])


def _live():
    return SimpleNamespace(name="github", session=object(), _config={"command": "x"},
                           _tools=[], tool_timeout=30, initialize_result=None,
                           _registered_tool_names=[], _sampling=None)


def test_a_session_tool_scope_reaches_the_bare_config_connection(ledgers):
    from tools.registry import session_tool_scope
    from tools.mcp_tool_discovery import _get_connected_server_for_call
    from tools.mcp_tool_scope import _resolve_server_key

    server = _live()
    ledgers._servers["github"] = server
    with session_tool_scope("sess:abc"):
        assert _resolve_server_key("github") == "github"
        assert _get_connected_server_for_call("github") is server


def test_a_server_the_scope_lacks_still_resolves_to_the_scoped_key(ledgers):
    from tools.registry import session_tool_scope
    from tools.mcp_tool_scope import _resolve_server_key

    with session_tool_scope("sess:abc"):
        assert _resolve_server_key("absent") == ("sess:abc", "absent")


def test_a_connection_the_scope_owns_wins_over_the_bare_one(ledgers):
    from tools.registry import session_tool_scope
    from tools.mcp_tool_scope import _resolve_server_key

    own = _live()
    ledgers._servers[("sess:abc", "github")] = own
    ledgers._servers["github"] = _live()
    with session_tool_scope("sess:abc"):
        assert _resolve_server_key("github") == ("sess:abc", "github")


def test_a_profile_overlay_scope_does_not_reach_the_bare_connection(ledgers):
    """Another profile's overlay scope must not read the process profile's bare connection: that
    would hand it the owner's credentials (#106005). Only a session-bound tool scope may."""
    from tools.mcp_tool_scope import _resolve_server_key

    ledgers._servers["github"] = _live()
    assert _resolve_server_key("github", "profile:b") == ("profile:b", "github")


def test_the_scope_reports_the_config_server_as_connected(ledgers, monkeypatch):
    from tools.registry import session_tool_scope
    from tools import mcp_tool_discovery as discovery

    ledgers._servers["github"] = _live()
    monkeypatch.setattr(discovery, "_enabled_config_names", lambda: {"github"})
    with session_tool_scope("sess:abc"):
        assert discovery.mcp_servers_not_connected() == []
        assert discovery.mcp_servers_ready() == ["github"]
