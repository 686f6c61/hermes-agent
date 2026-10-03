import { describe, expect, it } from 'vitest'

import { isArtifactFilePath } from './media'

// #131842: artifact discovery and the Artifacts drawer must recognize bare
// relative file paths (`docs/report.md`), not only absolute / file:// / ~ /
// drive-letter shapes. A slash and a terminating extension are required so
// domains, URL slugs and directories never masquerade as artifacts.
describe('isArtifactFilePath', () => {
  it('accepts the established absolute and dotted-relative shapes', () => {
    expect(isArtifactFilePath('/home/user/report.md')).toBe(true)
    expect(isArtifactFilePath('~/notes/todo.md')).toBe(true)
    expect(isArtifactFilePath('file:///srv/data/notes.txt')).toBe(true)
    expect(isArtifactFilePath('C:\\Users\\me\\doc.pdf')).toBe(true)
    expect(isArtifactFilePath('\\\\server\\share\\f.txt')).toBe(true)
    expect(isArtifactFilePath('./docs/summary.md')).toBe(true)
    expect(isArtifactFilePath('../README.md')).toBe(true)
  })

  it('accepts bare relative paths that carry a slash and an extension', () => {
    expect(isArtifactFilePath('docs/report.md')).toBe(true)
    expect(isArtifactFilePath('docs/deep/nested/summary.md')).toBe(true)
    expect(isArtifactFilePath('docs/image.PNG')).toBe(true)
  })

  it('rejects domains, slugs, directories and scheme-ful URLs', () => {
    expect(isArtifactFilePath('example.com')).toBe(false)
    expect(isArtifactFilePath('example.com/page')).toBe(false)
    expect(isArtifactFilePath('docs/')).toBe(false)
    expect(isArtifactFilePath('report.md')).toBe(false)
    expect(isArtifactFilePath('docs/guide')).toBe(false)
    expect(isArtifactFilePath('https://example.com/a.md')).toBe(false)
  })
})
