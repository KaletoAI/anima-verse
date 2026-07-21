/**
 * Shared types + vocabulary of the prop library (plan-room-props.md).
 * Split out of PropsTab so the container, the create form and the detail
 * panel all read from one place.
 */

export interface PropMarker {
  animation: string
  /** Object-local position: fractions of the model bounding box (0..1). */
  at: [number, number, number]
  /** Facing in degrees (0 south / 90 east / 180 north / 270 west). */
  facing?: number
}

export interface PropFull {
  id: string
  name: string
  category: string
  /** Real extent in metres AFTER the orientation fix (x/y/z). */
  width_m: number
  depth_m: number
  height_m: number
  tags: string[]
  marker_count: number
  has_model: boolean
  /** AABB edge lengths of the mesh on its RAW axes (before the fix) — the
   *  proportions the dims are derived from. Absent = no measurable model. */
  bbox?: [number, number, number]
  /** True = placeholder cube, not informed by the model's proportions yet. */
  dims_estimated?: boolean
  rotation?: { x?: number; y?: number; z?: number }
  markers?: PropMarker[]
  has_source?: boolean
  created_at?: string
  source?: string
  backend?: string
  prompt?: string
  model_url?: string
  source_url?: string
}

export interface ImageBackendInfo {
  name: string
  prompt_style: string
  prompt_negative: string
}

export interface MeshBackendInfo {
  name: string
  face_num?: number | null
}

// Suggested categories (open vocabulary — free text via datalist). The base
// ones (chair/bed/bench/…) are what the client's category→animation mapping
// keys on (AV3D-6); everything else is decoration.
export const CATEGORY_SUGGESTIONS = [
  'chair', 'table', 'bed', 'sofa', 'bench', 'stool', 'shelf', 'cabinet',
  'desk', 'lamp', 'plant', 'rug', 'decoration', 'appliance', 'misc',
]

/** id of the shared category <datalist> — rendered once by PropsTab. */
export const CATEGORY_DATALIST_ID = 'prop-category-options'
