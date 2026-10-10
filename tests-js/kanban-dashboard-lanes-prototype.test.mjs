/**
 * Invariant of the kanban dashboard lane grouping.
 *
 * The dashboard groups the running column's tasks per assignee into a plain
 * object literal. An assignee named like an inherited Object.prototype key
 * ("constructor" is a common role name on agent orchestration boards;
 * "toString", "hasOwnProperty" work too) resolves to the inherited value,
 * which is truthy: the `|| []` never installs a real array and the grouping
 * `.push` throws, corrupting the lane render for that profile.
 *
 * The bundle is hand-maintained source (its header says "Plain IIFE, no
 * build step"), so this test extracts the real `lanes` grouping block from
 * plugins/kanban/dashboard/dist/index.js and pins its behavior for
 * prototype-key assignees instead of re-implementing it here.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { test } from 'vitest'

const BUNDLE = fileURLToPath(
  new URL('../plugins/kanban/dashboard/dist/index.js', import.meta.url)
)

function loadLanesGrouping() {
  const src = readFileSync(BUNDLE, 'utf8')
  const match = src.match(
    /const lanes = (useMemo\(function \(\) \{[\s\S]*?\n    \}, \[props\.column, props\.laneByProfile\]\));/
  )
  if (!match) {
    throw new Error(
      'lanes grouping block not found in plugins/kanban/dashboard/dist/index.js; the bundle changed shape, update this extractor'
    )
  }
  return new Function('useMemo', 'props', 'return ' + match[1])
}

test('dashboard lane grouping survives assignees named like Object prototype keys', () => {
  const lanesOf = loadLanesGrouping()
  const tasks = [
    { id: 't1', assignee: 'constructor' },
    { id: 't2', assignee: 'constructor' },
    { id: 't3', assignee: 'reviewer' },
    { id: 't4', assignee: '' }
  ]
  const lanes = lanesOf(fn => fn(), {
    laneByProfile: true,
    column: { name: 'running', tasks }
  })
  assert.deepEqual(lanes, [
    { assignee: '(unassigned)', tasks: [tasks[3]] },
    { assignee: 'constructor', tasks: [tasks[0], tasks[1]] },
    { assignee: 'reviewer', tasks: [tasks[2]] }
  ])
})
