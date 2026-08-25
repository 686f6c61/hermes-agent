import { afterEach, describe, expect, it, vi } from 'vitest'

import { createTimeoutBag } from './timeout-bag'

afterEach(() => {
  vi.useRealTimers()
})

describe('createTimeoutBag', () => {
  it('runs a scheduled callback', () => {
    vi.useFakeTimers()
    const bag = createTimeoutBag()
    const fn = vi.fn()

    bag.schedule(fn, 200)
    expect(fn).not.toHaveBeenCalled()
    vi.advanceTimersByTime(200)
    expect(fn).toHaveBeenCalledOnce()
  })

  it('clearAll prevents a pending callback from running after the owner unmounts', () => {
    vi.useFakeTimers()
    const bag = createTimeoutBag()
    const fn = vi.fn()

    bag.schedule(fn, 200)
    bag.clearAll()
    vi.advanceTimersByTime(200)
    expect(fn).not.toHaveBeenCalled()
  })
})
