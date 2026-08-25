/**
 * Timers that must die with the owner. The edit composer unmounts on
 * confirm/cancel while `setTimeout` callbacks still hold `setState`. After
 * jsdom tears `window` down, React 19's scheduler then throws
 * `window is not defined` and fails the whole vitest run even when every
 * test passed.
 */
function createTimeoutBag(
  clock: {
    setTimeout: typeof globalThis.setTimeout
    clearTimeout: typeof globalThis.clearTimeout
  } = globalThis
) {
  const ids = new Set<ReturnType<typeof clock.setTimeout>>()

  function schedule(fn: () => void, ms: number) {
    const id = clock.setTimeout(() => {
      ids.delete(id)
      fn()
    }, ms)
    ids.add(id)

    return id
  }

  function clearAll() {
    for (const id of ids) {
      clock.clearTimeout(id)
    }

    ids.clear()
  }

  return { schedule, clearAll }
}

export { createTimeoutBag }
