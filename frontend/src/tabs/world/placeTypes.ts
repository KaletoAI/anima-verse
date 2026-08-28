/**
 * placeTypes — the pose catalog's PLACE TYPES as the world editors see them
 * (plan-posen-plaetze.md § 4). A room marker or a prop marker names a place
 * type (`group`: seat, bed, floor, …), never a clip; which pose plays there
 * is the character's business. The editors need three things of the
 * catalog, and they need them alike: the group vocabulary for the picker
 * (label shown, key stored), the poses of a group for the preview cycler
 * (the group's DEFAULT first, then alphabetical — the same order the server's
 * `poses_in_group` yields) and a stable id for a new marker.
 *
 * Shared by RoomLayoutEditor, PlanSidePanel, FloorPlanPreview, FurnishDialog
 * and the prop detail — nothing here decides geometry.
 */
import { useEffect, useState } from 'react'
import { apiGet } from '../../lib/api'

export interface PoseGroupSpec {
  label: string
  /** Root drop as a fraction of the figure height (the SERVER composes it
   *  into the payload's `root_offset`; the client never recomputes it). */
  root_drop?: number
  /** The pose a click on such a marker sets — first in the cycler. */
  default?: string
}

export interface PoseEntryLite {
  key: string
  group?: string
  /** Animation-clip kind the pose plays. */
  animation?: string
  solo?: boolean
  /** Marker slots a PAIR pose consumes (1 or 2). */
  places?: number
  /** Degrees the pair clip's frame turns against the marker facing. */
  yaw_offset?: number
}

export interface PoseCatalog {
  status: 'loading' | 'ready' | 'missing'
  entries: PoseEntryLite[]
  groups: Record<string, PoseGroupSpec>
}

const EMPTY_CATALOG: PoseCatalog = { status: 'loading', entries: [], groups: {} }

/** `GET /poses?axis=pose`, fetched once per mount. Until it is in, `status`
 *  is 'loading' and both maps are empty; a failed fetch ends in 'missing'. */
export function usePoseCatalog(): PoseCatalog {
  const [catalog, setCatalog] = useState<PoseCatalog>(EMPTY_CATALOG)
  useEffect(() => {
    let alive = true
    apiGet<{ entries?: PoseEntryLite[]; groups?: Record<string, PoseGroupSpec> }>('/poses?axis=pose')
      .then((d) => {
        if (!alive) return
        setCatalog({ status: 'ready', entries: d.entries || [], groups: d.groups || {} })
      })
      .catch(() => { if (alive) setCatalog({ status: 'missing', entries: [], groups: {} }) })
    return () => { alive = false }
  }, [])
  return catalog
}

/** Stable marker id — 8 base32 characters (a-z, 2-7), the same alphabet the
 *  server mints with; it keeps a client-sent id verbatim. */
export function newId(): string {
  const alphabet = 'abcdefghijklmnopqrstuvwxyz234567'
  return Array.from({ length: 8 }, () => alphabet[Math.floor(Math.random() * 32)]).join('')
}

/** Human label of a place type — the key itself when the catalog does not
 *  (yet) know it. */
export function groupLabel(groups: Record<string, PoseGroupSpec>, group: string): string {
  return groups[group]?.label || group
}

/** Group keys in picker order: by label, case-insensitively. */
export function groupKeys(groups: Record<string, PoseGroupSpec>): string[] {
  return Object.keys(groups).sort((a, b) =>
    groupLabel(groups, a).localeCompare(groupLabel(groups, b), undefined, { sensitivity: 'base' }))
}

/** The pose keys of a place type: the group's default first, then the rest
 *  alphabetically — the server's `poses_in_group` order. */
export function posesInGroup(catalog: PoseCatalog, group: string): string[] {
  const def = catalog.groups[group]?.default || ''
  const keys = catalog.entries
    .filter((e) => (e.group || '') === group && e.key !== def)
    .map((e) => e.key)
    .sort()
  return def && catalog.entries.some((e) => e.key === def) ? [def, ...keys] : keys
}

/** The pose a marker's preview figure plays: the cycled one when it names a
 *  pose of the marker's own group, else the group's default. `undefined`
 *  while the catalog loads or for a group it does not know. */
export function previewEntry(catalog: PoseCatalog, group: string,
                             cycled?: string): PoseEntryLite | undefined {
  const byKey = (key?: string) => (key
    ? catalog.entries.find((e) => e.key === key && (e.group || '') === group)
    : undefined)
  return byKey(cycled) || byKey(catalog.groups[group]?.default)
}
