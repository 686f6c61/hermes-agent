import { afterEach, describe, expect, it, vi } from 'vitest'

import { $connection } from '@/store/session'
import type { SessionInfo, SessionMessage } from '@/types/hermes'

import {
  artifactImageSrc,
  collectArtifactsForSession,
  loadArtifactsForSessions,
  toEpochMs
} from './artifact-utils'

function makeSession(overrides: Partial<SessionInfo> = {}): SessionInfo {
  return {
    ended_at: null,
    id: 'session-1',
    input_tokens: 0,
    is_active: false,
    last_active: 1000,
    message_count: 1,
    model: null,
    output_tokens: 0,
    preview: null,
    source: null,
    started_at: 1000,
    title: 'Session',
    tool_call_count: 0,
    ...overrides
  }
}

describe('collectArtifactsForSession', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
    $connection.set(null)
  })

  it('indexes plain https links from assistant text', () => {
    const artifacts = collectArtifactsForSession(makeSession(), [
      {
        content: 'Reference: https://example.com/docs/getting-started',
        role: 'assistant',
        timestamp: 2000
      }
    ])

    expect(artifacts).toHaveLength(1)
    expect(artifacts[0]).toMatchObject({
      href: 'https://example.com/docs/getting-started',
      kind: 'link',
      value: 'https://example.com/docs/getting-started',
      // DB seconds → ms for Date formatting (#81016)
      timestamp: 2_000_000
    })
  })

  it('converts second-based session timestamps to ms when messages omit them', () => {
    // 2026-08-07 19:43:00 UTC
    const sessionTs = Math.floor(Date.UTC(2026, 7, 7, 19, 43, 0) / 1000)
    const artifacts = collectArtifactsForSession(
      makeSession({ last_active: sessionTs, started_at: sessionTs }),
      [
        {
          content: 'See https://example.com/report.pdf',
          role: 'assistant'
        }
      ]
    )

    expect(artifacts).toHaveLength(1)
    expect(artifacts[0].timestamp).toBe(sessionTs * 1000)
    // Must not render as 1970 when fed to Date
    expect(new Date(artifacts[0].timestamp).getUTCFullYear()).toBe(2026)
    expect(new Date(artifacts[0].timestamp).getUTCMonth()).toBe(7)
  })

  it('indexes http links present in tool JSON payloads', () => {
    const messages: SessionMessage[] = [
      {
        content: JSON.stringify({ source_url: 'https://example.com/changelog/latest' }),
        role: 'tool',
        timestamp: 3000
      }
    ]

    const artifacts = collectArtifactsForSession(makeSession({ id: 'session-2' }), messages)

    expect(artifacts).toHaveLength(1)
    expect(artifacts[0]).toMatchObject({
      href: 'https://example.com/changelog/latest',
      kind: 'link',
      value: 'https://example.com/changelog/latest'
    })
  })

  it('resolves remote image artifact thumbnails through the desktop fs bridge', async () => {
    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path.startsWith('/api/fs/read-data-url?')) {
        return { dataUrl: 'data:image/jpeg;base64,cmVtb3Rl' }
      }

      throw new Error(`unexpected path ${path}`)
    })

    vi.stubGlobal('window', { hermesDesktop: { api } })
    $connection.set({ baseUrl: 'https://gw', mode: 'remote', token: 'secret' } as never)

    const path = '/Users/me/.hermes/skills/work-esab/references/images/manual-step03.jpeg'
    const downloadHref = `https://gw/api/files/download?path=${encodeURIComponent(path)}&token=secret`

    await expect(artifactImageSrc(path, downloadHref)).resolves.toBe('data:image/jpeg;base64,cmVtb3Rl')

    expect(api).toHaveBeenCalledWith({
      path: '/api/fs/read-data-url?path=%2FUsers%2Fme%2F.hermes%2Fskills%2Fwork-esab%2Freferences%2Fimages%2Fmanual-step03.jpeg'
    })
  })
})

describe('toEpochMs', () => {
  it('multiplies second-scale values and leaves millisecond values alone', () => {
    expect(toEpochMs(1_700_000_000)).toBe(1_700_000_000_000)
    expect(toEpochMs(1_700_000_000_000)).toBe(1_700_000_000_000)
  })
})

describe('loadArtifactsForSessions', () => {
  it('loads transcripts serially and continues after a session fails', async () => {
    const sessions = [
      makeSession({ id: 'session-1' }),
      makeSession({ id: 'session-2' }),
      makeSession({ id: 'session-3' })
    ]

    const callOrder: string[] = []
    let activeLoads = 0
    let maxActiveLoads = 0

    const result = await loadArtifactsForSessions(sessions, async session => {
      activeLoads += 1
      maxActiveLoads = Math.max(maxActiveLoads, activeLoads)
      callOrder.push(`start:${session.id}`)

      try {
        await Promise.resolve()

        if (session.id === 'session-2') {
          throw new Error('Session transcript exceeds the Desktop safe-load limit')
        }

        return [
          {
            content: `https://example.com/${session.id}.png`,
            role: 'assistant',
            timestamp: 2000
          }
        ]
      } finally {
        callOrder.push(`end:${session.id}`)
        activeLoads -= 1
      }
    })

    expect(maxActiveLoads).toBe(1)
    expect(callOrder).toEqual([
      'start:session-1',
      'end:session-1',
      'start:session-2',
      'end:session-2',
      'start:session-3',
      'end:session-3'
    ])
    expect(result.artifacts.map(artifact => artifact.sessionId)).toEqual(['session-1', 'session-3'])
    expect(result.failures).toHaveLength(1)
    expect(result.failures[0]?.session.id).toBe('session-2')
  })
})
