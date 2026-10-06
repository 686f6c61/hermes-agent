import { act, cleanup, render, waitFor } from '@testing-library/react'
import type { MutableRefObject } from 'react'
import { useEffect } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { registry } from '@/contrib/registry'
import { revealTreePane } from '@/components/pane-shell/tree/store'
import { $routeTiles } from '@/store/route-tiles'
import type { ClientSessionState } from '../../../types'

import { useSessionActions } from './index'

vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  deleteSession: vi.fn(),
  getSession: vi.fn(),
  getAllSessionMessages: vi.fn(),
  getLatestSessionMessages: vi.fn(),
  listAllProfileSessions: vi.fn(),
  setApiRequestProfile: vi.fn(),
  setSessionArchived: vi.fn()
}))

vi.mock('@/store/profile', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ensureGatewayAgent: vi.fn().mockResolvedValue(undefined),
  ensureGatewayProfile: vi.fn().mockResolvedValue(undefined)
}))

vi.mock('@/store/gateway', async importOriginal => {
  const original = await importOriginal<Record<string, unknown>>()

  return {
    ...original,
    activeGatewayConnectionId: vi.fn(original.activeGatewayConnectionId as () => null | string),
    requestGatewayForAgent: vi.fn(),
    requestGatewayForProfile: vi.fn(),
    retainGatewayForAgent: vi.fn(async () => () => undefined)
  }
})

vi.mock('@/components/pane-shell/tree/store', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  noteActiveTreeGroup: vi.fn(),
  revealTreePane: vi.fn()
}))

type HarnessHandle = Pick<ReturnType<typeof useSessionActions>, 'selectSidebarItem'>

function Harness({
  navigate,
  onReady
}: {
  navigate: ReturnType<typeof vi.fn>
  onReady: (handle: HarnessHandle) => void
}) {
  const ref = <T,>(value: T): MutableRefObject<T> => ({ current: value })

  const actions = useSessionActions({
    activeSessionId: null,
    activeSessionIdRef: ref(null),
    busyRef: ref(false),
    creatingSessionRef: ref(false),
    ensureSessionState: () => ({}) as ClientSessionState,
    getRouteToken: () => 'token',
    getRoutedStoredSessionId: () => null,
    navigate: navigate as never,
    requestGateway: vi.fn(async () => ({}) as never),
    resetViewSync: vi.fn(),
    routedSessionId: null,
    runtimeIdByStoredSessionIdRef: ref(new Map<string, string>()),
    selectedStoredSessionId: null,
    selectedStoredSessionIdRef: ref(null),
    sessionStateByRuntimeIdRef: ref(new Map<string, ClientSessionState>()),
    syncSessionStateToView: vi.fn(),
    updateSessionState: () => ({}) as ClientSessionState
  })

  useEffect(() => {
    onReady(actions)
  }, [actions, onReady])

  return null
}

function contributeRoute(): () => void {
  return registry.register({
    id: 'page',
    area: 'routes',
    source: 'plugin:kanban',
    data: { path: '/kanban' },
    render: () => null
  })
}

async function mountActions(navigate: ReturnType<typeof vi.fn>): Promise<HarnessHandle> {
  let handle: HarnessHandle | null = null

  render(<Harness navigate={navigate} onReady={value => (handle = value)} />)
  await waitFor(() => expect(handle).not.toBeNull())

  return handle!
}

function kanbanItem(): { icon: never; id: string; label: string; route: string } {
  return {
    icon: (() => null) as never,
    id: 'kanban',
    label: 'Kanban',
    route: '/kanban'
  }
}

describe('selectSidebarItem contributed routes as tiles (#101593)', () => {
  afterEach(() => {
    cleanup()
    $routeTiles.set([])
    vi.clearAllMocks()
  })

  it('opens contributed plugin pages as closable tiles instead of replacing chat', async () => {
    const dispose = contributeRoute()

    try {
      const navigate = vi.fn()
      const handle = await mountActions(navigate)

      $routeTiles.set([])
      act(() => {
        handle.selectSidebarItem(kanbanItem())
      })

      expect(navigate).not.toHaveBeenCalled()
      expect($routeTiles.get().some(tile => tile.path === '/kanban')).toBe(true)
    } finally {
      dispose()
    }
  })

  it('fronts the tile pane on a re-click while a zone is parked elsewhere', async () => {
    const dispose = contributeRoute()

    try {
      const navigate = vi.fn()
      const handle = await mountActions(navigate)

      $routeTiles.set([])
      act(() => {
        handle.selectSidebarItem(kanbanItem())
        handle.selectSidebarItem(kanbanItem())
      })

      expect(vi.mocked(revealTreePane).mock.calls.some(([pane]) => pane === 'route-tile:/kanban')).toBe(true)
    } finally {
      dispose()
    }
  })
})
