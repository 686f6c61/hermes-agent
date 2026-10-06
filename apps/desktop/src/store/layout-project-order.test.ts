import { beforeEach, describe, expect, it } from 'vitest'

import { rescopeConnectionScopedStores } from '@/lib/connection-scoped'

import { $sidebarProjectOrderIds } from './layout'

const remote = (profile: string) => ({
  baseUrl: 'https://gw.example:8443',
  mode: 'remote' as const,
  profile
})

const PROJECT_ORDER_KEY = 'hermes.desktop.projectOrder'

beforeEach(() => {
  rescopeConnectionScopedStores({ mode: 'local' })
  window.localStorage.clear()
  $sidebarProjectOrderIds.set([])
})

describe('$sidebarProjectOrderIds', () => {
  it('keeps the project drag order per profile when the window rescopes', () => {
    rescopeConnectionScopedStores(remote('meridian'))
    $sidebarProjectOrderIds.set(['p2', 'p1'])

    rescopeConnectionScopedStores(remote('default'))
    expect($sidebarProjectOrderIds.get()).toEqual([])

    $sidebarProjectOrderIds.set(['p9'])

    rescopeConnectionScopedStores(remote('meridian'))
    expect($sidebarProjectOrderIds.get()).toEqual(['p2', 'p1'])

    rescopeConnectionScopedStores({ mode: 'local' })
  })

  it('lands remote writes under the per-profile key, not the shared legacy key', () => {
    rescopeConnectionScopedStores(remote('meridian'))
    $sidebarProjectOrderIds.set(['p2', 'p1'])

    const scopedKey = `${PROJECT_ORDER_KEY}.remote.${encodeURIComponent('https://gw.example:8443')}.meridian`

    expect(window.localStorage.getItem(scopedKey)).not.toBeNull()
    expect(window.localStorage.getItem(PROJECT_ORDER_KEY)).toBeNull()

    rescopeConnectionScopedStores({ mode: 'local' })
  })

  it('keeps the bare legacy key on the local connection', () => {
    $sidebarProjectOrderIds.set(['a', 'b'])

    expect(window.localStorage.getItem(PROJECT_ORDER_KEY)).not.toBeNull()

    rescopeConnectionScopedStores(remote('other'))
    expect($sidebarProjectOrderIds.get()).toEqual([])

    rescopeConnectionScopedStores({ mode: 'local' })
    expect($sidebarProjectOrderIds.get()).toEqual(['a', 'b'])
  })
})
