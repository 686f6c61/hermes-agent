"""Daemon names for the hybrid local Browser Use sidecar (``tools/browser_use_cli.py``).

``_sidecar_daemon_name`` is the ``BU_NAME`` of the harness daemon that serves the local sidecar. That
daemon reads its CDP endpoint once at spawn and then outlives the call, so two sessions that resolve to
one daemon name end up sharing one browser. Truncating the identity to the 64-character cap collapsed
every pair of long names that share a 57-character prefix onto a single daemon (#137047).
"""
from __future__ import annotations

from tools.browser_use_cli import _SESSION_RE, _sidecar_daemon_name

_MAX_DAEMON_NAME = 64


def test_short_name_keeps_its_verbatim_daemon_name():
    assert _sidecar_daemon_name("shop") == "_local_shop"


def test_empty_name_falls_back_to_default():
    assert _sidecar_daemon_name("") == "_local_default"


def test_name_that_exactly_fills_the_cap_is_not_rewritten():
    name = "a" * 57
    assert _SESSION_RE.fullmatch(name)
    assert _sidecar_daemon_name(name) == f"_local_{name}"
    assert len(_sidecar_daemon_name(name)) == _MAX_DAEMON_NAME


def test_names_sharing_a_truncated_prefix_get_distinct_daemons():
    first, second = "a" * 57 + "x", "a" * 57 + "y"
    assert _SESSION_RE.fullmatch(first) and _SESSION_RE.fullmatch(second)
    assert _sidecar_daemon_name(first) != _sidecar_daemon_name(second)


def test_distinct_long_names_map_to_distinct_daemons():
    names = ["a" * 57 + char for char in "xyz"] + ["b" * 63, "b" * 63 + "c", "b" * 64]
    daemon_names = [_sidecar_daemon_name(name) for name in names]
    assert len(set(daemon_names)) == len(names)


def test_daemon_name_stays_within_the_cap_for_every_valid_session_name():
    names = ["x", "a" * 56, "a" * 57, "a" * 58, "a" * 57 + "x", "z" * 64, "a-b_c" * 12 + "d"]
    for name in names:
        assert _SESSION_RE.fullmatch(name), name
        assert len(_sidecar_daemon_name(name)) <= _MAX_DAEMON_NAME, name
