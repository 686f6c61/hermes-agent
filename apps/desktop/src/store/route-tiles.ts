import { atom } from 'nanostores'

import { findGroupOfPane } from '@/components/pane-shell/tree/model'
import { $layoutTree, isPaneVisible, noteActiveTreeGroup, revealTreePane } from '@/components/pane-shell/tree/store'
import { readJson, writeJson } from '@/lib/storage'

import type { SplitDir } from './session-states'

/**
 * Route (page) tiles — a full-page view (Capabilities / Messaging / Artifacts,
 * or any plugin route) rendered as a layout-tree pane BESIDE the main thread,
 * the page analog of session tiles. Persisted by path so they re-open on boot.
 */
export interface RouteTile {
  /** The route path this tile renders, e.g. `/capabilities`. */
  path: string
  /** Edge to dock against main on adoption (default right). */
  dir?: SplitDir
}

const TILES_KEY = 'hermes.desktop.routeTiles.v1'

/** Layout-tree pane-id namespace shared with route-tile.tsx's paneMirror —
 *  the id is `${ROUTE_TILE_PANE_PREFIX}:${path}`. */
export const ROUTE_TILE_PANE_PREFIX = 'route-tile'

export function routeTilePaneId(path: string): string {
  return `${ROUTE_TILE_PANE_PREFIX}:${path}`
}

function loadTiles(): RouteTile[] {
  const parsed = readJson<unknown>(TILES_KEY)

  return Array.isArray(parsed)
    ? parsed
        .filter((t): t is RouteTile => Boolean(t && typeof (t as RouteTile).path === 'string'))
        .map(t => ({ dir: t.dir, path: t.path }))
    : []
}

export const $routeTiles = atom<RouteTile[]>(loadTiles())

function saveTiles(tiles: RouteTile[]) {
  $routeTiles.set(tiles)
  writeJson(TILES_KEY, tiles.length === 0 ? null : tiles)
}

/** Open (or front) a page tile for a route, docked on `dir` (default right).
 *  Idempotent — an already-open tile keeps its original edge. */
export function openRouteTile(path: string, dir: SplitDir = 'right') {
  const tiles = $routeTiles.get()

  if (!tiles.some(t => t.path === path)) {
    saveTiles([...tiles, { dir, path }])
  }
}

export function closeRouteTile(path: string) {
  saveTiles($routeTiles.get().filter(t => t.path !== path))
}

/** Front a route tile's own pane after a navigate to its path. The router saw
 *  no change, so nothing reveals the pane on its own — the route-tile analog
 *  of `focusOpenSession`'s tile branch: reveal (un-dismiss + adopt + front in
 *  its group), then mark the group active so the sidebar/readouts come home. */
export function revealRouteTilePane(path: string): void {
  const paneId = routeTilePaneId(path)

  revealTreePane(paneId)

  const tree = $layoutTree.get()
  const group = tree ? findGroupOfPane(tree, paneId) : null

  if (group && isPaneVisible(paneId)) {
    noteActiveTreeGroup(group.id)
  }
}
