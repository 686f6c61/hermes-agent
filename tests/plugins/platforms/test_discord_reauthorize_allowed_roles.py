"""The durable Discord re-authorization reads the same role gate as the ingress (#139148).

Ingress resolves ``allowed_roles`` through the adapter's ``_gate_raw``, which falls back to
``PlatformConfig.extra`` — and ``PlatformConfig.from_dict`` promotes the flat
``platforms.discord.allowed_roles`` spelling, with an explicit ``extra:`` block winning, into
that same ``extra``. The durable re-authorization read only the scoped env var and the legacy
top-level ``discord:`` block, so a profile configured the documented way was admitted at
ingress and then dropped at re-authorization with ``permission_denied``.
"""

import asyncio
import importlib.util
import sys
from types import ModuleType, SimpleNamespace

import pytest

from gateway.config import Platform, PlatformConfig
from plugins.platforms.discord.adapter import DiscordAdapter

GUILD_ID = 222222
USER_ID = "42"
ROLE_ID = 5555
SOURCE = SimpleNamespace(chat_type="dm", scope_id=str(GUILD_ID), user_id=USER_ID)


@pytest.fixture(autouse=True)
def _discord_http_exception(monkeypatch):
    """The mixin imports the SDK lazily, only to catch ``HTTPException``: stub it when absent."""
    if importlib.util.find_spec("discord") is not None:
        return
    stub = ModuleType("discord")
    stub.HTTPException = type("HTTPException", (Exception,), {})
    monkeypatch.setitem(sys.modules, "discord", stub)


def _read_raw_config(monkeypatch, config):
    """Patch the attribute ``adapter_authorization`` imports at call time."""
    import hermes_cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "read_raw_config", lambda: config, raising=True)


def _adapter():
    """A minimal DiscordAdapter holding the member whose role is ROLE_ID."""
    adapter = object.__new__(DiscordAdapter)
    adapter.platform = Platform.DISCORD
    adapter.config = PlatformConfig(enabled=True, token="x")
    member = SimpleNamespace(id=int(USER_ID), roles=[SimpleNamespace(id=ROLE_ID)])

    async def fetch_member(_uid):
        return member

    guild = SimpleNamespace(id=GUILD_ID, fetch_member=fetch_member)
    member.guild = guild
    adapter._client = SimpleNamespace(get_guild=lambda gid: guild if gid == GUILD_ID else None)
    return adapter


def _policy_config(**platform_discord):
    return {"discord": {"dm_role_auth_guild": GUILD_ID},
            "platforms": {"discord": dict(platform_discord)}}


def test_flat_platform_allowed_roles_authorize_the_recovery(monkeypatch):
    """``platforms.discord.allowed_roles`` (the documented spelling) must pass recovery."""
    _read_raw_config(monkeypatch, _policy_config(allowed_roles=[ROLE_ID]))

    assert asyncio.run(_adapter().reauthorize_native_roles(SOURCE)) is True


def test_explicit_extra_allowed_roles_authorize_the_recovery(monkeypatch):
    """An explicit ``platforms.discord.extra.allowed_roles`` wins, as it does at ingress."""
    _read_raw_config(monkeypatch, _policy_config(allowed_roles=[999],
                                                 extra={"allowed_roles": [ROLE_ID]}))

    assert asyncio.run(_adapter().reauthorize_native_roles(SOURCE)) is True


def test_legacy_top_level_allowed_roles_still_authorize(monkeypatch):
    """The pre-``platforms:`` spelling keeps working."""
    _read_raw_config(monkeypatch, {"discord": {"dm_role_auth_guild": GUILD_ID,
                                               "allowed_roles": [ROLE_ID]}})

    assert asyncio.run(_adapter().reauthorize_native_roles(SOURCE)) is True


def test_a_profile_allowing_another_role_still_refuses(monkeypatch):
    """The gate keeps refusing a member whose role the profile does not allow."""
    _read_raw_config(monkeypatch, _policy_config(allowed_roles=[999]))

    assert asyncio.run(_adapter().reauthorize_native_roles(SOURCE)) is False
