/**
 * Strip terminal bracketed-paste leaks and repeated artifact tails from composer
 * text before it is shown in the UI or sent to the gateway.
 *
 * Mirrors hermes_cli/input_sanitize.py (CLI/TUI gateway defensive path).
 */

const BRACKETED_PASTE_BOUNDARY_START = /(^|[\s\n>:\])])\[200~/g
const BRACKETED_PASTE_BOUNDARY_END = /\[201~(?=$|[\s\n<[():;.,!?])/g
const BRACKETED_PASTE_DEGRADED_START = /(^|[\s\n>:\])])00~/g
const BRACKETED_PASTE_DEGRADED_END = /01~(?=$|[\s\n<[():;.,!?])/g

// A clock-time range (`12:00~12:15`) reuses the shape of the degraded `00~` / `01~` markers, so its span is
// held back from the boundary substitutions and passed through verbatim. Any run of spaces or tabs may
// separate the two times.
const CLOCK_TIME_RANGE = /\d{1,2}:\d{2}~[ \t]*\d{1,2}:\d{2}/g

const DESKTOP_PASTE_ARTIFACT = '~[[e'

/** Stand-in for a held-back clock-time range; swapped back for the original span after the substitutions. */
const RANGE_PLACEHOLDER = '\u0000'

/** Strip leaked bracketed-paste wrapper markers from user-visible text. */
function stripLeakedMarkers(text: string): string {
  let cleaned = text
    // eslint-disable-next-line no-control-regex -- terminal data may contain control chars
    .replace(/\x1b\[200~/g, '')
    // eslint-disable-next-line no-control-regex -- terminal data may contain control chars
    .replace(/\x1b\[201~/g, '')
    .replace(/\^\[\[200~/g, '')
    .replace(/\^\[\[201~/g, '')

  cleaned = cleaned.replace(BRACKETED_PASTE_BOUNDARY_START, '$1')
  cleaned = cleaned.replace(BRACKETED_PASTE_BOUNDARY_END, '')
  cleaned = cleaned.replace(BRACKETED_PASTE_DEGRADED_START, '$1')
  cleaned = cleaned.replace(BRACKETED_PASTE_DEGRADED_END, '')

  return cleaned
}

/** Put the held-back range spans back in the order their placeholders appear. */
function restoreRanges(stripped: string, source: string, spans: Array<[number, number]>, placeholder: string): string {
  let out = ''
  const pending = [...spans]
  let index = 0

  while (index < stripped.length) {
    if (stripped[index] === placeholder) {
      let runEnd = index

      while (runEnd < stripped.length && stripped[runEnd] === placeholder) {
        runEnd += 1
      }

      let remaining = runEnd - index

      while (remaining > 0 && pending.length > 0) {
        const [start, stop] = pending[0]
        const length = stop - start

        if (length > remaining) {
          break
        }

        out += source.slice(start, stop)
        pending.shift()
        remaining -= length
      }

      index = runEnd
    } else {
      out += stripped[index]
      index += 1
    }
  }

  return out
}

/** Strip leaked bracketed-paste wrapper markers from user-visible text. */
export function stripLeakedBracketedPasteWrappers(text: string): string {
  if (!text) {
    return text
  }

  const spans: Array<[number, number]> = []

  for (const match of text.matchAll(CLOCK_TIME_RANGE)) {
    const start = match.index ?? 0

    spans.push([start, start + match[0].length])
  }

  if (spans.length === 0) {
    return stripLeakedMarkers(text)
  }

  // Hold each range back with a same-length placeholder instead of cutting the text into fragments: the
  // boundary patterns anchor on the neighbouring character, so a fragment that starts or ends where a range
  // does gains an artificial string boundary and eats a marker embedded in the original text
  // (`id01~12:00~12:15` keeps its `01~`, `12:00~12:15[200~tag` keeps its `[200~`).
  const placeholder = text.includes(RANGE_PLACEHOLDER) ? '\u0001' : RANGE_PLACEHOLDER
  let masked = ''
  let cursor = 0

  for (const [start, stop] of spans) {
    masked += text.slice(cursor, start) + placeholder.repeat(stop - start)
    cursor = stop
  }

  masked += text.slice(cursor)

  return restoreRanges(stripLeakedMarkers(masked), text, spans, placeholder)
}

/** Drop a trailing run of the desktop ~[[e corruption signature (#62557). */
export function collapseRepeatedInputArtifacts(text: string, minRepeats = 4): string {
  if (!text) {
    return text
  }

  const marker = DESKTOP_PASTE_ARTIFACT
  let index = text.length
  let repeatCount = 0

  while (index >= marker.length && text.slice(index - marker.length, index) === marker) {
    repeatCount += 1
    index -= marker.length
  }

  if (repeatCount < minRepeats) {
    return text
  }

  let start = index

  if (start >= 2 && text.slice(start - 2, start) === '[e') {
    start -= 2
  } else if (start >= 1 && text[start - 1] === '[') {
    start -= 1
  }

  return text.slice(0, start)
}

/** Normalize composer text before submit or draft persistence. */
export function sanitizeComposerInput(text: string): string {
  if (!text) {
    return text
  }

  return collapseRepeatedInputArtifacts(stripLeakedBracketedPasteWrappers(text))
}
