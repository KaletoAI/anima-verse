/**
 * Shared types + vocabulary of the prop library (plan-room-props.md).
 * Split out of PropsTab so the container, the create form and the detail
 * panel all read from one place.
 */

export interface PropMarker {
  animation: string
  /** Object-local position: fractions [X, Y, Z] of the RAW model bounding
   *  box. Range -0.5..1.5 — seats and lying surfaces sit on the hull or
   *  just outside it (mirrors props.MARKER_AT_MIN/MAX). */
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
  /** How much of its ground's wind this prop takes part in (0..1) — the
   *  multiplier on the terrain kind's sway when the prop is scattered over a
   *  painted area. Always the EFFECTIVE value on a full record (1 = the full
   *  amount); the server stores it only when it differs. */
  sway_factor?: number
  /** Generation subject — feeds the render prompt; the name stays free
   *  display text (empty = the name is used). */
  description?: string
  /** AABB edge lengths of the mesh on its RAW axes (before the fix) — the
   *  proportions the dims are derived from. Absent = no measurable model. */
  bbox?: [number, number, number]
  /** True = placeholder cube, not informed by the model's proportions yet. */
  dims_estimated?: boolean
  /** What Blender read out of the mesh — informational, nothing is derived
   *  from it (the dims come from `bbox`). Absent until measured. */
  measured?: { tris?: number; verts?: number; uv_layers?: number; vertex_colors?: number }
  rotation?: { x?: number; y?: number; z?: number }
  markers?: PropMarker[]
  has_source?: boolean
  created_at?: string
  source?: string
  backend?: string
  /** Image backend the CURRENT source image was rendered on. */
  backend_image?: string
  /** Final prompt / negative of the current source image (provenance). */
  prompt?: string
  negative?: string
  /** When the current source image was rendered (UTC ISO). */
  source_generated_at?: string
  model_url?: string
  source_url?: string
  /** Every ACTIVE model variant that HAS a mesh, in payload order — element 0
   *  is the primary variant, so its `tiers` is what an unqualified `/model`
   *  request serves. `variant` is the STORE INDEX, not the position in this
   *  list: a switched-off variant leaves a gap. Anything that addresses a
   *  variant over the API uses that number, never the array position. */
  variant_tiers?: Array<{ variant: number; tiers: string[] }>
  /** How many active variants actually carry a mesh. */
  variant_count?: number
  /** Configured ceiling on ACTIVE variants (image_generation.prop_variant_max). */
  variant_max?: number
}

/**
 * One model variant of a prop (`GET /world/props/{id}/variants`).
 *
 * A prop carries an ORDERED list of variants — several meshes of the SAME
 * object, so a scattered wood is not one tree twenty times. Each variant is a
 * whole mesh gallery of its own (own `full`/`low` tiers, own history). The
 * FIRST ACTIVE one is the PRIMARY variant: it is what `/assets/props/{id}/model`
 * serves without a `variant` parameter, i.e. what every consumer that knows
 * nothing about variants keeps getting.
 */
/**
 * What ONE variant's source image was made with — the provenance the image
 * panel shows beside the picture it is displaying.
 *
 * The image belongs to the VARIANT, not to the prop: a variant is a whole
 * version of the object, and its mesh was made from THIS picture (variant 0
 * keeps the historic `source.png`, every further one gets `source-v<n>.png`).
 */
export interface PropSourceImage {
  /** Image backend it was rendered on ('' = uploaded / no record). */
  backend: string
  prompt: string
  negative: string
  /** UTC ISO stamp of the render or upload ('' = no record). */
  generated_at: string
}

export interface PropVariant {
  index: number
  /** File stem this variant's meshes are stored under (informational). */
  stem: string
  /** Switched off variants keep their meshes but are not rendered. */
  active: boolean
  primary: boolean
  /** Resolution tiers this variant HAS (`full` / `low`). */
  tiers: string[]
  has_model: boolean
  model_file: string
  /** Canonical serving URL WITH its `variant` parameter ('' = no mesh yet). */
  model_url: string
  signature: string
  /** This variant HAS a source image of its own (see PropSourceImage). */
  has_source: boolean
  /** Its serving URL, `variant` parameter included ('' = no image yet). */
  source_url: string
  /** What that image was rendered/uploaded with. */
  image: PropSourceImage
}

export interface ImageBackendInfo {
  name: string
  prompt_style: string
  prompt_negative: string
  /** false = this backend has no negative input (distilled / guidance-free
   *  model); the server folds the negations into the prompt, so the forms
   *  hide the negative field. Resolved server-side from auto/yes/no. */
  supports_negative_prompt?: boolean
}

export interface MeshBackendInfo {
  name: string
  face_num?: number | null
  /** Hard ceiling of the face count (0/absent = none). */
  face_num_max?: number | null
  /** Alias can bake reduced LOD stages in the same job (from its schema). */
  lod_stages?: boolean
}

// Categories are an open vocabulary (free text): the shared datalist offers
// the categories the EXISTING props use, nothing is predefined. The client's
// category→animation mapping (AV3D-6) still keys on names like chair/bed —
// but that is a consumer convention, not an input restriction.

/** id of the shared category <datalist> — rendered once by PropsTab. */
export const CATEGORY_DATALIST_ID = 'prop-category-options'
