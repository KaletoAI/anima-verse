/**
 * The face-budget arithmetic every mesh surface shares.
 *
 * A triangle budget is stated in three places — the variant strip's two
 * fields, the generate dialog's face field, the distance-mesh button — and all
 * three have to agree on what an EMPTY statement means, or the number the
 * admin reads is not the number the run starts on. So the rule lives here and
 * is imported, never restated: the module holds no component, which is also
 * what keeps it out of the fast-refresh rule.
 *
 * The order of preference is always the same (spec-bild-props-v2.md E5): what
 * the SUBJECT states beats what the backend defaults to, because the subject's
 * statement outlives the run.
 */
import { DEFAULT_MODEL_TIER, type ModelTier } from './ModelGallery'

/** Low-variant recipe for a run that targets the `low` tier directly — the
 *  third way next to a baked generation stage and the mesh→mesh reduction: a
 *  second run with a smaller budget. The numbers are a PREFILL, shown in the
 *  editable fields — not a hidden rewrite of what the admin asked for. */
export const LOW_FACE_FRACTION = 0.25
/** Offered when the picked backend declares no face default of its own. */
export const LOW_FACE_FALLBACK = 4000
/** Prefilled target size of the low stage — the alias default of the contract. */
export const LOD_STAGE_DEFAULT = 5000

/** What the SUBJECT of a run states about its own triangle budgets — a prop
 *  variant's `target_faces_high` / `target_faces_low` where the caller has
 *  them. Absent fields fall back to the backend default. */
export interface FaceTargets {
  high?: number | null
  low?: number | null
}

/**
 * Face budget prefilled for a tier: what the SUBJECT states for it, else the
 * backend default for `full` and a quarter of it (rounded to 500) for `low`.
 * `''` = leave it to the backend.
 *
 * The subject's own targets come first because they are a decision that
 * outlives the run: a variant that says what it costs must not have that
 * overwritten by whatever the picked backend defaults to.
 */
export function faceFor(tier: ModelTier, backendDefault: number,
                        stated: FaceTargets = {}): string {
  if (tier === DEFAULT_MODEL_TIER) {
    if (stated.high) return String(stated.high)
    return backendDefault ? String(backendDefault) : ''
  }
  if (stated.low) return String(stated.low)
  if (!backendDefault) return String(LOW_FACE_FALLBACK)
  return String(Math.max(500, Math.round(backendDefault * LOW_FACE_FRACTION / 500) * 500))
}
