/**
 * A plugin page route registered AFTER the workspace surface mounts must stay
 * navigable. Regression for late-loaded desktop plugins (disk plugins load
 * async). Since #101593 a contributed page never renders IN the workspace
 * route table — the tile path is the only surface a contributed page shows on
 * — so a late registration must reach the routing layer (the tile door opens
 * the page beside the live chat) while the router falls through to the chat
 * catch-all: the chat is never replaced. Uses the REAL useContributions +
 * registry (unlike surfaces.test.tsx) because the reactive flow is the subject.
 */
import { act, cleanup, render, screen } from '@testing-library/react'
import { atom } from 'nanostores'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { registry } from '@/contrib/registry'
import { $routeTiles } from '@/store/route-tiles'

import { $routesVersion, $workspaceIsPage, syncWorkspaceRoute } from '../routes'

import { ChatRoutesSurface } from './surfaces'
import type { WiringActions } from './types'

vi.mock('@/store/connections', () => ({ $activeConnectionId: atom('local') }))
vi.mock('@/store/gateway', () => ({ $gateway: atom<unknown>(null) }))
vi.mock('@/store/profile', () => ({ $activeGatewayProfile: atom('default') }))
vi.mock('@/store/session', () => ({
  $freshDraftReady: atom(false),
  $gatewayState: atom('open')
}))
vi.mock('../chat', () => ({ ChatView: () => <div data-testid="chat-view" /> }))
vi.mock('../chat/sidebar', () => ({ ChatSidebar: () => null }))
vi.mock('../right-sidebar/terminal/chrome', () => ({ TerminalPaneChrome: () => null }))
vi.mock('../shell/hooks/use-status-snapshot', () => ({ useStatusSnapshot: () => ({}) }))
vi.mock('../shell/hooks/use-statusbar-items', () => ({
  useStatusbarItems: () => ({ leftStatusbarItems: [], statusbarItems: [] })
}))
vi.mock('../shell/statusbar-controls', () => ({ StatusbarControls: () => null }))
vi.mock('./latest-actions', () => ({ latestChatActions: () => ({}), latestSidebarActions: () => ({}) }))
vi.mock('./panes', () => ({ setStatusbarItemGroup: vi.fn(), useStatusbarContributions: () => [] }))
vi.mock('../shell/model-menu-panel', () => ({ ModelMenuPanel: () => null }))
vi.mock('../shell/reasoning-menu-panel', () => ({ ReasoningMenuPanel: () => null }))

afterEach(() => {
  cleanup()
  $routeTiles.set([])
  $workspaceIsPage.set(false)
})

describe('ChatRoutesSurface late-registered plugin routes', () => {
  it('a late registration opens the tile door and never replaces the chat', () => {
    const actions = {} as unknown as WiringActions

    render(
      <MemoryRouter initialEntries={['/late-plugin']}>
        <ChatRoutesSurface actions={actions} />
      </MemoryRouter>
    )

    // Before registration the path falls through to the chat catch-all.
    expect(screen.queryByTestId('late-page')).toBeNull()
    expect(screen.getByTestId('chat-view')).toBeTruthy()

    let dispose = () => {}
    act(() => {
      dispose = registry.register({
        area: 'routes',
        id: 'late-plugin:page',
        data: { path: '/late-plugin' },
        render: () => <div data-testid="late-page" />
      })
    })

    try {
      // The late registration must reach the routing layer: a location still
      // pointing at the page (deep link, back/forward) opens its TILE instead
      // of taking the workspace (#101593)…
      act(() => {
        syncWorkspaceRoute('/late-plugin')
      })

      expect($routeTiles.get().some(tile => tile.path === '/late-plugin')).toBe(true)
      expect($workspaceIsPage.get()).toBe(false)

      // …while the router keeps the chat mounted: the page renders beside the
      // chat as a tile, never instead of it.
      expect(screen.queryByTestId('late-page')).toBeNull()
      expect(screen.getByTestId('chat-view')).toBeTruthy()
    } finally {
      dispose()
    }
  })

  it('a late registration bumps the reactive routes layer for non-React consumers', () => {
    // Pane-mirror tab titles derive outside React from `contributedRoutes()`
    // re-synced by `$routesVersion`; the subscription is what delivers a
    // registration that lands after the tile opened.
    let bumps = 0

    const unwatch = $routesVersion.subscribe(() => {
      bumps += 1
    })

    // The area subscription emits once on attach (current state), so count
    // relative to that baseline.
    const baseline = bumps

    try {
      const dispose = registry.register({
        area: 'routes',
        id: 'late-plugin:reactive',
        data: { path: '/late-plugin-reactive' },
        render: () => null
      })

      try {
        expect(bumps).toBe(baseline + 1)
      } finally {
        dispose()
      }

      expect(bumps).toBe(baseline + 2)
    } finally {
      unwatch()
    }
  })
})
