import assert from 'node:assert/strict'

import { test } from 'vitest'

import { terminalSpawnCwd } from './terminal-cwd'

const HOME = '/home/wojtek'

function probe(dirs: string[], enterable = dirs) {
  return {
    isDirectory: (candidate: string) => {
      if (dirs.includes(candidate)) {
        return true
      }

      if (dirs.some(dir => candidate.startsWith(`${dir}/`))) {
        return false
      }

      throw Object.assign(new Error(`ENOENT: ${candidate}`), { code: 'ENOENT' })
    },
    isEnterable: (candidate: string) => enterable.includes(candidate)
  }
}

test('an enterable session cwd is used as the spawn directory', () => {
  assert.equal(terminalSpawnCwd('/home/wojtek/work', HOME, probe(['/home/wojtek/work'])), '/home/wojtek/work')
})

test('a cwd that exists but cannot be entered falls back to the app home', () => {
  // The reported shape: a remote backend's cwd that also exists here, owned by another account with 0700.
  // statSync succeeds, chdir(2) would return EACCES, and the pane used to close itself on the dead shell.
  assert.equal(terminalSpawnCwd('/home/hermes', HOME, probe(['/home/hermes'], [])), HOME)
})

test('a non-directory cwd spawns in its parent when the parent is enterable', () => {
  const dirs = ['/home/wojtek/work']

  assert.equal(terminalSpawnCwd('/home/wojtek/work/notes.md', HOME, probe(dirs)), '/home/wojtek/work')
})

test('a non-directory cwd whose parent cannot be entered falls back to the app home', () => {
  const dirs = ['/home/hermes']

  assert.equal(terminalSpawnCwd('/home/hermes/notes.md', HOME, probe(dirs, [])), HOME)
})

test('a cwd that does not exist locally falls back to the app home', () => {
  assert.equal(terminalSpawnCwd('/srv/remote-only', HOME, probe([])), HOME)
})

test('no session cwd resolves to the app home', () => {
  assert.equal(terminalSpawnCwd(undefined, HOME, probe([HOME])), HOME)
  assert.equal(terminalSpawnCwd(null, HOME, probe([HOME])), HOME)
  assert.equal(terminalSpawnCwd('', HOME, probe([HOME])), HOME)
})

test('a probe that throws is treated as unusable, not fatal', () => {
  const throwing = {
    isDirectory: () => {
      throw new Error('EPERM')
    },
    isEnterable: () => {
      throw new Error('EPERM')
    }
  }

  assert.equal(terminalSpawnCwd('/home/hermes', HOME, throwing), HOME)
})
