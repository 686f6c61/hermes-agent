// The directory an embedded terminal may spawn in. The pane's cwd can arrive from the session, and a
// Desktop client can be attached to a backend on ANOTHER host: the path then exists locally while
// belonging to an account this user cannot enter (another account's 0700 home is the usual case).
// node-pty spawns a local PTY with that cwd, chdir(2) fails with EACCES, the shell exits 1, and the
// onExit handler removes the tab together with the only copy of the error — the button looks dead
// (#141686). A local pane has no business starting in a directory the user cannot enter, so the app
// home is the honest default. Pure: the platform's stat/access calls arrive as probes so tests need
// no real permission bits (they are a no-op for root, and this host runs CI as root in containers).
import path from 'node:path'

export interface TerminalCwdProbe {
  /** True when the path exists and is a directory. Throws when it does not exist. */
  isDirectory: (candidate: string) => boolean
  /** True when this user may enter and read the directory. Throws when it may not. */
  isEnterable: (candidate: string) => boolean
}

export function terminalSpawnCwd(
  cwd: null | string | undefined,
  home: string,
  probe: TerminalCwdProbe
): string {
  const candidate = path.resolve(String(cwd || home))

  try {
    const dir = probe.isDirectory(candidate) ? candidate : path.dirname(candidate)

    return probe.isEnterable(dir) ? dir : home
  } catch {
    return home
  }
}
