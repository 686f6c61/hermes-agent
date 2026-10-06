"""Regression tests for the handoff.request seeding of a missing session row.

Split out of ``test_tui_gateway_server.py`` (file-line cap): see issue
#133726 — ``handoff.request`` on a session with no persisted row must seed
the row and queue, not be misreported as "already in flight".
"""

from __future__ import annotations

import contextlib

from gateway.config import GatewayConfig, HomeChannel, Platform, PlatformConfig
from hermes_state import SessionDB
from tui_gateway import methods_session, server


def test_handoff_request_seeds_missing_session_row(monkeypatch, tmp_path):
    """``_ensure_session_db_row`` returns True without writing when no store is
    bound to the context, and ``set_session_title`` is an UPDATE-only CAS — so
    the seeding must live in the handoff path itself."""
    methods_session.register(server)
    db = SessionDB(db_path=tmp_path / "state.db")

    def load_config():
        config = GatewayConfig()
        config.platforms[Platform.DISCORD] = PlatformConfig(
            enabled=True,
            home_channel=HomeChannel(
                platform=Platform.DISCORD,
                chat_id="discord-home",
                name="home",
            ),
        )
        return config

    @contextlib.contextmanager
    def handoff_db(_session):
        yield db

    monkeypatch.setattr("gateway.config.load_gateway_config", load_config)
    monkeypatch.setattr(server, "_ensure_session_db_row", lambda _session: None)
    monkeypatch.setattr(server, "_session_db", handoff_db)
    server._sessions["handoff-fresh"] = {
        "running": False,
        "session_key": "fresh-handoff-session-key",
    }
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "handoff.request",
                "params": {
                    "session_id": "handoff-fresh",
                    "platform": "discord",
                },
            }
        )
        assert "result" in resp, resp
        assert resp["result"]["queued"] is True
        assert db.get_session("fresh-handoff-session-key") is not None
        assert db.get_handoff_state("fresh-handoff-session-key")["state"] == "pending"
    finally:
        server._sessions.pop("handoff-fresh", None)
        db.close()
