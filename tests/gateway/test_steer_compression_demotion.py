"""Regression tests: the compression-in-flight guard (#56391) must cover the
steer dispatch surfaces that were still unprotected.

``busy_input_mode: steer`` mutates the live transcript mid-run via
``agent.steer()``, which races the pre-rotation parent exactly like the
interrupt the guard already demotes. Two steer sites were unprotected:

  * the PRIORITY fast-path's steer branch (``_handle_message`` running path),
  * ``_resolve_busy_steer_or_redirect`` (the adapter busy-session handler),
    whose compression demotion only fired for ``interrupt``.

The fresh-turn dispatch gap is deliberately NOT covered here: blocking a
fresh turn while compression holds the lock collides with the pre-turn
hygiene contract (see ``test_session_hygiene.py::
test_hygiene_skips_when_compression_already_in_flight``) and would need a
guaranteed drain of the queued follow-up, which only exists behind a live
turn.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.event import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(text=text, source=_make_source(), message_id="m1")


def _make_runner(*, compression_in_flight: bool):
    """Minimal GatewayRunner harness.

    Mirrors tests/gateway/test_priority_path_compression_demotion.py's harness
    (proven to drive _handle_message end-to-end with a live running agent),
    extended with the compression-lock plumbing
    _session_has_compression_in_flight reads.
    """
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    adapter._pending_messages = {}
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)

    source = _make_source()
    sk = build_session_key(source)
    session_entry = SessionEntry(
        session_key=sk,
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )
    session_store = MagicMock()
    session_store.get_or_create_session.return_value = session_entry
    session_store.load_transcript.return_value = []
    session_store.has_any_sessions.return_value = True
    session_store.append_to_transcript = MagicMock()
    session_store.rewrite_transcript = MagicMock()
    session_store.update_session = MagicMock()
    runner.session_store = session_store

    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._session_db = None
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._show_reasoning = False
    runner._service_tier = None
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._should_send_voice_reply = lambda *_args, **_kwargs: False
    runner._send_voice_reply = AsyncMock()
    runner._capture_gateway_honcho_if_configured = lambda *args, **kwargs: None
    runner._emit_gateway_run_progress = AsyncMock()
    runner._draining = False
    runner._busy_input_mode = "interrupt"

    runner._agent_has_active_subagents = lambda _agent: False
    runner._session_has_compression_in_flight = AsyncMock(
        return_value=compression_in_flight
    )

    agent_mock = MagicMock()
    agent_mock.get_activity_summary.return_value = {
        "seconds_since_activity": 0.0,
        "last_activity_desc": "api_call",
        "api_call_count": 1,
        "max_iterations": 60,
    }
    return runner, agent_mock, sk


@pytest.mark.asyncio
async def test_priority_steer_demotes_to_queue_when_compression_in_flight():
    """steer mode on the PRIORITY fast-path must demote to queue while
    compression is in flight — a steer mutates the live transcript, racing the
    pre-rotation parent exactly like the interrupt it demotes (#56391)."""
    import time

    runner, agent_mock, sk = _make_runner(compression_in_flight=True)
    runner._busy_input_mode = "steer"
    runner._running_agents[sk] = agent_mock
    runner._running_agents_ts[sk] = time.time() - 120  # past the grace window

    await runner._handle_message(_make_event("next step"))

    agent_mock.steer.assert_not_called()
    queued = runner.adapters[Platform.TELEGRAM]._pending_messages.get(sk)
    assert queued is not None and queued.text == "next step"


@pytest.mark.asyncio
async def test_busy_session_handler_steer_demotes_when_compression_in_flight():
    """``_resolve_busy_steer_or_redirect`` (adapter busy-session handler) must
    demote steer -> queue for compression in flight, same as interrupt."""
    runner, agent_mock, _sk = _make_runner(compression_in_flight=True)
    runner._prepare_busy_steer_text = AsyncMock(return_value="next step")
    runner._fold_into_running_turn = MagicMock()

    outcome = await runner._resolve_busy_steer_or_redirect(
        _make_event("next step"), build_session_key(_make_source()), "steer", agent_mock
    )

    agent_mock.steer.assert_not_called()
    assert outcome.effective_mode == "queue"
    assert outcome.demoted_for_compression is True
