"""A compression continuation the user closed is terminal, not retryable (#137046).

Pinned completion → session A (``end_reason="compression"``) → continuation B, which the user then ended
with ``/new``. ``_resolve_compression_lineage_target`` treated *any* ended continuation as "the rotation
may still be publishing", so every offer classified retry, ``_requeue_uncertain_completion`` offered it
again, and the settlement's defer refunded the attempt: the same completion is offered forever even
though the line it belongs to is gone for good.

A continuation that is only mid-rotation stays retryable; the boundary set is the shared
``_USER_BOUNDARY_END_REASONS``. The delegation result stays queryable either way — this is about the
poll loop, not about delivery into the new conversation.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from types import SimpleNamespace

import pytest

from gateway.run import GatewayRunner

_PINNED = "session-a"
_CONTINUATION = "session-b"


class _FakeSessionDB:
    """Only the reads the ownership resolver makes."""

    def __init__(self, *, rows=None, tips=None):
        self.rows = dict(rows or {})
        self.tips = dict(tips or {})

    async def get_session(self, session_id):
        return self.rows.get(session_id)

    async def get_compression_tip(self, session_id):
        return self.tips.get(session_id)


def _runner(db):
    runner = object.__new__(GatewayRunner)
    runner._session_db = db
    runner._session_source_cache = {}
    runner._completion_delivery_lock = __import__("threading").Lock()
    runner._completion_deliveries_inflight = set()
    runner._completion_deliveries_delivered = OrderedDict()
    return runner


def _ended(end_reason, *, session_id):
    return {"session_id": session_id, "ended_at": "2026-01-01T00:00:00Z", "end_reason": end_reason}


@pytest.mark.parametrize("end_reason", ["session_reset", "user_exit", "session_switch", "new_session"])
def test_closed_continuation_is_terminal(end_reason):
    runner = _runner(_FakeSessionDB(
        rows={_PINNED: _ended("compression", session_id=_PINNED),
              _CONTINUATION: _ended(end_reason, session_id=_CONTINUATION)},
        tips={_PINNED: _CONTINUATION},
    ))
    assert asyncio.run(runner._classify_completion_target(_PINNED, "")) == "terminal"


def test_closed_continuation_stays_terminal_on_every_offer():
    """The reporter's probe classified the same completion retry three times in a row."""
    runner = _runner(_FakeSessionDB(
        rows={_PINNED: _ended("compression", session_id=_PINNED),
              _CONTINUATION: _ended("session_reset", session_id=_CONTINUATION)},
        tips={_PINNED: _CONTINUATION},
    ))
    verdicts = [asyncio.run(runner._classify_completion_target(_PINNED, "")) for _ in range(3)]
    assert verdicts == ["terminal", "terminal", "terminal"]


def test_continuation_mid_rotation_stays_retryable():
    runner = _runner(_FakeSessionDB(
        rows={_PINNED: _ended("compression", session_id=_PINNED),
              _CONTINUATION: _ended("compression", session_id=_CONTINUATION)},
        tips={_PINNED: _CONTINUATION},
    ))
    assert asyncio.run(runner._classify_completion_target(_PINNED, "")) == "retry"


def test_continuation_ended_for_a_non_boundary_reason_stays_retryable():
    runner = _runner(_FakeSessionDB(
        rows={_PINNED: _ended("compression", session_id=_PINNED),
              _CONTINUATION: _ended("idle", session_id=_CONTINUATION)},
        tips={_PINNED: _CONTINUATION},
    ))
    assert asyncio.run(runner._classify_completion_target(_PINNED, "")) == "retry"


def test_missing_continuation_row_stays_retryable():
    runner = _runner(_FakeSessionDB(
        rows={_PINNED: _ended("compression", session_id=_PINNED)},
        tips={_PINNED: _CONTINUATION},
    ))
    assert asyncio.run(runner._classify_completion_target(_PINNED, "")) == "retry"


def test_unpublished_rotation_stays_retryable():
    runner = _runner(_FakeSessionDB(rows={_PINNED: _ended("compression", session_id=_PINNED)}))
    assert asyncio.run(runner._classify_completion_target(_PINNED, "")) == "retry"


def test_live_continuation_still_delivers():
    runner = _runner(_FakeSessionDB(
        rows={_PINNED: _ended("compression", session_id=_PINNED),
              _CONTINUATION: {"session_id": _CONTINUATION}},
        tips={_PINNED: _CONTINUATION},
    ))
    entry = SimpleNamespace(session_id=_CONTINUATION)
    verdict, target = asyncio.run(
        runner._resolve_compression_lineage_target(runner._session_db, entry, _PINNED)
    )
    assert (verdict, target) == ("deliver", _CONTINUATION)
