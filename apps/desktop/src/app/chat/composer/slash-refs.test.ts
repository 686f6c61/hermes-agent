import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { rememberDesktopCommandsCatalog } from '@/lib/desktop-slash-commands'

import { slashCommandMatches } from './slash-refs'

const commands = (text: string, options?: Parameters<typeof slashCommandMatches>[1]) =>
  slashCommandMatches(text, options).map(match => `${match.kind}:${match.command}`)

describe('slashCommandMatches', () => {
  beforeEach(() => {
    rememberDesktopCommandsCatalog({
      commands: { '/goal': { argument_mode: 'mixed', desktop: null } }
    })
  })

  afterEach(() => {
    rememberDesktopCommandsCatalog(undefined)
  })

  it('recognizes a leading command and a skill named mid-prose', () => {
    expect(commands('/some-skill clean this with /other-skill please')).toEqual([
      'skill:/some-skill',
      'skill:/other-skill'
    ])
  })

  it('leaves a path alone — /usr/local/bin is not a command', () => {
    expect(commands('see /usr/local/bin ')).toEqual([])
  })

  it('holds a trailing token as still-typed unless the text is inert', () => {
    expect(commands('/some-skill')).toEqual([])
    expect(commands('/some-skill', { trailingCommitted: true })).toEqual(['skill:/some-skill'])
  })

  it('leaves an arg-taking command as text — its tail may be prose', () => {
    expect(commands('/goal ship the redesign')).toEqual([])
  })

  it('leaves a command with no desktop surface as text', () => {
    expect(commands('/exit now')).toEqual([])
  })

  it('offers a built-in only as an invocation, never mid-message', () => {
    // Mirrors what the popover offers: `/new` acts on the app, so it means
    // nothing dropped into a sentence, while a skill reads as "handle this
    // part with X".
    expect(commands('/new ')).toEqual(['command:/new'])
    expect(commands('start over with /new ')).toEqual([])
    expect(commands('start over with /some-skill ')).toEqual(['skill:/some-skill'])
  })

  it('disqualifies a leading token when the text lands mid-word', () => {
    expect(commands('/some-skill ', { boundaryBefore: false })).toEqual([])
  })
})

describe('slashCommandMatches — argument mode the catalog has not named yet', () => {
  afterEach(() => {
    rememberDesktopCommandsCatalog(undefined)
  })

  it('leaves a command as text while the mode is unknown', () => {
    // Reported repro: on a fresh mount, before `commands.catalog` answers,
    // `/plan ` and `/new ` hydrated as pills and turned back into prose the
    // moment the catalog landed. The mode is a property of the command, not of
    // when the catalog happened to arrive, so an unknown mode chips nothing.
    rememberDesktopCommandsCatalog(undefined)

    expect(commands('/plan ')).toEqual([])
    expect(commands('/new ')).toEqual([])
  })

  it('chips the same command once the catalog calls it argument-less', () => {
    rememberDesktopCommandsCatalog({ commands: { '/new': { argument_mode: null, desktop: null } } })

    expect(commands('/new ')).toEqual(['command:/new'])
  })

  it('keeps a text command as text with the catalog loaded', () => {
    rememberDesktopCommandsCatalog({ commands: { '/plan': { argument_mode: 'text', desktop: null } } })

    expect(commands('/plan ')).toEqual([])
  })
})
