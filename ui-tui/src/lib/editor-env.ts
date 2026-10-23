import { delimiter } from 'node:path'

const HERMES_PYTHON_BIN = /\/\.hermes\/(?:tools\/python-[^/]+|installs\/[^/]+(?:\/environments\/[^/]+)?\/venv)\/bin\/?$/

/**
 * Environment for the external editor child.
 *
 * Ctrl+G used to inherit the interpreter Hermes runs on. Vim then picked up
 * the bundled, stripped Python from `$PATH` (its `site` directory carries the
 * stdlib only), loaded it as its embedded interpreter and died with
 * `ModuleNotFoundError: _posixsubprocess` on the first UltiSnips expansion.
 * Drop the bundled entries and the variables that point at them, keep
 * everything else: the editor belongs to the user's environment.
 */
export const editorChildEnv = (env: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv => {
  const next: NodeJS.ProcessEnv = { ...env }

  delete next.PYTHONHOME
  delete next.PYTHONPATH
  delete next.VIRTUAL_ENV

  if (next.PATH) {
    next.PATH = next.PATH.split(delimiter)
      .filter(dir => !HERMES_PYTHON_BIN.test(dir.replace(/\\/g, '/')))
      .join(delimiter)
  }

  return next
}
