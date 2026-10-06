/**
 * The tile path with NO mocks on the pane machinery: a deep link (or any
 * navigation) to a contributed page must end with the route pane VISIBLE in a
 * real layout tree, docked beside the live chat. Tests that mock
 * `revealTreePane` can pass while a tile never becomes visible, which would
 * fix nothing (#101593).
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { watchRouteTiles } from '@/app/chat/route-tile'
import { group } from '@/components/pane-shell/tree/model'
import { $dismissedPanes, $hiddenTreePanes, $layoutTree, isPaneVisible } from '@/components/pane-shell/tree/store'
import { registry } from '@/contrib/registry'
import { $routeTiles, closeRouteTile } from '@/store/route-tiles'

import { navigateContributedRoute, ROUTES_AREA, syncWorkspaceRoute } from './routes'

const CONTRIBUTED_ROUTE = '/kanban'
const TILE_PANE = `route-tile:${CONTRIBUTED_ROUTE}`

const disposers: (() => void)[] = []

beforeEach(() => {
  $layoutTree.set(group(['workspace'], { active: 'workspace', id: 'g-main' }))
  $dismissedPanes.set(new Set())
  $hiddenTreePanes.set(new Set())
  watchRouteTiles()
})

afterEach(() => {
  disposers.splice(0).forEach(dispose => dispose())
  $routeTiles.set([])
})

function contributeRoute(): () => void {
  return registry.register({
    area: ROUTES_AREA,
    data: { path: CONTRIBUTED_ROUTE },
    id: 'test-route',
    render: () => null
  })
}

describe('a contributed page route ends with a visible tile pane', () => {
  it('a deep link opens the tile and its pane is visible beside the chat', () => {
    const dispose = contributeRoute()

    try {
      syncWorkspaceRoute(CONTRIBUTED_ROUTE)

      expect($routeTiles.get().some(tile => tile.path === CONTRIBUTED_ROUTE)).toBe(true)
      expect(isPaneVisible(TILE_PANE)).toBe(true)
    } finally {
      dispose()
    }
  })

  it('a click through the shared door leaves the pane visible, and closing it removes it', () => {
    const dispose = contributeRoute()

    try {
      expect(navigateContributedRoute(CONTRIBUTED_ROUTE)).toBe(true)
      expect(isPaneVisible(TILE_PANE)).toBe(true)

      closeRouteTile(CONTRIBUTED_ROUTE)

      expect(isPaneVisible(TILE_PANE)).toBe(false)
    } finally {
      dispose()
    }
  })
})
