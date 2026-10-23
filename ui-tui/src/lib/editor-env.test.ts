import { delimiter } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

vi.mock('node:child_process', () => ({ spawnSync: vi.fn(() => ({ status: 0 })) }))
vi.mock('@hermes/ink', () => ({ withInkSuspended: async (fn: () => Promise<void>) => fn() }))

import { spawnSync } from 'node:child_process'

import { editorChildEnv } from './editor-env.js'
import { openInEditor } from './editor.js'

describe('editorChildEnv', () => {
  it('drops Hermes bundled Python from PATH and the interpreter variables', () => {
    const home = '/home/user'
    const tools = `${home}/.hermes/tools/python-3.14.7+202****0101-linux-x64/bin`
    const venv = `${home}/.hermes/installs/abc/environments/def/venv/bin`

    const env = editorChildEnv({
      EDITOR: 'vim',
      PATH: `${tools}${delimiter}/usr/bin${delimiter}${venv}`,
      PYTHONHOME: tools,
      PYTHONPATH: `${home}/hermes`,
      VIRTUAL_ENV: `${home}/.hermes/installs/abc/environments/def/venv`
    })

    expect(env.PATH).toBe('/usr/bin')
    expect(env.PYTHONHOME).toBeUndefined()
    expect(env.PYTHONPATH).toBeUndefined()
    expect(env.VIRTUAL_ENV).toBeUndefined()
    expect(env.EDITOR).toBe('vim')
  })

  it('drops an install venv that sits directly under installs/<key>', () => {
    const env = editorChildEnv({
      PATH: `/usr/bin${delimiter}/home/user/.hermes/installs/abc/venv/bin`
    })

    expect(env.PATH).toBe('/usr/bin')
  })

  it('keeps a user virtualenv and unrelated PATH entries', () => {
    const env = editorChildEnv({
      PATH: `/home/user/.venvs/project/bin${delimiter}/usr/bin${delimiter}/home/user/.local/bin`
    })

    expect(env.PATH).toBe(`/home/user/.venvs/project/bin${delimiter}/usr/bin${delimiter}/home/user/.local/bin`)
  })

  it('matches a PATH entry written with backslashes', () => {
    const windowsStyle = '\\home\\user\\.hermes\\tools\\python-3.14.7\\bin'
    const env = editorChildEnv({ PATH: `${windowsStyle}${delimiter}/usr/bin` })

    expect(env.PATH).toBe('/usr/bin')
  })
})

describe('openInEditor', () => {
  it('launches the editor with the sanitized environment, not the inherited one', async () => {
    const tools = '/home/user/.hermes/tools/python-3.14.7/bin'
    vi.stubEnv('EDITOR', 'true')
    vi.stubEnv('PATH', `${tools}${delimiter}/usr/bin`)
    vi.stubEnv('VIRTUAL_ENV', '/home/user/.hermes/installs/abc/venv')

    try {
      await openInEditor('body')

      const [, , options] = vi.mocked(spawnSync).mock.calls.at(-1) as unknown as [
        string,
        string[],
        { env: NodeJS.ProcessEnv }
      ]

      expect(options.env.PATH).toBe('/usr/bin')
      expect(options.env.VIRTUAL_ENV).toBeUndefined()
      expect(options.env.EDITOR).toBe('true')
    } finally {
      vi.unstubAllEnvs()
    }
  })
})
