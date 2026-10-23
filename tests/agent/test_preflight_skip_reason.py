"""An over-threshold request the pre-API gate skips says why, once per reason.

The gate is one five-term condition, so before this the log could not tell a defer
from a cooldown from a gate that never ran: a long desktop session crossed its
threshold 164 times with no attempt line and no reason (#143521). These tests drive
``run_preflight_compression`` with the real verdict and a double agent, and read the
log back.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from agent.turn_preflight import PreflightGateVerdict, run_preflight_compression

LOGGER = "agent.conversation_loop"


def _messages() -> list:
    return [
        {"role": "user", "content": "x" * 8_000},
        {"role": "assistant", "content": "y" * 8_000},
        {"role": "user", "content": "current ask"},
    ]


def _agent(compressor_should_compress=True) -> SimpleNamespace:
    def _noop_compress(messages, _system, **_kwargs):
        return list(messages), "sys"

    compressor = SimpleNamespace(
        threshold_tokens=152_064,
        context_length=202_752,
        should_compress=lambda _tokens: compressor_should_compress,
        get_active_compression_failure_cooldown=lambda: None,
    )
    return SimpleNamespace(
        context_compressor=compressor,
        compression_enabled=True,
        model="claude-opus-5-5",
        session_id="s1",
        _api_call_count=1,
        iteration_budget=SimpleNamespace(refund=lambda: None),
        _emit_status=lambda _msg: None,
        _compress_context=_noop_compress,
        _persist_session=lambda *_a, **_k: None,
    )


def _drive(agent, *, tokens=400_000, attempts=0, max_attempts=3, defer=lambda _t: False,
           blocked=False):
    verdict = PreflightGateVerdict(
        action="fallthrough", pending_moa_prepared_request=None, messages=_messages(),
        active_system_prompt="sys", conversation_history=None, api_call_count=1,
        compression_attempts=attempts, final_response=None, failed=False,
        _turn_exit_reason=None, _compression_timeout_exhausted=False,
        _preflight_compression_blocked=blocked,
        _provider_overflow_recovery_pending=False, _last_preflight_pressure=0,
    )
    run_preflight_compression(
        agent, verdict, compressor=agent.context_compressor,
        request_pressure_tokens=tokens, provider_overflow_preflight=False,
        defer_preflight=defer, moa_prepared_request=None, system_message="sys",
        user_message="current ask", max_compression_attempts=max_attempts,
        effective_task_id="task",
    )
    return verdict


def _skip_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "skipped:" in r.getMessage()]


def test_a_defer_over_threshold_names_itself(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)

    _drive(_agent(), defer=lambda _t: True)

    lines = _skip_lines(caplog)
    assert len(lines) == 1
    assert "deferred_to_real_usage" in lines[0]
    assert "400,000" in lines[0] and "152,064" in lines[0]


def test_the_same_reason_is_logged_once(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    agent = _agent()

    for _ in range(5):
        _drive(agent, defer=lambda _t: True)

    assert len(_skip_lines(caplog)) == 1


def test_a_changed_reason_is_a_new_line(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    agent = _agent()

    _drive(agent, defer=lambda _t: True)
    agent._review_defer_compaction_before_first_response = True
    agent._turn_received_provider_response = False
    _drive(agent, defer=lambda _t: False)

    lines = _skip_lines(caplog)
    assert [line.split("skipped: ")[1].split(" (")[0] for line in lines] == [
        "deferred_to_real_usage",
        "review_fork_first_request_pending",
    ]


def test_below_threshold_stays_silent(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)

    _drive(_agent(), tokens=150_000, defer=lambda _t: True)

    assert _skip_lines(caplog) == []


def test_an_exhausted_attempt_budget_names_the_count(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)

    _drive(_agent(), attempts=3, max_attempts=3)

    lines = _skip_lines(caplog)
    assert len(lines) == 1
    assert "attempts_exhausted:3/3" in lines[0]


def test_a_disabled_compressor_and_a_lone_message_are_named(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    agent = _agent()
    agent.compression_enabled = False
    _drive(agent, tokens=300_000)
    assert "compression_disabled" in _skip_lines(caplog)[0]

    caplog.clear()
    lone = _agent()
    verdict_messages = [{"role": "user", "content": "only"}]
    verdict = PreflightGateVerdict(
        action="fallthrough", pending_moa_prepared_request=None, messages=verdict_messages,
        active_system_prompt="sys", conversation_history=None, api_call_count=1,
        compression_attempts=0, final_response=None, failed=False, _turn_exit_reason=None,
        _compression_timeout_exhausted=False, _preflight_compression_blocked=False,
        _provider_overflow_recovery_pending=False, _last_preflight_pressure=0,
    )
    run_preflight_compression(
        lone, verdict, compressor=lone.context_compressor, request_pressure_tokens=300_000,
        provider_overflow_preflight=False, defer_preflight=lambda _t: False,
        moa_prepared_request=None, system_message="sys", user_message="only",
        max_compression_attempts=3, effective_task_id="task",
    )
    assert "single_message" in _skip_lines(caplog)[0]


def test_a_real_compression_pass_clears_the_dedup(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    agent = _agent()
    agent._preflight_skip_logged = "deferred_to_real_usage"

    _drive(agent)  # every gate open: the pass runs and clears the marker

    assert agent._preflight_skip_logged is None
    assert _skip_lines(caplog) == []


@pytest.mark.parametrize("tokens", [152_064, 152_065, 467_454])
def test_threshold_is_inclusive_at_and_above(tokens, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)

    _drive(_agent(), tokens=tokens, defer=lambda _t: True)

    assert len(_skip_lines(caplog)) == 1
