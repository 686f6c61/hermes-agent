import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CatalogCard, type CatalogCardVariant } from './catalog-card'
import type { CatalogEntry } from './catalog-data'

const entry: CatalogEntry = {
  id: 'web',
  name: 'Web Search',
  description: 'Search the web',
  overview: 'Search the web',
  category: 'tools',
  categoryLabel: 'Tools',
  source: 'official',
  author: 'official',
  identifier: 'official/web',
  repo: 'https://github.com/example/web',
  sha: '',
  subdir: '',
  version: '1.0.0',
  requiresHermes: '',
  tags: [],
  platforms: [],
  requirements: [],
  tools: [],
  hooks: [],
  sourceUrl: null,
  docsUrl: null,
  imageUrl: null,
  stars: null,
  search: ''
}

/** The stacking level a class list asks for: `z-10` → 10, no `z-*` → auto (`null`). */
const stackingLevel = (className: string) => {
  const match = className.match(/(?:^|\s)z-(\d+)(?:\s|$)/)

  return match ? Number(match[1]) : null
}

const noop = () => {}

function renderCard(variant: CatalogCardVariant) {
  render(
    <CatalogCard
      accentIndex={0}
      action={<button type="button">Turn off</button>}
      entry={entry}
      onCategory={vi.fn()}
      onOpen={noop}
      onSearch={vi.fn()}
      onTag={vi.fn()}
      variant={variant}
    />
  )

  return {
    action: screen.getByRole('button', { name: 'Turn off' }),
    titleButton: screen.getByRole('button', { name: entry.name })
  }
}

afterEach(cleanup)

describe('CatalogCard action hit testing', () => {
  // The title button's ::after is `inset: 0` and positions against the card (the
  // button itself is static), so it covers the whole card — including a top-line
  // rendered before it in DOM order, which is where the compact and horizontal
  // variants put their action. jsdom has no layout and no hit testing, so a click
  // here cannot reproduce the defect (#143090: the click opened the detail dialog
  // instead of toggling the toolset). What these cases pin is the mechanism the
  // browser relies on: the overlay spans the card, and an action that precedes it
  // must ask for a stacking level above it.
  it.each(['compact', 'horizontal'] as CatalogCardVariant[])(
    'keeps the %s top-line action above the card-wide click overlay',
    variant => {
      const { action, titleButton } = renderCard(variant)

      expect(titleButton.className).toContain('after:inset-0')

      const wrapper = action.parentElement!
      expect(wrapper.parentElement?.className).toContain('catalog-card-topline')
      expect(stackingLevel(wrapper.className) ?? 0).toBeGreaterThan(0)
    }
  )

  // The default variant renders its action after the title button, so it paints
  // over the overlay by DOM order and needs no stacking level — which is why the
  // Plugins tab was never affected.
  it('leaves the default action after the title button, where the overlay paints under it', () => {
    const { action, titleButton } = renderCard('default')

    expect(titleButton.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(stackingLevel(action.parentElement!.className)).toBeNull()
  })
})
