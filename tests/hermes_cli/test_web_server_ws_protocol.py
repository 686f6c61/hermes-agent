"""The dashboard must not serve WebSockets through uvicorn's legacy ``websockets`` implementation:
on Python 3.14 that adapter's shielded close future reports an unretrieved exception, so every peer
that disappears without a close frame writes an ERROR-level ``asyncio`` record to errors.log, and the
records are indistinguishable from real failures (#141687)."""

import uvicorn.config as uvicorn_config

import hermes_cli.web_server as ws_mod


def test_dashboard_websockets_use_the_sansio_implementation(monkeypatch):
    monkeypatch.setattr(ws_mod.app.state, "auth_required", False, raising=False)
    config, _ = ws_mod._build_uvicorn_server("127.0.0.1", 0)

    # The requested name is not cosmetic: uvicorn resolves it to the sansio protocol class, which has no
    # shielded close task. `Config.load()` (and so `ws_protocol_class`) only runs in Server.run(), so the
    # registry entry is what pins the class here.
    assert config.ws == "websockets-sansio"
    sansio_target = uvicorn_config.WS_PROTOCOLS["websockets-sansio"]
    assert sansio_target is not None and sansio_target.endswith(
        "websockets_sansio_impl:WebSocketsSansIOProtocol")


def test_sansio_choice_keeps_the_ping_policy_and_attachment_ceiling(monkeypatch):
    monkeypatch.setattr(ws_mod.app.state, "auth_required", False, raising=False)

    # Loopback keeps the ping off for the same reason as before (#53773): only a half-open tunnel needs
    # it, and a stalled event loop would otherwise drop a healthy local socket.
    loopback, _ = ws_mod._build_uvicorn_server("127.0.0.1", 0)
    assert loopback.ws == "websockets-sansio"
    assert loopback.ws_ping_interval is None and loopback.ws_ping_timeout is None
    assert loopback.ws_max_size == ws_mod._DESKTOP_ATTACHMENT_WS_MAX_BYTES

    # The sansio implementation honours the same ping knobs, so a non-loopback bind keeps the cadence
    # the tunnel needs instead of silently losing it with the protocol switch.
    public, _ = ws_mod._build_uvicorn_server("0.0.0.0", 0)
    assert public.ws == "websockets-sansio"
    assert public.ws_ping_interval == 20.0 and public.ws_ping_timeout == 20.0


def test_sansio_is_only_requested_when_the_installed_uvicorn_has_it(monkeypatch):
    """The pyproject floor still allows uvicorn 0.31, which has no sansio protocol class; asking for it
    there makes Config construction raise and takes the dashboard down, so the choice degrades to auto."""

    monkeypatch.setattr(ws_mod.app.state, "auth_required", False, raising=False)
    monkeypatch.setattr(uvicorn_config, "WS_PROTOCOLS", {"auto": None, "websockets": "x"}, raising=False)
    config, _ = ws_mod._build_uvicorn_server("127.0.0.1", 0)

    assert config.ws == "auto"
