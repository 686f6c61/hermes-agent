"""Fresh membership checks for owner-held durable native inputs."""
import asyncio


def _configured_allowed_roles(config) -> object:
    """The role allowlist as ``PlatformConfig.from_dict`` resolves it for the adapter's gate.

    Every non-typed key of a platform block is promoted into ``extra`` (an explicit
    ``extra:`` value wins on a clash), so ``platforms.discord.allowed_roles`` and
    ``platforms.discord.extra.allowed_roles`` are the same gate the ingress reads. Only
    the pre-``platforms:`` top-level ``discord:`` block is read as the fallback.
    """
    def mapping(value):
        return value if isinstance(value, dict) else {}

    platform = mapping(mapping(config).get('platforms')).get('discord')
    platform = mapping(platform)
    extra = mapping(platform.get('extra'))
    if 'allowed_roles' in extra:
        return extra['allowed_roles']
    if 'allowed_roles' in platform:
        return platform['allowed_roles']
    return mapping(mapping(config).get('discord')).get('allowed_roles', [])


class DiscordAuthorizationMixin:
    async def reauthorize_native_roles(self, source):
        from plugins.platforms.discord.adapter import _read_dm_role_auth_guild, _scoped_gate_env
        from hermes_cli.config import read_raw_config
        from discord import HTTPException

        # Unlike ingress caches, recovery reads current transport-scoped policy.
        def policy():
            raw = (_scoped_gate_env('DISCORD_ALLOWED_ROLES')
                   or _configured_allowed_roles(read_raw_config() or {}))
            roles = {int(str(item).strip()) for item in self._gate_csv_set(raw)
                     if str(item).strip().isdigit()}
            guild_id = _read_dm_role_auth_guild() if source.chat_type == 'dm' else source.scope_id
            return roles, guild_id

        roles, guild_id = policy()
        if not roles or guild_id is None or self._client is None:
            return False
        try:
            guild = self._client.get_guild(int(guild_id))
            uid = int(source.user_id)
        except (TypeError, ValueError):
            return False
        if guild is None:
            return False
        client = self._client
        try:
            member = await asyncio.wait_for(guild.fetch_member(uid), timeout=10)
        except (HTTPException, TimeoutError, OSError):
            return False
        # The entry-time ContextVar contains a secret snapshot. Reload the same
        # transport home after SDK I/O so an intervening .env edit is visible too.
        from gateway.run import _profile_runtime_scope
        from hermes_constants import get_hermes_home
        with _profile_runtime_scope(get_hermes_home()):
            current_policy = policy()
        if self._client is not client or current_policy != (roles, guild_id):
            return False
        return (member.id == uid and member.guild.id == int(guild_id)
                and any(role.id in roles for role in member.roles))
