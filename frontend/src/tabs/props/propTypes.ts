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

/** What a texture slot can be filled WITH: a picture (a gallery image URL) or
 *  a look (glass, mirror, matte). Mirrors `props.SLOT_KINDS`. */
export type PropSlotKind = 'image' | 'material'

/**
 * ONE fillable surface of a prop's mesh — a picture frame, a screen, a window
 * pane. A slot IS a material of the model: the import reads a first draft off
 * the material names (`slot_<name>`, or one of picture / screen / sign /
 * glass — `props.detect_slots`), and the list is corrected here.
 */
export interface PropSlot {
  /** Lower-case, unique within the prop — it names the material. */
  name: string
  kind: PropSlotKind
}

/** Real extent in metres after the orientation fix. Owned by the VARIANT
 *  since 2026-08-25 and mandatory there — every variant answers with all
 *  three, because there is no prop-level size left to inherit. */
export interface PropDims {
  width_m: number
  depth_m: number
  height_m: number
}

/** State of the walkable-surface lattice baked out of a mesh
 *  (`model_surface.surface_status`): `baked` with its size, `stale` when the
 *  mesh or its orientation fix moved on, `missing` when none was ever baked. */
export interface SurfaceStatus {
  state: string
  cols?: number
  rows?: number
  step?: number
}

export interface PropFull {
  id: string
  name: string
  category: string
  /** Real extent in metres AFTER the orientation fix (x/y/z) — of the PRIMARY
   *  variant, which is what every read without a variant in hand answers
   *  (the library row, the plan's schematic footprint). Edited in the variant
   *  strip, never here. */
  width_m: number
  depth_m: number
  height_m: number
  tags: string[]
  /** The fillable surfaces of this prop's mesh — always present, `[]` = none.
   *  Edited here on the prop, because a slot is a material of the OBJECT. */
  slots?: PropSlot[]
  /** True = the list above is what the model's material names said (the badge
   *  "detected"); False = an admin authored it, and no import touches it
   *  again. Full records only. */
  slots_auto?: boolean
  /** How many markers the PRIMARY variant carries. */
  marker_count: number
  has_model: boolean
  /** How much of its ground's wind this prop takes part in (0..1) — the
   *  multiplier on the terrain kind's sway when the prop is scattered over a
   *  painted area. Always the EFFECTIVE value on a full record (1 = the full
   *  amount); the server stores it only when it differs. */
  sway_factor?: number
  /** How deep the PRIMARY variant stands in the ground, in metres (−5…+5).
   *  Owned by the variant since 2026-08-25 and edited in the strip; the
   *  record carries the primary one's value (0 = on the ground). */
  ground_offset_m?: number
  /** Generation subject of the PRIMARY variant — feeds the render prompt
   *  ('' = the prop's name is used). Edited in the variant strip. */
  description?: string
  /** AABB edge lengths of the mesh on its RAW axes (before the fix) — the
   *  proportions the dims are derived from. Absent = no measurable model. */
  bbox?: [number, number, number]
  /** Whether the PRIMARY variant's mesh has a walkable surface baked — what
   *  the model panel's status line reads. */
  surface_status?: SurfaceStatus
  /** True = the PRIMARY variant's size is still a placeholder cube, not
   *  informed by the model's proportions yet. */
  dims_estimated?: boolean
  /** What Blender read out of the mesh — informational, nothing is derived
   *  from it (the dims come from `bbox`). Absent until measured. */
  measured?: { tris?: number; verts?: number; uv_layers?: number; vertex_colors?: number }
  rotation?: { x?: number; y?: number; z?: number }
  /** The PRIMARY variant's object-local markers. Edited per variant. */
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
  variant_tiers?: Array<{
    variant: number
    tiers: string[]
    /** The three real metres THIS variant renders at (props.variant_dims). */
    dims?: PropDims
    /** How deep THIS variant stands in the ground (absent = on the ground). */
    ground_offset_m?: number
    /** Its object-local markers (absent = none). Full records only — the lean
     *  client library gets `marker_count` and nothing else. */
    markers?: PropMarker[]
  }>
  /** How many active variants actually carry a mesh. */
  variant_count?: number
  /** ACTIVE model variants in total — the ones a scene renders. */
  variants_total?: number
  /** How many of the active variants still lack their mesh resp. their source
   *  image. Counts only, deliberately: the library list flags THAT a prop is
   *  incomplete, the variant strip in the detail says which variant it is. */
  variants_missing_mesh?: number
  variants_missing_image?: number
  /** Configured ceiling on ACTIVE variants (image_generation.prop_variant_max). */
  variant_max?: number
  /** Which key colours this prop's render was asked for (`["picture"]`) —
   *  set in the create form, patchable here, and what makes a landing mesh
   *  split itself automatically (spec-picture-props.md § 2/3). */
  key_areas?: string[]
  /** The key surfaces the mesh actually carries. The Areas tab reads the
   *  richer `GET …/areas` (outlines, mesh layout, Blender state); this is the
   *  same list on the record, so a reader that only needs "has it any?" costs
   *  no second request. */
  areas?: PropArea[]
  /** Prop-wide slot values that apply WITHOUT a variant — a door's pane is
   *  glass on every placement of it, and a door prop has no variants. */
  area_defaults?: PropSlotValues
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
  /** Season names this variant depicts (E2c); empty = every season. */
  seasons: string[]
  /** Does that tag match the world's CURRENT season? An untagged variant is
   *  always in season, and so is every variant in a world without seasons. */
  in_season: boolean
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
  /** The three real metres THIS variant renders at — always complete, because
   *  the size belongs to the variant and there is nothing to inherit. */
  dims: PropDims
  /** True while those three are still the placeholder cube the mesh
   *  proportions have not informed. */
  dims_estimated: boolean
  /** The variant's generation subject ('' = none, and a render composes from
   *  the prop's NAME). A new variant starts with a COPY of the one it was
   *  added from, so this is usually filled — and editing it is how a version
   *  of the object gets its own product shot ("…as a sapling"). */
  description: string
  /** How deep THIS variant stands in the ground, in metres (−5…+5): negative
   *  sinks it, positive lifts it, and it applies wherever this version stands
   *  — manual placements, room/yard scatter, painted terrain scatter, world
   *  props. 0 = on the ground. The per-placement `offset_y` in the room editor
   *  stays the trim of one instance on top of it. */
  ground_offset_m: number
  /** Its object-local animation markers — fractions of THIS mesh's bounding
   *  box, which is why they cannot be shared with another version. */
  markers: PropMarker[]
  /** WHAT this variant shows in the prop's picture areas, keyed by area id
   *  (spec-picture-props.md § 1, D2). Empty/absent = an ordinary model
   *  variant; a filled map makes it a PICTURE variant, whose mesh is a COPY
   *  of the primary frame. */
  slot_values?: PropSlotValues
  /** The name the variant is listed under. Derived from the picture file
   *  names when it was created without one. */
  label?: string
  /** True = this picture variant's COPIED frame predates the mesh the prop
   *  shows now (the frame was re-split) — the tab offers "Re-copy mesh". */
  stale?: boolean
  /** Whether THIS variant's mesh has a walkable surface baked. */
  surface_status?: SurfaceStatus
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

/** What the Prompt Help must know before it "improves" a prop prompt (the
 *  `promptContext` of the render dialog's prompt field). This image is not a
 *  picture, it is the INPUT of the img2mesh pass: a scene, a cast shadow or a
 *  dramatic angle bakes into the geometry, so an assistant that adds the
 *  usual image-prompt garnish makes the mesh worse, not the picture better.
 *  Same wording rules as the "prop" use case in app/core/config.py. */
export const PROP_PROMPT_CONTEXT =
  'This prompt renders the SOURCE IMAGE of ONE furnishing prop (chair, table, '
  + 'plant …), which is then converted into a 3D mesh by an img2mesh backend. '
  + 'A single object, isolated and centred on a plain neutral studio '
  + 'background with a generous margin, flat even lighting, the whole object '
  + 'in frame. No scene, no environment, no people or hands, no cast shadows, '
  + 'no dramatic perspective, no text — all of that bakes into the mesh. Keep '
  + 'it a product shot of the object, not a picture of a place. The prompt is '
  + 'framed as 3D-ASSET creation on purpose — it opens with "A high-quality '
  + '3D model of …" and carries "designed for 3D asset generation, 8k '
  + 'resolution". Keep that framing word for word, and never state it twice.'

/** The subject slot a use-case style may carry — the server's weaving rule
 *  (`prompt_compose.weave_subject`) spelled the same way on this side. */
const SUBJECT_SLOT = '{subject}'

/** The FINAL prop render prompt from the backend's use-case style + this
 *  variant's subject — the client half of `props.compose_prompt`.
 *
 *  The style owns the wording, including the 3D-asset framing ("A high-quality
 *  3D model of {subject}, designed for 3D asset generation, 8k resolution"),
 *  and this only puts the subject where the style asks for it. That is why
 *  both prop dialogs call THIS and neither writes a phrase of its own: the
 *  framing has one home (the "prop" use case in `app/core/config.py`), and a
 *  second copy here would land in the final prompt twice.
 *
 *  Mirrors `weave_subject`: the slot is filled once, a leading article is
 *  lower-cased mid-sentence ("… model of A pine" reads wrong), a trailing full
 *  stop of the subject would cut the sentence in half, and a style WITHOUT a
 *  slot keeps the historic append. */
export function composePropPrompt(style: string, subject: string): string {
  const s = (style || '').trim()
  const woven = (subject || '').trim().replace(/[\s.]+$/, '')
  if (!s.includes(SUBJECT_SLOT)) return s ? (woven ? `${s}, ${woven}` : s) : woven
  const at = s.indexOf(SUBJECT_SLOT)
  const article = ['a', 'an', 'the'].includes(woven.split(' ')[0].toLowerCase())
  const fill = at > 0 && article ? woven[0].toLowerCase() + woven.slice(1) : woven
  // Only the FIRST slot is filled, any further one is dropped — the server
  // warns about that style and composes the same text. The replacer is a
  // FUNCTION so a `$` in the subject stays a dollar sign.
  return s.replace(SUBJECT_SLOT, () => fill).split(SUBJECT_SLOT).join('')
}

// ── Picture areas (spec-picture-props.md) ─────────────────────────────────

/**
 * THE AREA KINDS, in ONE place (ruling R8).
 *
 * A key surface of a prop's mesh — the panel a picture hangs on, the pane of
 * a door — is a MATERIAL of the GLB, and its kind decides three unrelated
 * things: the label it is listed under, the colour its outline gets in the 3D
 * viewer, and the chroma-key fragment the render prompt asks for. All three
 * hang on this list, so a new kind (Task 6 adds `leaf`) is one entry here and
 * nothing else — the kind select, the polygon tool's kind choice, the create
 * form's checkboxes and the outline colours all read from it.
 *
 * Mirrors `app/core/picture_areas.KINDS` (order included) and, for the two
 * kinds that have one, `config.KEY_AREA_PROMPTS` / `KEY_AREA_NEGATIVES`
 * verbatim — the server appends them itself and the append is idempotent, so
 * this copy only PREVIEWS the finished prompt.
 */
export interface AreaKind {
  /** The server's kind token — also the `<kind>_<n>` prefix of an area id. */
  kind: string
  /** English source string, rendered through `t()`. */
  label: string
  /** Outline colour in the 3D viewer. */
  color: string
  /** WHAT fills an area of this kind — a picture out of a gallery (`image`)
   *  or a look out of `MATERIAL_PRESETS` (`preset`). It is the field the value
   *  is written under, so the editor picks its control from this instead of
   *  naming a kind. Mirrors `props.SLOT_KINDS` through `detect_slots`. */
  value: 'image' | 'preset'
  /** How the create form offers this kind. Absent = it cannot be REQUESTED
   *  at generation time (it is only ever drawn by hand). */
  requestLabel?: string
  /** What asking for it appends to the render prompt (absent = nothing). */
  prompt?: string
  /** …and to the negative prompt. */
  negative?: string
}

export const AREA_KINDS: AreaKind[] = [
  {
    kind: 'picture',
    label: 'Picture',
    color: '#22c55e',
    value: 'image',
    requestLabel: 'Picture (green screen)',
    prompt: ', the picture surface inside the frame is a single flat '
      + 'uniform bright chroma-key green panel (#00FF00), no reflections, '
      + 'no artwork, no text',
    negative: 'painting, artwork, photo, poster, landscape in frame',
  },
  {
    kind: 'glass',
    label: 'Glass',
    color: '#d946ef',
    value: 'preset',
    requestLabel: 'Glass (magenta)',
    prompt: ', the window pane is a single flat uniform bright magenta '
      + 'panel (#FF00FF), no reflections',
    negative: 'transparent glass, reflections',
  },
]

/** The kind record of an area id's kind — `undefined` for a kind this client
 *  does not know (a newer server), which every reader treats as "no colour,
 *  no fragment" rather than as a crash. */
export function areaKindOf(kind: string): AreaKind | undefined {
  return AREA_KINDS.find((k) => k.kind === kind)
}

/** Comma tags joined without duplicates, case-insensitively, order kept —
 *  `prompt_compose.merge_tags` on this side. */
function mergeTags(...parts: string[]): string {
  const out: string[] = []
  const seen = new Set<string>()
  for (const part of parts) {
    for (const raw of (part || '').split(',')) {
      const tag = raw.trim()
      const key = tag.toLowerCase()
      if (tag && !seen.has(key)) { seen.add(key); out.push(tag) }
    }
  }
  return out.join(', ')
}

/**
 * The chroma-key fragments of `kinds` on a FINAL prompt + negative — the
 * client half of `props.apply_key_areas`, and a PREVIEW only.
 *
 * Idempotent for the same reason the server's is: the create form shows the
 * composed text and sends it back, and the server appends to whatever it
 * receives. Kind order is the fixed one of `AREA_KINDS`, not the order the
 * checkboxes were ticked in.
 */
export function applyKeyAreas(prompt: string, negative: string,
                              kinds: string[]): { prompt: string; negative: string } {
  let out = (prompt || '').replace(/\s+$/, '')
  let neg = negative || ''
  for (const entry of AREA_KINDS) {
    if (!kinds.includes(entry.kind) || !entry.prompt) continue
    const core = entry.prompt.replace(/^[\s,]+|[\s,]+$/g, '')
    if (core && !out.includes(core)) {
      out = out ? out.replace(/[\s,]+$/, '') + entry.prompt : core
    }
    if (entry.negative && !neg.includes(entry.negative)) {
      neg = mergeTags(neg, entry.negative)
    }
  }
  return { prompt: out, negative: neg }
}

/** What ONE picture area is filled with. Exactly one of the two per entry —
 *  a `picture` panel takes an image URL of this world's galleries, a `glass`
 *  pane a preset out of `SLOT_PRESETS` (`glass` is the only one today).
 *  Structurally the `SceneSlotValues` of @anima/scene-render. */
export interface PropSlotValue {
  image?: string
  preset?: string
}

/** Keyed by AREA ID (`picture_1`) — the map a variant stores and the scene
 *  recipe copies into its `models[].slots`. */
export type PropSlotValues = Record<string, PropSlotValue>

/** ONE detected or drawn key surface of the prop's mesh (`props.sanitize_areas`
 *  + the outline of the active mesh). The face assignment itself lives in the
 *  GLB and never travels — `faces` is a COUNT. */
export interface PropArea {
  /** `<kind>_<n>` — it IS the slot name, and `slot_<id>` the material name. */
  id: string
  kind: string
  /** Real extent of the panel in metres, [w, h]. */
  size_m: [number, number]
  normal: [number, number, number]
  source: 'auto' | 'manual'
  /** How many triangles carry this area's material. */
  faces: number
  /** The material the faces came from (informational). */
  origin?: string
  centroid?: [number, number, number]
  /** Outline segments in glTF y-up MODEL space — the server computed them at
   *  the split, the viewer only draws them (§ B5a: no geometry in a client). */
  edges?: AreaEdge[]
}

/** One outline segment: two points in model metres. */
export type AreaEdge = [[number, number, number], [number, number, number]]

/** What the viewer needs to draw one area's outline. */
export interface AreaOutline {
  id: string
  kind: string
  edges: AreaEdge[]
}

/** ONE mesh of the model in the R1 face-index order: meshes sorted by NAME,
 *  triangles in buffer order within each. The polygon tool aligns the loaded
 *  three.js meshes against this before it flattens an index. */
export interface MeshLayoutEntry {
  name: string
  tri_count: number
}

/** The answer of `GET /world/props/{id}/areas`. */
export interface PropAreasInfo {
  areas: PropArea[]
  mesh_layout: MeshLayoutEntry[]
  /** Which key colours the prop's render was asked for. */
  key_areas: string[]
  /** Prop-wide values that apply WITHOUT a variant (a door's pane). */
  area_defaults: PropSlotValues
  blender: { available: boolean; reason: string }
  /** UTC ISO stamp of the last detection run ('' / null = never). */
  last_run?: string | null
  /** What the last AUTOMATIC run failed with ('' = nothing). */
  error?: string
}
