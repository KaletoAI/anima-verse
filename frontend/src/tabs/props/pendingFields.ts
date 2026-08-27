/**
 * The prop detail's CHANGE BUFFER — one local draft, one explicit Save.
 *
 * Every field of a prop used to write through the moment it lost focus: the
 * name on blur, each of the three metres on blur, the subject on blur, the
 * sink on a debounce, a season chip on click, a marker slider on a debounce.
 * Authoring ONE variant — three metres, a subject, a sink, a season tag, two
 * markers — was seven requests and seven sidecar writes for one thought, and
 * every one of them made the whole tab reload. The edits collect here now and
 * go out in ONE request (`POST /world/props/{id}/bulk`).
 *
 * WHY THIS IS NOT `tabs/map/pendingBuffer`, which does the same job for the
 * map editor: that buffer holds WHOLE OBJECTS and the last one wins — a
 * dragged polygon replaces the polygon before it, and the extra machinery it
 * carries (deletes, client-side temp ids, per-object `updated_at` stamps,
 * per-object rejections) is what drawing a map needs. A prop detail edits
 * FIELDS of records that already exist: the size, then the subject, then a
 * marker of the SAME variant must all survive, so the entries MERGE key by key
 * instead of replacing each other, and nothing here is ever created or deleted
 * by a Save. Sharing one module would have meant a union of two shapes with
 * half of it inert on either side; the two laws they DO share ("the last thing
 * decided about a target", "the draft laid over the server's list so a refetch
 * cannot eat unsaved work") are stated once in each and read the same.
 *
 * THE RULES, each one a case somebody actually produces:
 *
 * - Type a width, then a subject, then drag a marker, then Save → ONE request
 *   carrying three fields of one variant. `queueFields` MERGES the patch into
 *   what the target already has.
 * - Type a width, then type it again → one field, the last value. Within one
 *   field the last write wins, exactly as the map buffer does per object.
 * - The three dims travel as ONE `dims` object, never as three keys: a prop is
 *   scaled uniformly, so the trio is one statement (how big, and what shape) —
 *   and "Save (1)" for one resize is what the admin actually did.
 * - Delete a variant (an immediate operation, see below) → its pending fields
 *   go with it, AND every pending target behind it moves down by one, because
 *   that is exactly how the server renumbers the list.
 *
 * WHAT IS NOT IN THE BUFFER, deliberately: everything that moves a FILE.
 * Rendering or uploading a source image, meshing, picking a mesh from the
 * gallery, the orientation fix, and the variant verbs add / on-off / delete.
 * They change what the mesh signature, the store indices and a running
 * generation address — a draft of them would be a promise about files that do
 * not exist yet, and the strip's own gallery would be reading a list the server
 * has never heard of. They stay immediate and their reload lands under the
 * draft, which `applyVariantDraft` then puts back on top.
 *
 * The module is PURE: every function returns a new Map and touches no state of
 * its own, which is what makes it testable without React
 * (`scripts/smoke_prop_fields_buffer.mjs`) and safe as React state.
 */

/** One target's pending fields — `{dims, description, …}` for a variant,
 *  `{name, category, tags, sway_factor, slots}` for the prop itself. */
export type FieldPatch = Record<string, unknown>

/** target key → the fields decided about it so far. */
export type PendingFields = ReadonlyMap<string, FieldPatch>

/** The prop's own fields (name / category / tags / sway / slots) live under
 *  this one key — the batch body's `general`. */
export const GENERAL_TARGET = 'general'

/** A variant's target key. The STORE INDEX is what every variant-scoped route
 *  takes, so it is what the buffer is keyed by as well. */
export function variantTarget(index: number): string {
  return `v:${index}`
}

/** The store index behind a variant target key, or -1 for the general one. */
function targetIndex(target: string): number {
  if (!target.startsWith('v:')) return -1
  const n = Number(target.slice(2))
  return Number.isInteger(n) ? n : -1
}

export function emptyFields(): PendingFields {
  return new Map<string, FieldPatch>()
}

/**
 * How many FIELDS are waiting — the number in the Save button.
 *
 * Fields, not targets: "Save (5)" for five edited fields says how much unsaved
 * work there is, while a count of targets would say "1" for a whole variant
 * rewritten. The dims trio counts as ONE, because it travels as one `dims`
 * object and one resize is one edit.
 */
export function pendingFieldCount(buf: PendingFields): number {
  let n = 0
  for (const patch of buf.values()) n += Object.keys(patch).length
  return n
}

/** Is anything waiting? The dirty flag behind the guards. */
export function isFieldsDirty(buf: PendingFields): boolean {
  return pendingFieldCount(buf) > 0
}

/**
 * Remember these fields for this target. The patch is MERGED into what the
 * target already holds — a later edit of another field must not drop the
 * earlier one — and within one field the last value wins.
 */
export function queueFields(buf: PendingFields, target: string,
  patch: FieldPatch): PendingFields {
  const next = new Map(buf)
  next.set(target, { ...(buf.get(target) || {}), ...patch })
  return next
}

/**
 * What one field says RIGHT NOW: the buffered value when the field was edited,
 * the stored one otherwise.
 *
 * Every commit compares against THIS and not against the server's value —
 * a field typed away and back must end up with what is on screen, and a
 * comparison against the stored value would let the first edit stand in the
 * buffer while the input shows the second.
 */
export function draftValue<T>(buf: PendingFields, target: string,
  field: string, stored: T): T {
  const patch = buf.get(target)
  return patch && field in patch ? (patch[field] as T) : stored
}

/**
 * The buffer after a variant was DELETED on the server.
 *
 * Its own pending fields are gone — there is nothing left to save them onto —
 * and every target behind it moves down by one, because a delete pops the
 * entry out of the stored list and renumbers exactly that way. Leaving them
 * would write one variant's unsaved size onto its neighbour.
 */
export function dropDeletedVariant(buf: PendingFields,
  index: number): PendingFields {
  const next = new Map<string, FieldPatch>()
  for (const [target, patch] of buf) {
    const i = targetIndex(target)
    if (i < 0) { next.set(target, patch); continue }
    if (i === index) continue
    next.set(i > index ? variantTarget(i - 1) : target, patch)
  }
  return next
}

/** The body of one batch save (`POST /world/props/{id}/bulk`). An empty half
 *  is left out entirely, so a body says what it changes and nothing else. */
export function toBulkFieldBody(buf: PendingFields): {
  general?: FieldPatch
  variants?: Record<string, FieldPatch>
} {
  const body: { general?: FieldPatch; variants?: Record<string, FieldPatch> } = {}
  const variants: Record<string, FieldPatch> = {}
  for (const [target, patch] of buf) {
    if (!Object.keys(patch).length) continue
    if (target === GENERAL_TARGET) {
      body.general = patch
      continue
    }
    const i = targetIndex(target)
    if (i >= 0) variants[String(i)] = patch
  }
  if (Object.keys(variants).length) body.variants = variants
  return body
}

/** The variant fields this buffer may carry — the same five the server's
 *  `VARIANT_PATCH_APPLIERS` knows, spelled the same way. */
interface VariantDraftFields {
  index: number
  dims: { width_m: number; depth_m: number; height_m: number }
  dims_estimated: boolean
  description: string
  ground_offset_m: number
  markers: unknown[]
  seasons: string[]
}

/**
 * The variant list as the DRAFT sees it: the server's records with every
 * buffered field laid on top.
 *
 * This is what keeps a refetch from eating unsaved work — and a refetch
 * happens on its own here, because the immediate operations beside the draft
 * (a mesh generated, a variant added) reload the list. The order and every
 * untouched field stay the server's.
 *
 * `dims` MERGES rather than replaces: a patch may name one metre, and the
 * other two are then still the stored ones. A dims patch also clears
 * `dims_estimated` in the draft, because storing a size does exactly that —
 * the hint must not go on claiming the number is a guess the admin just typed
 * over.
 */
export function applyVariantDraft<T extends VariantDraftFields>(
  list: T[], buf: PendingFields): T[] {
  if (!buf.size) return list
  return list.map((v) => {
    const patch = buf.get(variantTarget(v.index))
    if (!patch || !Object.keys(patch).length) return v
    const out = { ...v, ...patch } as T
    if (patch.dims) {
      out.dims = { ...v.dims, ...(patch.dims as Partial<T['dims']>) }
      out.dims_estimated = false
    }
    return out
  })
}
