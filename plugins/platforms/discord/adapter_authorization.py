"""Fresh membership checks for owner-held durable native inputs."""
import asyncio


class DiscordAuthorizationMixin:
    async def reauthorize_native_roles(self, source):
        from plugins.platforms.discord.adapter import _read_dm_role_auth_guild
        from discord import HTTPException

        # Unlike ingress caches, recovery reads current transport-scoped policy — through the
        # adapter's own gate resolver, the one `_get_allowed_roles` uses: the scoped env /
        # connect-time snapshot first, then `PlatformConfig.extra`, which carries every spelling of
        # the YAML gate (`platforms.discord.allowed_roles` promoted by `PlatformConfig.from_dict`,
        # an explicit `platforms.discord.extra.allowed_roles`, and the legacy top-level `discord:`
        # block seeded by `_apply_yaml_config`). Reading the raw config here instead resolved only
        # the legacy spelling, so a profile configured under `platforms:` admitted the member at
        # ingress and then dropped the same message with `permission_denied`.
        def policy():
            raw = self._gate_raw('allowed_roles', 'DISCORD_ALLOWED_ROLES')
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
