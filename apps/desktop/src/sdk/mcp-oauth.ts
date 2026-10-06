import { capabilityScoped } from '@/api/client'
import { completeMcpDesktopOAuth } from '@/lib/mcp-dashboard-oauth'
import { requestGatewayForAgent } from '@/store/gateway'

/** Complete client-local MCP sign-in for a pinned bot profile, optionally
 *  installing its catalog entry first. Uses the same OAuth flow as Settings. */
export async function completeMcpOAuth(
  options: Parameters<typeof completeMcpDesktopOAuth>[0] & { catalogPreset?: string }
) {
  const profile = capabilityScoped(options.profile)

  if (options.catalogPreset) {
    const added = await requestGatewayForAgent<{ ok?: boolean; error?: string }>(
      profile.connectionId ?? null,
      profile.profile || 'default',
      'mcp.servers.add',
      { name: options.serverName, preset: options.catalogPreset }
    )

    if (!added.ok) {
      throw new Error(added.error || 'Could not add server')
    }
  }

  return completeMcpDesktopOAuth({ ...options, profile })
}
