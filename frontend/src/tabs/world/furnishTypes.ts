/**
 * The room-furnishing job as the server speaks it (plan-furnish-v2.md § 4).
 *
 * ONE list carries the whole job: the NEED list. A need either names the
 * library piece that serves it (`prop_id`) or has to be built (`build`) — the
 * v1 split into "existing" and "new" is gone, and with it the question which
 * of the two lists a piece belonged to.
 *
 * The types live here rather than in `FurnishDialog.tsx` because the dialog,
 * its needs list, the description panel and the canvas all read them; a type
 * module keeps the component imports one-way.
 */
import type { MountKind } from '../props/propTypes'
import type { RoomPropPlacement } from './worldTypes'

/** State machine of one job (E6): the placement runs BEFORE the meshes, so a
 *  room is reviewable within minutes and fills itself in afterwards. */
export type FurnishState = 'selecting' | 'proposal_ready' | 'placing'
  | 'review_ready' | 'generating' | 'error'

/** The temporary prop id of a piece that still has to be built. The colon
 *  makes it unmintable as a real prop id, so a placeholder can never be
 *  mistaken for a library piece (server: `furnish_place.NEED_ID_PREFIX`). */
export const NEED_ID_PREFIX = 'need:'

/** ONE thing the room needs. `prop_id`/`build` are DERIVED server-side from
 *  the match — the dialog may propose a different `prop_id`, but never claims
 *  a piece is "already built". */
export interface FurnishNeed {
  key: string
  kind: string
  category?: string
  count: number
  mount: MountKind
  width_m: number
  depth_m: number
  height_m: number
  style?: string
  /** The generation subject of the piece — an isolated object, never a scene.
   *  Empty on a hand-added row; the dialog falls back to the kind on confirm,
   *  because the server drops a need without one. */
  description?: string
  /** The PLACE this piece offers: a place type of the pose catalog plus box
   *  fractions (never a clip, see `furnish_needs.valid_marker`). */
  marker?: { group: string; at: [number, number, number] } | null
  /** Fillable panels the render should carry (`picture`, `glass`). */
  key_areas?: string[]
  /** True = the room's own description names this object, so it is not a
   *  suggestion but a promise the room already made. */
  from_description?: boolean
  prop_id?: string | null
  build?: boolean
}

/** Floor/wall texture kinds proposed for a room that has none (E9). */
export interface FurnishSurfaces {
  floor?: string
  wall?: string
}

export interface FurnishProposal {
  needs: FurnishNeed[]
  surfaces?: FurnishSurfaces | null
  /** What stage 1 threw away, with the reason the dialog shows. */
  dropped?: Array<{ kind: string; reason: string }>
  exclude?: { prop_ids?: string[]; categories?: string[]; keywords?: string[] }
}

/** Placed/unplaced per mount group of the placement run. */
export interface FurnishPhaseCount {
  placed: number
  unplaced: number
}

export interface FurnishPlacements {
  /** Includes `on` children and `need:<key>` placeholder prop ids. */
  placed: RoomPropPlacement[]
  unplaced: Array<{ name: string; reason: string; pass?: string }>
  /** Set once `accept` has written the placements into the room. */
  accepted?: boolean
}

export interface FurnishStatus {
  room_id: string
  location_id: string
  state: FurnishState
  proposal?: FurnishProposal | null
  placements?: FurnishPlacements | null
  error?: string
  /** Meshes n/m — only after accept; 0/0 before (E6). */
  progress?: { done: number; total: number }
  phase_counts?: Record<string, FurnishPhaseCount>
  running?: boolean
  /** The job's state says "working" but no thread is — offer Continue. */
  stalled?: boolean
  updated_at?: string
}

export interface FurnishJob {
  status: FurnishStatus | null
  busy: boolean
  /** Pending placements while the job waits for review — FE state only, the
   *  ghost layer edits them and Accept sends them back. Their `at` is METRES
   *  from the room's min corner, exactly like a stored placement (contract v6
   *  Nr. 2; the solver emits metres since the server wave), so a ghost and the
   *  prop it becomes on Accept are drawn by the same arithmetic. */
  ghosts: RoomPropPlacement[]
  setGhosts: (next: RoomPropPlacement[]) => void
  refresh: () => Promise<void>
  act: (action: string, body?: unknown) => Promise<void>
}

/** One library prop as the dialog needs it: the match select shows name and
 *  size, the marker warning reads `marker_count`, the cube-dims hint reads
 *  `dims_estimated` (all from `GET /world/props`). */
export interface FurnishLibProp {
  id: string
  name: string
  category?: string
  mount?: string
  width_m?: number
  depth_m?: number
  height_m?: number
  has_model?: boolean
  dims_estimated?: boolean
  marker_count?: number
}

/** The mount groups of the needs list, in the order the solver works them —
 *  the heading says WHERE a piece goes, which is the one thing all needs in a
 *  group share. English sources; the list translates them. */
export const MOUNT_GROUPS: Array<{ mount: MountKind; label: string }> = [
  { mount: 'floor', label: 'Floor' },
  { mount: 'wall', label: 'Wall' },
  { mount: 'ceiling', label: 'Ceiling' },
  { mount: 'surface', label: 'On a surface' },
]

/** An unclassified library prop stands on the floor — the very assumption the
 *  server makes for it (`room_furnish._mount_of`). */
export function propMount(prop: FurnishLibProp | undefined): MountKind {
  const raw = (prop?.mount || '').trim()
  return (raw === 'wall' || raw === 'ceiling' || raw === 'surface')
    ? raw : 'floor'
}
