import type { SessionInfo } from '@/types/hermes'

/**
 * Index sessions by every id a pin might be stored under.
 *
 * The sidebar fetches three independent slices — recents, cron, and messaging
 * — and renders the latter two in self-managed sections. Any of them can be
 * pinned, so all three must be indexed here or the Pinned section can't
 * resolve the pin to a row. A pinned session is also filtered out of its own
 * section, so failing to index it doesn't merely misplace the row: it removes
 * the session from the sidebar entirely.
 *
 * Each session is keyed under both its live id and its lineage root, so a pin
 * stored before an auto-compression still resolves to the live continuation
 * tip. Recents are indexed last and win a direct id collision.
 */
export function buildSessionByAnyId(
  visibleSessions: SessionInfo[],
  cronSessions: SessionInfo[],
  messagingSessions: SessionInfo[]
): Map<string, SessionInfo> {
  const map = new Map<string, SessionInfo>()

  for (const session of [...cronSessions, ...messagingSessions, ...visibleSessions]) {
    map.set(session.id, session)

    if (session._lineage_root_id && !map.has(session._lineage_root_id)) {
      map.set(session._lineage_root_id, session)
    }
  }

  return map
}

/**
 * Resolve the Pinned section's rows: the locally stored pin ids first (in the
 * user's hand-picked order), then any row the SERVER flags `pinned` that the
 * local set doesn't know about yet.
 *
 * The local set (`$pinnedSessionIds` in localStorage) is a UI-ordering hint,
 * not the source of truth — `sessions.pinned` in the backend's state.db is.
 * When the two disagree (cold localStorage after a reload, a pin made from
 * another client, a persist that never landed), every other sidebar list
 * filters the session out as "pinned" while the Pinned section — resolving
 * only local ids — renders empty, so the conversation vanishes from the
 * sidebar entirely (#85969). Falling back to the row flag keeps the invariant:
 * a session the backend says is pinned is always reachable from the Pinned
 * section, whatever the local cache holds. session-pin-sync then adopts the
 * pin into the local set on its next reconcile, restoring ordering control.
 *
 * `unconfirmedPinWrites` is that same module's fence, and the fallback has to
 * respect it. Unpinning drops the id from the local set immediately, but the
 * loaded row keeps saying `pinned: true` until a page issued after the PATCH
 * lands — so an unfenced fallback reads the user's own unpin as a foreign pin
 * and parks the session at the bottom of Pinned for a refresh cycle before it
 * finally moves to Sessions.
 */
export function resolvePinnedSessions(
  pinnedSessionIds: readonly string[],
  sessionByAnyId: Map<string, SessionInfo>,
  allSessions: readonly SessionInfo[],
  unconfirmedPinWrites: ReadonlySet<string>
): SessionInfo[] {
  const seen = new Set<string>()
  const out: SessionInfo[] = []

  for (const pinId of pinnedSessionIds) {
    const session = sessionByAnyId.get(pinId)

    if (session && !seen.has(session.id)) {
      seen.add(session.id)
      out.push(session)
    }
  }

  for (const session of allSessions) {
    if (session.pinned !== true || seen.has(session.id)) {
      continue
    }

    // A pin write of ours the row predates — under either identity, since the
    // fence is keyed on the durable id and the row may surface as its tip.
    if (
      unconfirmedPinWrites.has(session.id) ||
      (session._lineage_root_id != null && unconfirmedPinWrites.has(session._lineage_root_id))
    ) {
      continue
    }

    seen.add(session.id)
    out.push(session)
  }

  return out
}

/**
 * Every id whose rows the other lists suppress because Pinned renders them.
 *
 * Suppression and rendering have to agree. A stored pin id that resolves to no loaded session
 * is not rendered by Pinned, so it must not hide the row either: a conversation whose
 * compression moved the tip kept the old lineage-root id in the connection-scoped local pin
 * set, and the raw id alone then removed it from its Project (which filters pins out) while
 * Pinned, resolving the id against the loaded rows, had nothing to show. Hidden from both is
 * the one outcome the sidebar must never produce (#141717).
 *
 * A resolved pin contributes BOTH identities of its session: the pin is stored on the durable
 * lineage root, while the lists that filter it are fed by three independent fetches (recents,
 * the messaging slice, the backend project tree) and each can surface the conversation under
 * either its live tip or its root. Comparing one identity against the other is how a pinned
 * session ended up rendered twice — once in Pinned, once in its project group.
 */
export function buildPinnedIdentitySet(
  pinnedSessionIds: readonly string[],
  sessionByAnyId: Map<string, SessionInfo>,
  pinnedSessions: readonly SessionInfo[]
): Set<string> {
  const ids = new Set(pinnedSessionIds.filter(id => sessionByAnyId.has(id)))

  for (const session of pinnedSessions) {
    ids.add(session.id)

    if (session._lineage_root_id) {
      ids.add(session._lineage_root_id)
    }
  }

  return ids
}
