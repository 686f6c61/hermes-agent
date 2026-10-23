import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { timelineBarWidth } from './timeline-data'
import { TimelineRail } from './timeline-rail'

vi.mock('@/components/ui/tooltip', () => ({ Tip: ({ children }: { children: ReactNode }) => children }))

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width: 48,
    height: 300,
    top: 0,
    left: 0,
    bottom: 300,
    right: 48,
    x: 0,
    y: 0,
    toJSON: () => ({})
  })
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(300)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(48)
  HTMLElement.prototype.scrollTo = vi.fn()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const entries = Array.from({ length: 5000 }, (_, index) => ({ id: `message-${index}`, preview: `Message ${index}` }))

// The live stylesheet, read directly: the hit-area test below must validate the
// shipped rule, not a copy of it. Tests run with cwd = apps/desktop.
const cssText = readFileSync(resolve(process.cwd(), 'src/components/assistant-ui/thread/timeline.css'), 'utf8')

function ruleBody(selector: string): string {
  const start = cssText.indexOf(`${selector} {`)

  expect(start, `missing rule ${selector}`).toBeGreaterThanOrEqual(0)

  return cssText.slice(start, cssText.indexOf('}', start))
}

function rem(body: string, property: string): number {
  const match = new RegExp(`${property}:\\s*([\\d.]+)rem`).exec(body)

  expect(match, `missing ${property} in rem`).not.toBeNull()

  return Number.parseFloat(match?.[1] ?? 'NaN')
}

/** `padding: 0 0.375rem 0 0` — the right value is what separates bar and edge. */
function paddingRight(body: string): number {
  const match = /padding:\s*[\d.]+(?:rem)?\s+([\d.]+)rem/.exec(body)

  expect(match, 'missing right padding in rem').not.toBeNull()

  return Number.parseFloat(match?.[1] ?? 'NaN')
}

describe('TimelineRail', () => {
  it('bounds mounted buttons for thousands of prompts', () => {
    const view = render(<TimelineRail activeIndex={0} entries={entries} loadingId={null} onJump={vi.fn()} />)

    expect(view.container.querySelectorAll('button').length).toBeGreaterThan(0)
    expect(view.container.querySelectorAll('button').length).toBeLessThan(60)
  })

  it('keeps the active bar compact without hover and routes selection by stable ID', () => {
    const onJump = vi.fn()
    render(<TimelineRail activeIndex={0} entries={entries} loadingId={null} onJump={onJump} />)

    const active = screen.getByRole('button', { name: 'Message 0' })

    expect(active.getAttribute('aria-current')).toBe('location')
    fireEvent.click(active)
    expect(onJump).toHaveBeenCalledWith('message-0')
  })

  it('keeps the tick hit area over the drawn bar instead of the whole 3rem strip', () => {
    const tick = ruleBody('.thread-timeline-tick')
    const bar = ruleBody(".thread-timeline-tick [data-slot='timeline-bar']")
    const widestBar = timelineBarWidth(0, 0, 0)

    // The strip is 3rem and the bar is drawn against its right edge, so a
    // full-width tick is a 48px button for an 8px line. It shares the corner
    // with the code block's expand toggle, which is the mis-click in #143184.
    expect(tick).toMatch(/right:\s*0/)
    expect(tick).not.toMatch(/left:\s*0/)
    expect(tick).not.toMatch(/width:\s*100%/)
    expect(ruleBody('.thread-timeline-ticks')).toMatch(/width:\s*3rem/)

    // The box has to contain the widest bar the hover curve paints, plus the
    // right padding that separates the bar from the pane edge.
    expect(rem(tick, 'width')).toBeGreaterThanOrEqual(widestBar + paddingRight(tick))
    expect(rem(tick, 'width')).toBeGreaterThanOrEqual(1.5)
    expect(rem(bar, 'width')).toBe(0.5)
  })
})
