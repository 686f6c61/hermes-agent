/**
 * Boundary helpers between profile switching and the projects cache.
 *
 * Kept in its own module so `profile.ts` can clear project state without a
 * circular import through `projects.ts` (which already imports profile).
 */

import {
  $activeProjectId,
  $projects,
  $projectTree,
  exitProjectScope
} from '@/store/projects'

/** Drop the previous profile's projects.db snapshot on profile switch (#79406). */
export function clearProjectsCacheForProfileSwitch(): void {
  $projects.set([])
  $projectTree.set([])
  $activeProjectId.set(null)
  exitProjectScope()
}
