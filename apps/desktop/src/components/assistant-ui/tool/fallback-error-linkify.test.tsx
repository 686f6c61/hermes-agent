import { cleanup, fireEvent, render } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@assistant-ui/react', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useAuiState: (select: (state: unknown) => unknown) =>
    select({ message: { id: 'msg-1', status: { type: 'complete' } }, thread: { isRunning: false } })
}))

const { ToolFallback } = await import('./fallback')

const desktopWindow = window as unknown as { hermesDesktop?: Window['hermesDesktop'] }
const PATH = 'C:\\Users\\me\\projects\\myrepo\\README.md'

function installTitleBridge(title: string) {
  desktopWindow.hermesDesktop = {
    fetchLinkTitle: vi.fn().mockResolvedValue(title),
    openExternal: vi.fn().mockResolvedValue(undefined)
  } as unknown as Window['hermesDesktop']
}

/** A failed write_file row, expanded, whose error summary carries a Windows path. */
let callSeq = 0

function renderErrorRow(error: string) {
  callSeq += 1

  const props = {
    args: { content: 'hello', path: PATH },
    isError: true,
    result: { error, ok: false },
    toolCallId: `call-${callSeq}`,
    toolName: 'write_file'
  } as unknown as ComponentProps<typeof ToolFallback>

  const { container } = render(<ToolFallback {...props} />)
  const toggle = container.querySelector('button[aria-expanded]')

  if (toggle) {
    fireEvent.click(toggle)
  }

  return container
}

function hrefs(container: HTMLElement): string[] {
  return [...container.querySelectorAll('a')].map(anchor => anchor.getAttribute('href') ?? '')
}

afterEach(() => {
  cleanup()
})

describe('tool error summary linkification', () => {
  // `readme.md` is a live domain (Moldova) that redirects to an unrelated site, so
  // the bare-domain branch of URL_RE turned a copied path into a link and `pretty`
  // replaced the visible text with that page's title.
  it('keeps a bare filename in an error summary as written', () => {
    installTitleBridge('AI Tools Directory - dealsbe.com')

    const container = renderErrorRow(`Refusing to overwrite unread file ${PATH}: the file was NOT modified.`)

    expect(container.textContent).toContain(PATH)
    expect(hrefs(container).some(href => /readme\.md/i.test(href))).toBe(false)
  })

  it('still links an explicit URL in the same error summary', () => {
    installTitleBridge('Upgrade guide')

    const container = renderErrorRow(
      `Refusing to overwrite unread file ${PATH}; see https://example.com/upgrade-guide`
    )

    expect(hrefs(container)).toContain('https://example.com/upgrade-guide')
  })
})
