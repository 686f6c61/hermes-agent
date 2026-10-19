import DOMPurify from 'dompurify'

import { isDesktopFsRemoteMode, readDesktopFileDataUrl, readDesktopFileText } from '@/lib/desktop-fs'
import { isWindowsAbsolutePath } from '@/lib/path-compare'
import type { PreviewTarget } from '@/store/preview'

const HTML_EXTENSIONS = new Set(['.htm', '.html'])
const IMAGE_EXTENSIONS = new Set(['.bmp', '.gif', '.jpeg', '.jpg', '.png', '.svg', '.webp'])
const PDF_EXTENSIONS = new Set(['.pdf'])
// Mirrors `_FS_DATA_URL_MAX_BYTES` in the backend filesystem endpoint.
const REMOTE_HTML_PREVIEW_MAX_BYTES = 16 * 1024 * 1024
const REMOTE_HTML_PREVIEW_MAX_BASE64_BYTES = Math.ceil(REMOTE_HTML_PREVIEW_MAX_BYTES / 3) * 4

const LANGUAGE_BY_EXT: Record<string, string> = {
  '.c': 'c',
  '.conf': 'ini',
  '.cpp': 'cpp',
  '.css': 'css',
  '.csv': 'csv',
  '.go': 'go',
  '.graphql': 'graphql',
  '.h': 'c',
  '.hpp': 'cpp',
  '.html': 'html',
  '.java': 'java',
  '.js': 'javascript',
  '.json': 'json',
  '.jsx': 'jsx',
  '.log': 'text',
  '.lua': 'lua',
  '.md': 'markdown',
  '.mjs': 'javascript',
  '.py': 'python',
  '.rb': 'ruby',
  '.rs': 'rust',
  '.sh': 'shell',
  '.sql': 'sql',
  '.svg': 'xml',
  '.toml': 'toml',
  '.ts': 'typescript',
  '.tsx': 'tsx',
  '.txt': 'text',
  '.xml': 'xml',
  '.yaml': 'yaml',
  '.yml': 'yaml',
  '.zsh': 'shell'
}

function basename(value: string) {
  return value.split(/[\\/]/).filter(Boolean).pop() || value
}

function extension(value: string) {
  const clean = value.split(/[?#]/, 1)[0] || value
  const idx = clean.lastIndexOf('.')

  return idx >= 0 ? clean.slice(idx).toLowerCase() : ''
}

// Collapses `.`/`..` so a note's `../other.md` lands on the sibling, not on a
// path the fs bridge rejects. Never climbs above the root of `base`.
function joinPath(base: string, rel: string) {
  if (!base) {
    return rel
  }

  const normalizedBase = base.replace(/\\/g, '/')
  const root = normalizedBase.match(/^(?:\/\/|(?:[A-Za-z]:)?\/)/)?.[0] ?? ''
  const parts = normalizedBase.slice(root.length).split('/').filter(Boolean)

  for (const part of rel.replace(/\\/g, '/').split('/')) {
    if (!part || part === '.') {
      continue
    }

    if (part === '..') {
      parts.pop()

      continue
    }

    parts.push(part)
  }

  return `${root}${parts.join('/')}`
}

function pathToFileUrl(path: string) {
  const isWindowsUnc = path.startsWith('\\\\')
  const normalized = isWindowsUnc || /^[a-z]:[\\/]/i.test(path) ? path.replace(/\\/g, '/') : path

  const encoded = normalized
    .split('/')
    .map(part => encodeURIComponent(part))
    .join('/')

  if (isWindowsUnc) {
    return `file://${encoded.slice(2)}`
  }

  return `file://${encoded.startsWith('/') ? encoded : `/${encoded}`}`
}

/** Loopback hosts — "this machine". The one address family an agent's dev
 *  server lives on, and the one whose meaning changes with WHICH machine loads
 *  it (a remote gateway's `localhost` is not ours). */
const LOOPBACK_HOST_RE = /^(localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|::1)$/

export function isLoopbackPreviewUrl(value: string): boolean {
  try {
    const url = new URL(value)

    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      return false
    }

    return LOOPBACK_HOST_RE.test(
      url.hostname
        .toLowerCase()
        .replace(/^\[|\]$/g, '')
        .replace(/\.$/, '')
    )
  } catch {
    return false
  }
}

export function validatedRemoteHtmlDataUrl(value: string): string | null {
  const prefix = 'data:text/html;base64,'

  if (!value.startsWith(prefix)) {
    return null
  }

  const payload = value.slice(prefix.length)

  if (payload.length > REMOTE_HTML_PREVIEW_MAX_BASE64_BYTES || payload.length % 4 !== 0) {
    return null
  }

  try {
    const decoded = atob(payload)

    return decoded.length <= REMOTE_HTML_PREVIEW_MAX_BYTES && btoa(decoded) === payload ? value : null
  } catch {
    return null
  }
}

export function remoteHtmlPreviewDocument(dataUrl: string): string | null {
  const validated = validatedRemoteHtmlDataUrl(dataUrl)

  if (!validated) {
    return null
  }

  const csp = `default-src 'none'; base-uri 'none'; form-action 'none'; img-src data:; media-src data:; font-src data:; style-src 'unsafe-inline'`

  const html = new TextDecoder().decode(
    Uint8Array.from(atob(validated.slice(validated.indexOf(',') + 1)), char => char.charCodeAt(0))
  )

  const document = new DOMParser().parseFromString(
    DOMPurify.sanitize(html, {
      WHOLE_DOCUMENT: true,
      FORBID_TAGS: ['script', 'template', 'iframe', 'frame', 'object', 'embed'],
      FORBID_ATTR: ['href', 'xlink:href', 'action', 'formaction', 'target']
    }),
    'text/html'
  )

  document.querySelectorAll('meta[http-equiv]').forEach(element => {
    if (element.getAttribute('http-equiv')?.toLowerCase() === 'refresh') {
      element.remove()
    }
  })
  document.querySelectorAll('*').forEach(element => {
    for (const attribute of Array.from(element.attributes)) {
      if (attribute.localName === 'href' || attribute.localName === 'ping') {
        element.removeAttributeNode(attribute)
      }
    }
  })
  const policy = document.createElement('meta')
  policy.httpEquiv = 'Content-Security-Policy'
  policy.content = csp
  document.head.prepend(policy)

  return `<!doctype html>${document.documentElement.outerHTML}`
}

export async function openPreviewTargetInBrowser(target: PreviewTarget): Promise<void> {
  const bridge = window.hermesDesktop

  if (!bridge?.openPreviewInBrowser) {
    throw new Error('Desktop preview browser bridge is unavailable')
  }

  const dataUrl = target.dataUrl && validatedRemoteHtmlDataUrl(target.dataUrl)

  if (!dataUrl) {
    if (target.transient) {
      throw new Error('Remote HTML preview could not be loaded')
    }

    await bridge.openPreviewInBrowser(target.url)

    return
  }

  if (!bridge.saveImageBuffer) {
    throw new Error('Desktop preview buffer bridge is unavailable')
  }

  const decoded = atob(dataUrl.slice(dataUrl.indexOf(',') + 1))
  const bytes = Uint8Array.from(decoded, char => char.charCodeAt(0))
  const filePath = await bridge.saveImageBuffer(bytes, '.html')

  if (!filePath) {
    throw new Error('Could not stage remote HTML preview')
  }

  await bridge.openPreviewInBrowser(pathToFileUrl(filePath))
}

/** A file-viewer fragment: `page=8`, `page=8&zoom=100`, `zoom=100,50,200`,
 *  `nameddest=chapter`. Only that shape is split off the target, because `#` is
 *  also a legal character in a POSIX file name (`//srv/share/report #1?.html`,
 *  covered by `preserves POSIX double-slash file paths`), and a bare
 *  `#section` is a document anchor with no file target at all. */
const VIEWER_FRAGMENT_RE = /^[A-Za-z][\w.-]*=[^#\s]*$/

/** Split a link target into the path and the URL fragment that follows it.
 *
 *  A Markdown link can name a position INSIDE the file it opens:
 *  `[spec](../pdfs/1.pdf#page=8)`. The `#…` part is a fragment, never part of
 *  the name, so resolving the whole string as a path looks for a file called
 *  `1.pdf#page=8` and reports it as missing (#141766). */
export function splitPreviewFragment(raw: string): { fragment?: string; target: string } {
  const hash = raw.lastIndexOf('#')

  if (hash <= 0) {
    return { target: raw }
  }

  const fragment = raw.slice(hash + 1)

  return VIEWER_FRAGMENT_RE.test(fragment) ? { fragment, target: raw.slice(0, hash) } : { target: raw }
}

export function localPreviewTarget(rawTarget: string, cwd?: string | null): PreviewTarget | null {
  const raw = rawTarget.trim().replace(/^`|`$/g, '')

  if (!raw) {
    return null
  }

  if (/^https?:\/\//i.test(raw)) {
    return { kind: 'url', label: basename(raw), source: raw, url: raw }
  }

  const { fragment, target: targetPath } = splitPreviewFragment(raw)
  let path = targetPath

  if (/^file:\/\//i.test(targetPath)) {
    try {
      path = decodeURIComponent(new URL(targetPath).pathname)
    } catch {
      path = targetPath.replace(/^file:\/\//i, '')
    }
  } else if (!targetPath.startsWith('/') && !isWindowsAbsolutePath(targetPath) && cwd) {
    path = joinPath(cwd, targetPath)
  }

  const ext = extension(path)
  const isHtml = HTML_EXTENSIONS.has(ext)
  const isImage = IMAGE_EXTENSIONS.has(ext)
  const isPdf = PDF_EXTENSIONS.has(ext)

  return {
    kind: 'file',
    label: basename(path),
    language: LANGUAGE_BY_EXT[ext] || 'text',
    path,
    // Renderer fallback can't stat/sniff without reading; assume text unless
    // image/html/pdf extension says otherwise. LocalFilePreview still guards
    // binary/large files when readFileText/readFileDataUrl returns metadata.
    previewKind: isHtml ? 'html' : isImage ? 'image' : isPdf ? 'pdf' : 'text',
    source: raw,
    ...(fragment ? { fragment } : {}),
    url: pathToFileUrl(path)
  }
}

async function enrichPreviewTarget(target: PreviewTarget | null): Promise<PreviewTarget | null> {
  if (
    !isDesktopFsRemoteMode() ||
    !target ||
    target.kind !== 'file' ||
    target.previewKind === 'image' ||
    target.previewKind === 'pdf'
  ) {
    return target
  }

  if (target.previewKind === 'html') {
    try {
      const dataUrl = validatedRemoteHtmlDataUrl(await readDesktopFileDataUrl(target.path || target.source))

      return dataUrl ? { ...target, dataUrl } : { ...target, renderMode: 'source', transient: true }
    } catch {
      return { ...target, renderMode: 'source', transient: true }
    }
  }

  try {
    const result = await readDesktopFileText(target.path || target.source)

    return {
      ...target,
      binary: result.binary,
      byteSize: result.byteSize,
      language: result.language || target.language,
      large: (result.byteSize ?? 0) > 512 * 1024,
      mimeType: result.mimeType
    }
  } catch {
    return target
  }
}

export async function normalizeOrLocalPreviewTarget(
  rawTarget: string,
  cwd?: string | null
): Promise<PreviewTarget | null> {
  // The fragment names a position inside the file, so main-process resolution
  // gets the path alone — it would otherwise look for `1.pdf#page=8` on disk
  // (#141766) — and the reply carries it back to the viewer.
  const { fragment, target } = splitPreviewFragment(rawTarget.trim())
  const resolved = await resolvePreviewTarget(target, rawTarget, cwd)

  return fragment && resolved ? { ...resolved, fragment } : resolved
}

async function resolvePreviewTarget(
  target: string,
  rawTarget: string,
  cwd?: string | null
): Promise<PreviewTarget | null> {
  try {
    const normalized = await window.hermesDesktop?.normalizePreviewTarget?.(target, cwd || undefined)

    if (normalized) {
      // Directories and dead links arrive as typed non-previewable results
      // (#101683). Locally they must not fall through to the renderer's blind
      // classification below, which would fabricate a text tab for a path
      // that cannot be previewed. A remote backend's paths are not on this
      // machine, so remote mode keeps the fabricated fallback the gateway
      // read resolves later.
      if (normalized.previewKind === 'directory' || normalized.previewKind === 'missing') {
        return isDesktopFsRemoteMode() ? enrichPreviewTarget(localPreviewTarget(rawTarget, cwd)) : null
      }

      return enrichPreviewTarget(normalized)
    }

    // The main process resolved the target against the real filesystem and
    // found nothing openable (`null`); an absent bridge yields `undefined` from
    // the optional call above instead. In local mode the main process's answer
    // is authoritative — the fallback below can only fabricate a broken
    // preview tab (#101683). Remote-backend paths, and a dev server without
    // the bridge, keep it.
    if (!isDesktopFsRemoteMode() && normalized === null) {
      return null
    }
  } catch {
    // Running Electron may still have the old HTML-only preview IPC. Fall
    // through to renderer-side local classification so text/images still open.
  }

  return enrichPreviewTarget(localPreviewTarget(rawTarget, cwd))
}
