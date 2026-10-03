// apps/shared tests run in the plain Node environment. The JSON-RPC gateway
// tests dispatch real CloseEvent instances so the handshake-close path (code +
// reason surfaced distinctly from a timeout) stays guarded. CloseEvent is not a
// global in every engine-permitted Node release (the `engines` range allows
// 22.22/24.11, where it is absent), so on those runtimes the guard dies with
// "ReferenceError: CloseEvent is not defined" instead of running (#131956).
//
// Assigned with ??= rather than vi.stubGlobal so a test's unstubAllGlobals()
// cannot strip it mid-suite — same rationale as the desktop setup's
// ResizeObserver. On runtimes that already ship CloseEvent this is a no-op.
class CloseEventStub extends Event {
  readonly code: number
  readonly reason: string
  readonly wasClean: boolean

  constructor(type: string, eventInit?: CloseEventInit) {
    super(type, eventInit)
    this.code = eventInit?.code ?? 0
    this.reason = eventInit?.reason ?? ''
    this.wasClean = eventInit?.wasClean ?? false
  }
}

globalThis.CloseEvent ??= CloseEventStub as unknown as typeof CloseEvent
