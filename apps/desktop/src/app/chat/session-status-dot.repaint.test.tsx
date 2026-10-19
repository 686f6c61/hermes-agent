import { act, cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { $projects } from '@/store/projects'
import { $sessions, sessionPinId } from '@/store/session'
import { $sessionColorOverrides, setSessionColorOverride } from '@/store/session-color'

import { makeCwdSession } from '../../test/session-info'

import { SessionStatusDot } from './session-status-dot'

// #141434: the idle dot resolved its colour with a plain `sessionColorFor(session)`
// call next to a bare `useStore($sessionColorById)` subscription. The compiler
// treats that helper as a pure function of `session`, so picking a colour — which
// leaves the session object untouched — served the cached colour until the row
// remounted. These tests run through the compiler-enabled Vite config on purpose:
// a compiler-stripped run would pass either way.

afterEach(() => {
  cleanup()
  $sessions.set([])
  $projects.set([])
  $sessionColorOverrides.set({})
  localStorage.clear()
})

/** The idle dot is the only `aria-hidden` span when no branch stem is passed. */
function idleDot(container: HTMLElement): HTMLElement {
  const dot = container.querySelector('span[aria-hidden="true"]')

  if (!(dot instanceof HTMLElement)) {
    throw new Error('the dot did not render')
  }

  return dot
}

describe('SessionStatusDot colour repaint (#141434)', () => {
  it('repaints a mounted dot when a colour override is picked', async () => {
    const a = makeCwdSession('/www/app', { git_repo_root: '/www/app' })
    $sessions.set([a])

    const { container } = render(<SessionStatusDot session={a} storedSessionId={a.id} />)
    expect(idleDot(container).style.backgroundColor).toBe('')

    await act(async () => {
      setSessionColorOverride(sessionPinId(a), '#ff0000')
    })

    expect(idleDot(container).style.backgroundColor).toBe('rgb(255, 0, 0)')
  })

  it('repaints a project-tree session that is not in the recents page', async () => {
    // This session has no `$sessionColorById` entry, so it resolves through the
    // helper's fallback — the half a fix that only reads the map would miss.
    const older = makeCwdSession('/www/app', { git_repo_root: '/www/app' })

    const { container } = render(<SessionStatusDot session={older} storedSessionId={older.id} />)
    expect(idleDot(container).style.backgroundColor).toBe('')

    await act(async () => {
      setSessionColorOverride(sessionPinId(older), '#00ff00')
    })

    expect(idleDot(container).style.backgroundColor).toBe('rgb(0, 255, 0)')
  })
})
