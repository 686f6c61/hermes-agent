"""Regression tests for the standard-mode overlay warning (#134243).

``computer_use.no_overlay: false`` is the documented escape hatch to keep the
agent cursor overlay — the wrapper's own docstrings recommend it for X11 and
macOS. But the ``standard`` permission mode spawns no embedded daemon (only a
bare ``cua-driver mcp`` child), and the overlay is rendered by a daemon's UI
runloop, so there the key is accepted and silently produces nothing. The
backend must say so instead of failing silently. Bounded/unrestricted launch
the daemon, where the setting works; an explicit ``True`` and the unset
auto-detection never claim to keep the cursor, so both stay silent.
"""

import logging

from tools.computer_use import cua_backend


def _cfg(monkeypatch, no_overlay):
    monkeypatch.setattr(
        cua_backend, "_computer_use_cfg", lambda: {"no_overlay": no_overlay}
    )


def test_warns_when_standard_mode_cannot_render_the_overlay(monkeypatch, caplog):
    _cfg(monkeypatch, False)
    with caplog.at_level(logging.WARNING, logger=cua_backend.logger.name):
        cua_backend._warn_overlay_unreachable_in_standard_mode("standard")
    assert any(
        "no_overlay" in r.message and "standard" in r.message
        for r in caplog.records
    )


def test_silent_for_unset_auto_detection(monkeypatch, caplog):
    _cfg(monkeypatch, None)
    with caplog.at_level(logging.WARNING, logger=cua_backend.logger.name):
        cua_backend._warn_overlay_unreachable_in_standard_mode("standard")
    assert not caplog.records


def test_silent_when_overlay_explicitly_hidden(monkeypatch, caplog):
    _cfg(monkeypatch, True)
    with caplog.at_level(logging.WARNING, logger=cua_backend.logger.name):
        cua_backend._warn_overlay_unreachable_in_standard_mode("standard")
    assert not caplog.records


def test_silent_for_daemon_backed_modes(monkeypatch, caplog):
    _cfg(monkeypatch, False)
    with caplog.at_level(logging.WARNING, logger=cua_backend.logger.name):
        cua_backend._warn_overlay_unreachable_in_standard_mode("bounded")
        cua_backend._warn_overlay_unreachable_in_standard_mode("unrestricted")
    assert not caplog.records
