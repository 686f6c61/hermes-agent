import { JsonRpcGatewayError } from '@hermes/shared'

/** Session ids the gateway has told us are gone. A session-scoped RPC against a
 *  runtime the gateway no longer holds fails 4001 "session not found" — terminal
 *  for THIS runtime id, not a transient socket loss.
 *
 *  Shared by every background poller (process.list, approval.pending, goal
 *  status) and by the owner-routed RPC seam that clears it. This module is a
 *  dependency-free leaf on purpose: `session-request-router` (which every
 *  store imports) must be able to clear the latch after a successful rebind
 *  without pulling the session/tile stores into its import graph. Stores that
 *  also need the heal levers import through `runtime-gone.ts` (which re-exports
 *  this module); cycle-sensitive callers (the router, the gateway event loop)
 *  import the leaf directly. */
const goneSessions = new Set<string>()

/** Owner recorded at latch time so a secondary reconnect can unlatch only its
 *  own corpses. After `markRuntimeGone` unbinds the tile, the runtime id is no
 *  longer on `$sessionTiles` — without this map a scoped reset would miss
 *  every already-healed id (#100327). */
const goneSessionOwners = new Map<string, { connectionId: string; profile: string }>()

/** Connection/profile whose gone-latch should be cleared on reconnect. */
export interface BackgroundPollingGuardScope {
  connectionId: string
  profile?: null | string
}

/** Gateway JSON-RPC code for "session not found" (tui_gateway `_sess_nowait`). */
const GATEWAY_SESSION_NOT_FOUND_CODE = 4001

/** Consecutive heals per stored session id (see `runtime-gone.ts`
 *  `markRuntimeGone`). Lives here so the rebind seam below can refund it
 *  without importing the heal module. */
export const healsByStoredId = new Map<string, number>()

/** A gone session is unrecoverable for THIS runtime id; a timeout or transport
 *  blip is not. Only the former may stop a poll — misclassifying a transient
 *  failure would silently freeze a healthy session.
 *
 *  Match the gateway's 4001 code when the error carries one. Codeless errors
 *  (the frame's structure was lost across the IPC bridge or a wrapped rethrow)
 *  are accepted only with a bare "session not found" body — a tool or report
 *  string that merely mentions the phrase must not latch a live runtime. */
export function isSessionGoneForBackgroundPolling(error: unknown): boolean {
  if (error instanceof JsonRpcGatewayError && typeof error.code === 'number') {
    return error.code === GATEWAY_SESSION_NOT_FOUND_CODE
  }

  const code =
    error && typeof error === 'object' && typeof (error as { code?: unknown }).code === 'number'
      ? (error as { code: number }).code
      : undefined

  if (code !== undefined) {
    return code === GATEWAY_SESSION_NOT_FOUND_CODE
  }

  const message = (error instanceof Error ? error.message : String(error ?? ''))
    .trim()
    .replace(/^Error invoking remote method '[^']+':\s*Error:\s*/i, '')
    .replace(/^Error:\s*/i, '')

  return /^(?:4001\s*[:,-]?\s*)?session not found[.!]?$/i.test(message)
}

export function isSessionGone(sid: null | string | undefined): boolean {
  return Boolean(sid && goneSessions.has(sid))
}

/** Latch `sid` off. Idempotent. `owner` is recorded when the caller still
 *  has the tile (before unbind) so a later scoped reset can match it. */
export function latchSessionGone(
  sid: string,
  owner?: { connectionId: string; profile: string } | null
): void {
  if (!sid) {
    return
  }

  goneSessions.add(sid)

  const connectionId = owner?.connectionId?.trim()

  if (connectionId) {
    goneSessionOwners.set(sid, {
      connectionId,
      profile: (owner?.profile || '').trim()
    })
  }
}

/** Clear the gone-latch.
 *
 *  - session id: a fresh runtime bound to that id, so polling resumes
 *  - `{ connectionId, profile }`: only that reconnecting secondary's latched ids
 *  - no argument: tests / a primary backend re-mint that recycles every id */
export function resetBackgroundPollingGuard(sidOrScope?: BackgroundPollingGuardScope | string): void {
  if (!sidOrScope) {
    goneSessions.clear()
    goneSessionOwners.clear()
    // Same lifetime as the latch: a respawned backend re-mints every runtime
    // id, so every stored session's heal budget starts over too.
    healsByStoredId.clear()

    return
  }

  if (typeof sidOrScope === 'string') {
    goneSessions.delete(sidOrScope)
    goneSessionOwners.delete(sidOrScope)

    return
  }

  const wantedConnection = sidOrScope.connectionId.trim()
  const wantedProfile = sidOrScope.profile?.trim() || ''

  for (const sid of [...goneSessions]) {
    const owner = goneSessionOwners.get(sid)

    if (!owner || owner.connectionId !== wantedConnection) {
      continue
    }

    if (wantedProfile && owner.profile !== wantedProfile) {
      continue
    }

    goneSessions.delete(sid)
    goneSessionOwners.delete(sid)
  }
}

/** Ids a successful `session.resume` / `session.activate` just rebound — the
 *  stored id it was asked for and the runtime id it answered with. Empty for
 *  any other method: a socket reconnect is NOT a rebind (the backend may have
 *  reaped the old runtime, and reopening a WebSocket does not make that id
 *  valid again). Only a successful resume/activate response is proof. */
function reboundSessionIds(method: string, params: Record<string, unknown>, result: unknown): string[] {
  if (method !== 'session.activate' && method !== 'session.resume') {
    return []
  }

  const ids: string[] = []

  for (const value of [params.session_id, (result as { session_id?: unknown } | null)?.session_id]) {
    if (typeof value === 'string' && value.trim()) {
      ids.push(value.trim())
    }
  }

  return ids
}

/** Un-latch the ids a successful `session.resume` / `session.activate` just
 *  rebound and refund the stored session's heal budget: a rebind is proof of
 *  life, so the NEXT reap can still be healed. Without the refund a backend
 *  that reaps a detached runtime a few times (per-request lease sockets
 *  closing between polls) exhausts the heal cap and the view is stuck on a
 *  phantom id forever (#100639: 1,230 approval.pending 4001s on one runtime
 *  id in 42 minutes, zero recovery). Called by the session request router on
 *  every routed RPC result; a no-op for every method but resume/activate. */
export function resetBackgroundPollingGuardAfterRebind(
  method: string,
  params: Record<string, unknown>,
  result: unknown
): void {
  for (const id of reboundSessionIds(method, params, result)) {
    goneSessions.delete(id)
    goneSessionOwners.delete(id)
    healsByStoredId.delete(id)
  }
}

/** Adapt a store-level gateway handle (`$gateway.get()` or the narrower
 *  `ApprovalGateway` shape) to the ambient-request callback
 *  `requestForOwnedSession` expects. The pollers never pass a deadline, so the
 *  2-arg call shape is kept exactly (gateway.request callers assert on it). */
export function ambientRequestFor(gateway: {
  request: (method: string, params: Record<string, unknown>) => Promise<unknown>
}): <R>(method: string, params?: Record<string, unknown>) => Promise<R> {
  return <R>(method: string, params?: Record<string, unknown>) => gateway.request(method, params ?? {}) as Promise<R>
}
