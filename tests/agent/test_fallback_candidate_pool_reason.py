"""``_candidate_pool_unusable_reason()`` tells a real cooldown from an unusable pool.

#131993: the fallback skip logged "credential pool is exhausted (every entry in
cooldown)" even when nothing was in cooldown — the pool merely held an
unauthenticated row (a borrowed reference entry without a token). The reason
string now distinguishes the two cases; the skip decision itself is unchanged
(#89401 semantics).
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from agent.chat_completion_helpers import _candidate_pool_unusable_reason
from agent.credential_pool import AUTH_TYPE_OAUTH, CredentialPool, PooledCredential

_MODEL = "claude-opus-5-5"


def _agent_with_pool(entries):
    pool = CredentialPool(
        "anthropic", [PooledCredential.from_dict("anthropic", entry) for entry in entries]
    )
    return SimpleNamespace(_credential_pool=pool)


def test_available_entry_gets_its_chance():
    agent = _agent_with_pool([{"source": "manual", "access_token": "sk-ant-ok"}])
    assert _candidate_pool_unusable_reason(agent, "anthropic", _MODEL) is None


def test_short_throttle_still_gets_its_chance():
    agent = _agent_with_pool([{
        "source": "manual",
        "access_token": "sk-ant-ok",
        "model_cooldowns": {_MODEL: time.time() + 60},
    }])
    assert _candidate_pool_unusable_reason(agent, "anthropic", _MODEL) is None


def test_long_cooldown_reports_cooldown():
    agent = _agent_with_pool([{
        "source": "manual",
        "access_token": "sk-ant-ok",
        "model_cooldowns": {_MODEL: time.time() + 3600},
    }])
    reason = _candidate_pool_unusable_reason(agent, "anthropic", _MODEL)
    assert reason is not None
    assert reason.startswith("every entry in cooldown")


def test_unfilled_borrowed_row_is_not_reported_as_cooldown():
    agent = _agent_with_pool([{
        "source": "claude_code",
        "auth_type": AUTH_TYPE_OAUTH,
        "access_token": "",
    }])
    reason = _candidate_pool_unusable_reason(agent, "anthropic", _MODEL)
    assert reason is not None
    assert reason.startswith("no usable entry")
