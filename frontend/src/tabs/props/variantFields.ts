/**
 * The FIELDS one model variant of a prop owns — their descriptors and the
 * pure commit law behind each of them.
 *
 * They used to sit inside `PropVariantStrip`, one copy per chip. Since the
 * props page was restructured (2026-08-29) the chip is a SELECTOR — variant
 * number, badges, seasons, active, delete — and every input of the selected
 * variant stands in the second column, beside the model it describes: the
 * size trio and the sink under "Variant settings", the two triangle budgets
 * with the resolution tiers they decide.
 *
 * So the law moved here rather than being written twice: what an empty field
 * means, what is clamped, and when an edit is no edit at all. Every function
 * below returns the PATCH that belongs in the detail's change buffer, or
 * `null` when nothing changed — none of them touches React state or the
 * server. The redistribution itself stays in `dims.ts`, which is where
 * `scripts/smoke_variant_dims.mjs` proves it.
 */
import { faceFor } from '../../components/faceBudget'
import { DEFAULT_MODEL_TIER } from '../../components/ModelGallery'
import { DIM_KEYS, DIM_MAX_M, DIM_MIN_M, orientedDims, variantRedistribute,
  type DimKey } from './dims'
import type { PropDims } from './propTypes'

/** The three dims in the form's own order. `label` is the short caption on
 *  the input, `title` the sentence behind it. */
export const DIM_FIELDS: Array<{ key: DimKey; label: string; title: string }> = [
  { key: 'width_m', label: 'W', title: 'Width (m)' },
  { key: 'depth_m', label: 'D', title: 'Depth (m)' },
  { key: 'height_m', label: 'H', title: 'Height (m)' },
]

/** The two face budgets of a variant (v2 E5), in the order they are used: the
 *  close-up mesh first, the distance mesh second. `placeholder` says what
 *  happens when the field is left empty — the picked backend's own face count
 *  for the full mesh, a quarter of it for the distance mesh (the dialog's
 *  `faceFor` rule, and the number the reduction lands near). */
export const FACE_FIELDS: Array<{
  key: 'high' | 'low'
  label: string
  title: string
  placeholder: (backendFaces: number, t: (s: string) => string) => string
}> = [
  { key: 'high', label: '△ High', title: 'Triangles this variant’s close-up mesh should cost. Empty = whatever the picked backend uses by default. The generate dialog opens on this number and the automatic improvement re-meshes to it; above the backend’s own ceiling the run is clamped and the gallery row says so.',
    // The dialog's own rule, imported rather than restated: the number the
    // admin sees here and the number a run starts on must be one function.
    placeholder: (faces, t) => (faces
      ? faceFor(DEFAULT_MODEL_TIER, faces) : t('backend default')) },
  { key: 'low', label: '△ Low', title: 'Triangles this variant’s DISTANCE mesh should cost. Empty = the configured reduction fraction decides. Given, the server reduces to exactly this budget — it divides it by the full mesh’s own triangle count to get the Decimate ratio.',
    placeholder: (faces, t) => (faces
      ? faceFor('low', faces) : t('LOD ratio')) },
]

/** The window the server accepts a budget in (`props.FACE_TARGET_MIN/MAX`) —
 *  the input only has to agree with it. */
export const FACE_TARGET_MIN = 100
export const FACE_TARGET_MAX = 2000000

/** Clamp of the ground offset, the stored limit itself
 *  (`props.GROUND_OFFSET_MIN/MAX`). The field is TYPED, not swept (user
 *  2026-08-25): sinking is a value you know — 0.05 for a mesh with a base
 *  plate, 0.4 to bury a root ball — and a slider sweeping ±5 m hits neither. */
export const SINK_LIMIT_M = 5

/** Rows of the description field: readable at rest, a real editor while it is
 *  written in. 5/12 (was 3/8, before that 1/4) — the user twice asked for more
 *  room, because a variant's subject is whole sentences, not tags. */
export const DESC_ROWS_REST = 5
export const DESC_ROWS_OPEN = 12

/**
 * WHERE THE PROPORTIONS OF A RESIZE COME FROM — never the prop's box.
 *
 * The variant on screen is MEASURED: `bbox` is its raw mesh box, and the
 * file's orientation fix turns it into [width, height, depth] exactly as every
 * renderer does. That is the only true statement about THIS mesh the client
 * holds — a sapling's GLB is not a small pine, so redistributing along the
 * prop's aspect would give it the grown tree's footprint.
 *
 * Without a loaded box the stored dims stand in: they ARE the variant's
 * declared aspect, and since every renderer sizes a variant by exactly those
 * three numbers, rescaling along them keeps the object the shape it is
 * rendered at.
 */
export function dimRatios(dims: PropDims, bbox: [number, number, number] | null,
  rotation?: { x?: number; y?: number; z?: number }): Record<DimKey, number> {
  if (bbox) {
    const [w, h, d] = orientedDims(bbox, rotation)
    return { width_m: w, depth_m: d, height_m: h }
  }
  return { width_m: dims.width_m, depth_m: dims.depth_m, height_m: dims.height_m }
}

/**
 * ONE edited size field, and with it the other two.
 *
 * The trio is a resize of a known mesh, not three free numbers (see `dims.ts`),
 * so the edited value drives and the other two follow the variant's
 * proportions. All three travel as ONE `dims` object, so the preview follows
 * immediately and Save writes one field.
 *
 * An empty or unusable input is not a size at all — `null` comes back and the
 * field snaps to what is stored. There is nothing to inherit since 2026-08-25,
 * so "cleared" is not a state a variant may be in: a typing slip costs the
 * edit, never the size.
 */
export function dimsPatch(stored: PropDims, key: DimKey, raw: string,
  ratios: Record<DimKey, number>): PropDims | null {
  const n = parseFloat(raw)
  if (!Number.isFinite(n) || n <= 0) return null
  // A ratio source with a flat edge (a mesh box measuring zero on one axis)
  // redistributes to nothing usable — then the edited field goes out alone
  // rather than a zero, and the other two stay where they are. Clamped and
  // rounded to the same window the helper keeps, so this path cannot store a
  // number the server would round away into a cleared key either.
  const next = variantRedistribute(key, n, ratios) ?? {
    ...stored,
    [key]: Math.round(Math.min(Math.max(n, DIM_MIN_M), DIM_MAX_M) * 1000) / 1000,
  }
  if (DIM_KEYS.every((k) => next[k] === stored[k])) return null
  return next as PropDims
}

/**
 * ONE of the two face budgets (v2 E5).
 *
 * An EMPTY field is a real statement here, unlike a size: it CLEARS the budget
 * and hands the decision back to the backend default (high) / the configured
 * reduction ratio (low) — which is exactly what the placeholder then shows, so
 * the field never lies about what the next run will use.
 *
 * BOTH budgets travel every time, like the dims trio and for the same reason:
 * the change buffer merges patches field by field, so a second edit sending
 * only its own half would drop the first one. The other half is read off the
 * DRAFT record, which already carries an earlier edit.
 */
export function facePatch(
  stored: { high?: number | null; low?: number | null },
  which: 'high' | 'low', raw: string,
): { target_faces_high: number | null; target_faces_low: number | null } | null {
  const text = raw.trim()
  const n = text ? parseInt(text, 10) : 0
  const value = text && Number.isFinite(n) && n > 0 ? n : null
  const was = {
    target_faces_high: stored.high ?? null,
    target_faces_low: stored.low ?? null,
  }
  const next = {
    ...was,
    [which === 'high' ? 'target_faces_high' : 'target_faces_low']: value,
  }
  if (next.target_faces_high === was.target_faces_high
    && next.target_faces_low === was.target_faces_low) return null
  return next
}

/** How deep the variant stands in the ground, clamped to what the server
 *  stores. `null` = the number is the one already stored. 0 clears the key,
 *  which is the normal state. */
export function sinkPatch(stored: number | undefined, value: number): number | null {
  const next = Math.round(
    Math.min(Math.max(value, -SINK_LIMIT_M), SINK_LIMIT_M) * 100) / 100
  return next === stored ? null : next
}

/** The variant's generation subject. Blank clears the key and a render
 *  composes from the prop's NAME — the same law the server stores by, so the
 *  draft says exactly what will be kept. */
export function descPatch(stored: string | undefined, raw: string): string | null {
  const value = raw.trim()
  return value === (stored || '') ? null : value
}
