"""Slack session keys round-trip: the parser must know the workspace slot the builder emits (#141356).

``build_session_key`` inserts the Slack workspace ``scope_id`` between the chat_type and the chat id
(``agent:main:slack:group:<T…>:<C…>``). The parser assumed ``parts[4]`` was always the chat id, so
every Slack key parsed to a chat id of the WORKSPACE and, for DMs and threads, to a thread slot
shifted by one — which is why async-delegation results never reached the chat that asked for them.
"""

from types import SimpleNamespace

import pytest

from gateway.config import Platform
from gateway.run import GatewayRunner, _parse_session_key
from gateway.session import SessionSource, build_session_key, parse_session_key

WORKSPACE = "T0123ABCD"
CHANNEL = "C0456EFGH"
DM = "D0789IJKL"
THREAD = "1700000000.000100"


def test_group_key_reports_the_channel_not_the_workspace():
    parsed = _parse_session_key(f"agent:main:slack:group:{WORKSPACE}:{CHANNEL}")
    assert parsed == {
        "platform": "slack",
        "chat_type": "group",
        "chat_id": CHANNEL,
        "scope_id": WORKSPACE,
    }


def test_dm_thread_key_shifts_the_thread_slot_too():
    parsed = _parse_session_key(f"agent:main:slack:dm:{WORKSPACE}:{DM}:{THREAD}")
    assert parsed["chat_id"] == DM
    assert parsed["scope_id"] == WORKSPACE
    assert parsed["thread_id"] == THREAD


def test_thread_chat_type_reports_the_thread_after_the_shifted_chat_id():
    parsed = _parse_session_key(f"agent:main:slack:thread:{WORKSPACE}:{CHANNEL}:{THREAD}")
    assert parsed["chat_id"] == CHANNEL
    assert parsed["thread_id"] == THREAD


def test_slack_key_without_a_workspace_slot_keeps_the_old_reading():
    parsed = _parse_session_key(f"agent:main:slack:group:{CHANNEL}")
    assert parsed == {"platform": "slack", "chat_type": "group", "chat_id": CHANNEL}


def test_relay_tenant_id_is_read_as_the_workspace():
    """A relay connector's scope need not look like a Slack workspace id."""
    parsed = _parse_session_key(f"agent:main:slack:group:acme-tenant:{CHANNEL}")
    assert parsed["chat_id"] == CHANNEL
    assert parsed["scope_id"] == "acme-tenant"


def test_non_slack_keys_are_untouched():
    parsed = _parse_session_key(f"agent:work:discord:group:{CHANNEL}:{WORKSPACE}")
    assert parsed == {
        "profile": "work",
        "platform": "discord",
        "chat_type": "group",
        "chat_id": CHANNEL,
    }


@pytest.mark.parametrize(
    "source",
    [
        SessionSource(platform=Platform.SLACK, chat_id=CHANNEL, chat_type="group", scope_id=WORKSPACE),
        SessionSource(platform=Platform.SLACK, chat_id=CHANNEL, chat_type="channel", scope_id=WORKSPACE),
        SessionSource(
            platform=Platform.SLACK, chat_id=DM, chat_type="dm", scope_id=WORKSPACE, thread_id=THREAD,
        ),
        SessionSource(platform=Platform.SLACK, chat_id=CHANNEL, chat_type="group", scope_id=WORKSPACE,
                      user_id="U0123ABCD"),
        SessionSource(platform=Platform.SLACK, chat_id=CHANNEL, chat_type="group"),
        SessionSource(platform=Platform.SLACK, chat_id=DM, chat_type="dm", thread_id=THREAD),
        SessionSource(platform=Platform.TELEGRAM, chat_id="123", chat_type="dm", thread_id="42"),
    ],
)
def test_parse_is_the_inverse_of_build(source):
    key = build_session_key(source)
    parsed = parse_session_key(key)
    assert parsed["platform"] == source.platform.value
    assert parsed["chat_id"] == source.chat_id
    if source.scope_id:
        assert parsed["scope_id"] == source.scope_id
    else:
        assert "scope_id" not in parsed
    if source.chat_type in {"dm", "thread"}:
        assert parsed.get("thread_id") == source.thread_id


def test_async_delegation_routing_carries_the_channel_and_the_workspace():
    evt = {"session_key": f"agent:main:slack:group:{WORKSPACE}:{CHANNEL}"}
    GatewayRunner._enrich_async_delegation_routing(SimpleNamespace(), evt)
    assert evt["platform"] == "slack"
    assert evt["chat_type"] == "group"
    assert evt["chat_id"] == CHANNEL
    assert evt["scope_id"] == WORKSPACE
