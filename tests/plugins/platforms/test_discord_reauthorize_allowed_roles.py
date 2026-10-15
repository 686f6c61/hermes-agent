"""The durable Discord re-authorization reads the role gate through the ingress resolver (#139148).

Ingress resolves ``allowed_roles`` through ``DiscordAdapter._gate_raw`` — the scoped env /
connect-time snapshot first, then ``PlatformConfig.extra``. Every YAML spelling of the gate lands
in that ``extra``: ``PlatformConfig.from_dict`` promotes the flat ``platforms.discord.allowed_roles``
key (an explicit ``platforms.discord.extra.allowed_roles`` winning on a clash), and
``_apply_yaml_config`` seeds the legacy top-level ``discord:`` block into it as well. The durable
re-authorization read only the scoped env var and the raw legacy block, so a profile configured
the documented way was admitted at ingress and then dropped at re-authorization with
``permission_denied``.
"""

import asyncio
import importlib.util
import sys
from types import ModuleType, SimpleNamespace

import pytest

from gateway.config import Platform, PlatformConfig
from plugins.platforms.discord.adapter import DiscordAdapter, _GATE_ENV_KEYS

GUILD_ID = 222222
USER_ID = "42"
ROLE_ID = 5555
SOURCE = SimpleNamespace(chat_type="dm", scope_id=str(GUILD_ID), user_id=USER_ID)


@pytest.fixture(autouse=True)
def _discord_http_exception(monkeypatch):
    """The mixin imports the SDK lazily, only to catch ``HTTPException``: stub it when absent."""
    if getattr(sys.modules.get("discord"), "HTTPException", None) is not None:
        return
    try:
        importlib.import_module("discord")
    except ImportError:
        stub = ModuleType("discord")
        stub.HTTPException = type("HTTPException", (Exception,), {})
        monkeypatch.setitem(sys.modules, "discord", stub)


def _read_raw_config(monkeypatch, config):
    """Patch the attribute ``adapter_authorization`` imports at call time."""
    import hermes_cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "read_raw_config", lambda: config, raising=True)


def _adapter(platform_config, gate_env=None):
    """A minimal DiscordAdapter holding the member whose role is ROLE_ID.

    ``gate_env`` fills the connect-time snapshot the adapter's gate resolver reads first, so the
    test never depends on the process environment.
    """
    adapter = object.__new__(DiscordAdapter)
    adapter.platform = Platform.DISCORD
    adapter.config = platform_config
    adapter._gate_env_snapshot = {key: (gate_env or {}).get(key, "") for key in _GATE_ENV_KEYS}
    member = SimpleNamespace(id=int(USER_ID), roles=[SimpleNamespace(id=ROLE_ID)])

    async def fetch_member(_uid):
        return member

    guild = SimpleNamespace(id=GUILD_ID, fetch_member=fetch_member)
    member.guild = guild
    adapter._client = SimpleNamespace(get_guild=lambda gid: guild if gid == GUILD_ID else None)
    return adapter


def _dm_config(**platform_discord):
    """A raw config with the DM role-auth opt-in, as ``_read_dm_role_auth_guild`` reads it."""
    return {"discord": {"dm_role_auth_guild": GUILD_ID},
            "platforms": {"discord": dict(platform_discord)}}


def test_flat_platform_allowed_roles_authorize_the_recovery(monkeypatch):
    """``platforms.discord.allowed_roles`` reaches the gate through ``PlatformConfig.from_dict``."""
    _read_raw_config(monkeypatch, _dm_config(allowed_roles=[ROLE_ID]))
    adapter = _adapter(PlatformConfig.from_dict({"enabled": True, "allowed_roles": [ROLE_ID]}))

    assert asyncio.run(adapter.reauthorize_native_roles(SOURCE)) is True


def test_explicit_extra_allowed_roles_win_like_at_ingress(monkeypatch):
    """An explicit ``platforms.discord.extra.allowed_roles`` wins over the flat key."""
    _read_raw_config(monkeypatch, _dm_config(allowed_roles=[999], extra={"allowed_roles": [ROLE_ID]}))
    adapter = _adapter(PlatformConfig.from_dict(
        {"enabled": True, "allowed_roles": [999], "extra": {"allowed_roles": [ROLE_ID]}}))

    assert asyncio.run(adapter.reauthorize_native_roles(SOURCE)) is True


def test_scoped_env_allowlist_still_wins_over_the_config(monkeypatch):
    """The scoped env is resolved first, as it is at ingress."""
    _read_raw_config(monkeypatch, _dm_config(allowed_roles=[ROLE_ID]))
    adapter = _adapter(PlatformConfig.from_dict({"enabled": True, "allowed_roles": [ROLE_ID]}),
                       gate_env={"DISCORD_ALLOWED_ROLES": "999"})

    assert asyncio.run(adapter.reauthorize_native_roles(SOURCE)) is False


def test_a_profile_allowing_another_role_still_refuses(monkeypatch):
    """The gate keeps refusing a member whose role the profile does not allow."""
    _read_raw_config(monkeypatch, _dm_config(allowed_roles=[999]))
    adapter = _adapter(PlatformConfig.from_dict({"enabled": True, "allowed_roles": [999]}))

    assert asyncio.run(adapter.reauthorize_native_roles(SOURCE)) is False
