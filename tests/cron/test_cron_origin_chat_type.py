"""A cron origin carries the source chat's type, so a DM thread seeds the DM key.

Bug report #141429: ``tools/cronjob_job_args.py::_origin_from_env`` captured platform,
chat_id, chat_name, thread_id, user_id and scope_id but not ``chat_type``, so
``cron/scheduler_delivery.py`` decided the seed's chat type from
``str(chat_id).startswith("D")`` — Slack's DM id convention. Matrix room ids start with
``!``, so a continuable cron thread opened on a Matrix DM was seeded ``group``
(``_THREAD_REPLY_CHAT_TYPE["matrix"]``) while the user's in-thread reply resolves under
``dm``. Two session rows for one thread: the brief is mirrored into the ``group`` row and
the reply starts with an empty transcript ("continuation amnesia").

The same capture fixes the second surface of the report: a Telegram private chat is a DM
whose id is a positive integer, so the ``D...`` fallback never fires there either and a
wake/seed built from the origin landed in ``telegram:group:<id>`` while the user's real
conversation is ``telegram:dm:<id>``.

Contract under test: the KEY of the seeded session equals the KEY the reply builds.
"""

from typing import Optional
from unittest.mock import MagicMock, patch

import cron.scheduler_delivery as sd
from cron.scheduler_delivery import _seed_cron_channel_session, _seed_cron_thread_session
from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.session import SessionSource, build_session_key

MATRIX_DM_ROOM = "!K3Nym:matrix.example.org"
MATRIX_THREAD = "$hgMh"
# Bot API id conventions: private chats are positive, groups/supergroups negative.
TELEGRAM_DM_CHAT = "120334455"
TELEGRAM_GROUP_CHAT = "-1001987654321"
TELEGRAM_USER = "778899"


def _session_env(env: dict):
    """Patch gateway.session_context.get_session_env with a dict lookup."""
    return patch(
        "gateway.session_context.get_session_env",
        side_effect=lambda name, default="": env.get(name, default),
    )


def _origin(**extra):
    return {"platform": "matrix", "chat_id": MATRIX_DM_ROOM, "thread_id": MATRIX_THREAD, **extra}


def _target(origin, platform: str = "matrix", chat_id: str = MATRIX_DM_ROOM,
            thread_id: Optional[str] = MATRIX_THREAD):
    config = GatewayConfig()
    config.platforms[Platform(platform)] = PlatformConfig(enabled=True)
    deliver: dict = {"platform": platform, "chat_id": chat_id}
    if thread_id:
        deliver["thread_id"] = thread_id
    t = sd._prepare_target_delivery(
        {"id": "job-1", "origin": origin},
        deliver,
        adapters={}, loop=None, config=config, notify_delivery=False,
        mirror_enabled=False, mirror_text="", delivery_errors=[])
    assert t is not None
    return t


def test_origin_stamps_the_session_chat_type():
    env = {
        "HERMES_SESSION_PLATFORM": "matrix",
        "HERMES_SESSION_CHAT_ID": MATRIX_DM_ROOM,
        "HERMES_SESSION_CHAT_TYPE": "dm",
    }
    with _session_env(env):
        from tools.cronjob_job_args import _origin_from_env

        origin = _origin_from_env()
    assert origin is not None
    assert origin["chat_type"] == "dm"


def test_origin_without_a_chat_type_stays_none():
    """Legacy/synthetic sessions: no chat_type in the origin, not an empty string."""
    env = {"HERMES_SESSION_PLATFORM": "matrix", "HERMES_SESSION_CHAT_ID": MATRIX_DM_ROOM}
    with _session_env(env):
        from tools.cronjob_job_args import _origin_from_env

        origin = _origin_from_env()
    assert origin is not None
    assert origin["chat_type"] is None


def test_matrix_dm_origin_seeds_the_key_its_reply_resolves_to():
    env = {
        "HERMES_SESSION_PLATFORM": "matrix",
        "HERMES_SESSION_CHAT_ID": MATRIX_DM_ROOM,
        "HERMES_SESSION_CHAT_TYPE": "dm",
        "HERMES_SESSION_THREAD_ID": MATRIX_THREAD,
        "HERMES_SESSION_USER_ID": "@alice:matrix.example.org",
    }
    with _session_env(env):
        from tools.cronjob_job_args import _origin_from_env

        origin = _origin_from_env()
    assert origin is not None
    t = _target(origin)
    assert t.is_dm_target, (
        "a Matrix DM origin must not fall back to the Slack 'D...' id convention — "
        "room ids start with '!' and the seed would land in a row no reply resolves to"
    )

    store = MagicMock()
    adapter = MagicMock()
    adapter._session_store = store
    with patch("gateway.mirror.mirror_to_session", return_value=True):
        _seed_cron_thread_session(
            {"id": "job-1", "name": "digest"}, adapter, "matrix",
            MATRIX_DM_ROOM, MATRIX_THREAD, "Three bullets",
            chat_name=None, is_dm=t.is_dm_target,
        )

    reply_source = SessionSource(
        platform=Platform.MATRIX,
        chat_id=MATRIX_DM_ROOM,
        chat_type="dm",
        user_id="@alice:matrix.example.org",
        thread_id=MATRIX_THREAD,
    )
    store.get_or_create_session.assert_called_once()
    seeded = store.get_or_create_session.call_args[0][0]
    assert build_session_key(seeded) == build_session_key(reply_source), (
        "seeded key diverges from the DM reply's key — the brief lands in a row no reply "
        "ever resolves to (continuation amnesia)"
    )


def test_origin_without_chat_type_keeps_the_legacy_slack_heuristic():
    """Jobs stamped before the fix keep the old behaviour: not a DM, seed untouched."""
    for platform_name, chat_id in (
        ("matrix", MATRIX_DM_ROOM),
        ("telegram", TELEGRAM_DM_CHAT),
    ):
        t = _target({"platform": platform_name, "chat_id": chat_id}, platform=platform_name,
                    chat_id=chat_id, thread_id=None)
        assert not t.is_dm_target


def _telegram_env(chat_type: str, chat_id: str = TELEGRAM_DM_CHAT) -> dict:
    return {
        "HERMES_SESSION_PLATFORM": "telegram",
        "HERMES_SESSION_CHAT_ID": chat_id,
        "HERMES_SESSION_CHAT_TYPE": chat_type,
        "HERMES_SESSION_USER_ID": TELEGRAM_USER,
    }


def test_telegram_dm_origin_seeds_the_key_its_reply_resolves_to():
    """Second surface: a Telegram private chat is a DM with a positive id, not a `D...` one.

    With the origin's type missing, the seed typed the wake as a group and opened a second
    session (`telegram:group:<id>`) beside the user's real conversation (`telegram:dm:<id>`).
    """
    with _session_env(_telegram_env("dm")):
        from tools.cronjob_job_args import _origin_from_env

        origin = _origin_from_env()
    assert origin is not None
    assert origin["chat_type"] == "dm"
    t = _target(origin, platform="telegram", chat_id=TELEGRAM_DM_CHAT, thread_id=None)
    assert t.is_dm_target, (
        "a Telegram private chat id is positive, so the Slack 'D...' fallback can never "
        "fire; without the captured chat_type the seed opens a group session"
    )

    store = MagicMock()
    adapter = MagicMock()
    adapter._session_store = store
    with patch("gateway.mirror.mirror_to_session", return_value=True):
        _seed_cron_channel_session(
            {"id": "job-1", "name": "watchdog"}, adapter, "telegram", TELEGRAM_DM_CHAT,
            "[Wake: cron job \"watchdog\"]", is_dm=t.is_dm_target,
            user_id=origin.get("user_id"),
        )

    reply_source = SessionSource(
        platform=Platform.TELEGRAM, chat_id=TELEGRAM_DM_CHAT,
        chat_type="dm", user_id=TELEGRAM_USER,
    )
    store.get_or_create_session.assert_called_once()
    seeded = store.get_or_create_session.call_args[0][0]
    seeded_key = build_session_key(seeded)
    assert seeded_key == build_session_key(reply_source), (
        "the wake seeded a row the user's DM conversation never resolves to — two agents "
        "act on the same delivery (the second-session symptom of #141429)"
    )
    assert ":group:" not in seeded_key


def test_telegram_group_origin_keeps_the_group_key():
    """The other direction: the fix must not turn a Telegram group into a DM."""
    with _session_env(_telegram_env("group", TELEGRAM_GROUP_CHAT)):
        from tools.cronjob_job_args import _origin_from_env

        origin = _origin_from_env()
    assert origin is not None
    assert origin["chat_type"] == "group"
    t = _target(origin, platform="telegram", chat_id=TELEGRAM_GROUP_CHAT, thread_id=None)
    assert not t.is_dm_target

    store = MagicMock()
    adapter = MagicMock()
    adapter._session_store = store
    with patch("gateway.mirror.mirror_to_session", return_value=True):
        _seed_cron_channel_session(
            {"id": "job-1", "name": "watchdog"}, adapter, "telegram", TELEGRAM_GROUP_CHAT,
            "[Wake: cron job \"watchdog\"]", is_dm=t.is_dm_target,
            user_id=origin.get("user_id"),
        )

    reply_source = SessionSource(
        platform=Platform.TELEGRAM, chat_id=TELEGRAM_GROUP_CHAT,
        chat_type="group", user_id=TELEGRAM_USER,
    )
    store.get_or_create_session.assert_called_once()
    seeded = store.get_or_create_session.call_args[0][0]
    assert build_session_key(seeded) == build_session_key(reply_source)
