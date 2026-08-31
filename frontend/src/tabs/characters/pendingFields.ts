/**
 * The character detail's CHANGE BUFFER — one local draft, one explicit Save.
 *
 * Every field of a character sheet used to write through the moment it lost
 * focus: the name on blur, the appearance prompt on blur, a select the instant
 * it changed. Filling in a new character — a dozen fields of one thought — was
 * a dozen requests and a dozen toasts, each one a point at which half a sheet
 * was already stored, and there was no way back from a typo except typing the
 * old value again. The edits collect here now and go out together when the
 * toolbar's Save is pressed.
 *
 * WHY THIS IS ITS OWN MODULE and not `tabs/props/pendingFields`, which does the
 * same job for a prop: the shapes agree, the TARGETS do not. A prop batches
 * into ONE route (`/world/props/{id}/bulk`) whose body has two halves; a
 * character has no batch route at all — its stores are four separate endpoints
 * (`/profile`, `/config`, `/outfit-imagegen`, `/body-slots/{slot}`), two of
 * which take many fields per request and two of which take a whole record. So
 * the target vocabulary, the body shape and the number of requests a Save
 * produces are all different, and a shared module would have been a union with
 * half of it inert on either side. The two laws they DO share ("the last thing
 * decided about a target", "the draft laid over the server's values so a
 * refetch cannot eat unsaved work") are stated once in each and read the same.
 *
 * THE RULES, each one a case somebody actually produces:
 *
 * - Type a name, then an age, then pick a gender, then Save → ONE request to
 *   `/profile` carrying three fields. `queueFields` MERGES the patch into what
 *   the target already has.
 * - Type an age, then type it again → one field, the last value. Within one
 *   field the last write wins.
 * - A profile field and a config field edited together → two requests, one per
 *   store, because that is how many stores were touched — never one request per
 *   field.
 * - `status_effects` is ONE profile field whose value happens to be an object:
 *   the form merges the whole map and queues it under that single key, so two
 *   edited effects are one pending field, exactly as one `/profile` request
 *   carrying one key is what they produce.
 *
 * WHAT IS NOT IN THE BUFFER, deliberately: everything that moves a FILE or runs
 * a pipeline — rendering, uploading, meshing, deleting, the template switch,
 * the memory verbs. A draft of those would be a promise about files that do not
 * exist yet. They stay immediate.
 *
 * The module is PURE: every function returns a new Map and touches no state of
 * its own, which is what makes it safe as React state.
 */

/** One target's pending fields — `{name, age, …}` for the profile store,
 *  `{chat_mode, …}` for the config store. */
export type FieldPatch = Record<string, unknown>

/** target key → the fields decided about it so far. */
export type PendingFields = ReadonlyMap<string, FieldPatch>

/** The character profile store (`POST /characters/{n}/profile {fields}`). */
export const PROFILE_TARGET = 'profile'
/** The per-character config store (`POST /characters/{n}/config {fields}`). */
export const CONFIG_TARGET = 'config'
/** The image-generation override record (`PUT /characters/{n}/outfit-imagegen`).
 *  That route takes the WHOLE record, so its patch is the whole body — the
 *  editor queues every key of it at once. */
export const IMAGEGEN_TARGET = 'imagegen'

/** One body slot's values (`POST /characters/{n}/body-slots/{slot} {values}`).
 *  Each slot is its own request, so each slot is its own target. */
export function bodyTarget(slotId: string): string {
  return `body:${slotId}`
}

/** The slot id behind a body target key, or '' for anything else. */
function bodySlotId(target: string): string {
  return target.startsWith('body:') ? target.slice(5) : ''
}

/** Shared empty patch — a stable identity, so a `targetPatch` of a target that
 *  holds nothing does not invalidate a memo on every render. */
const NO_FIELDS: FieldPatch = Object.freeze({})

export function emptyFields(): PendingFields {
  return new Map<string, FieldPatch>()
}

/**
 * How many FIELDS are waiting — the number in the Save button.
 *
 * Fields, not targets: "Save (5)" for five edited fields says how much unsaved
 * work there is, while a count of targets would say "1" for a whole sheet
 * rewritten. The one exception is the imagegen target: its route takes the
 * WHOLE record, so every edit queues all four keys at once — counting them
 * individually would jump the button to "Save (4)" on the first keystroke.
 * It counts as ONE change (the props buffer's "dims counts as 1" precedent).
 */
export function pendingFieldCount(buf: PendingFields): number {
  let n = 0
  for (const [target, patch] of buf.entries()) {
    if (target === IMAGEGEN_TARGET) {
      n += Object.keys(patch).length > 0 ? 1 : 0
      continue
    }
    n += Object.keys(patch).length
  }
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
 * Everything decided about one target so far — the layer a form lays OVER the
 * server's values so a refetch cannot eat unsaved work, and so a field typed
 * away and back shows what is on screen rather than what is stored.
 */
export function targetPatch(buf: PendingFields, target: string): FieldPatch {
  return buf.get(target) || NO_FIELDS
}

/** What one field says RIGHT NOW: the buffered value when the field was
 *  edited, the stored one otherwise. */
export function draftValue<T>(buf: PendingFields, target: string,
  field: string, stored: T): T {
  const patch = buf.get(target)
  return patch && field in patch ? (patch[field] as T) : stored
}

/**
 * The buffer split by STORE — one entry per request the Save has to make.
 *
 * An empty half is left out entirely, so the caller sends what actually
 * changed and nothing else: no `/config` request for a sheet where only
 * profile fields were touched.
 */
export function toSaveBody(buf: PendingFields): {
  profile?: FieldPatch
  config?: FieldPatch
  imagegen?: FieldPatch
  body?: Record<string, FieldPatch>
} {
  const out: {
    profile?: FieldPatch
    config?: FieldPatch
    imagegen?: FieldPatch
    body?: Record<string, FieldPatch>
  } = {}
  const body: Record<string, FieldPatch> = {}
  for (const [target, patch] of buf) {
    if (!Object.keys(patch).length) continue
    if (target === PROFILE_TARGET) { out.profile = patch; continue }
    if (target === CONFIG_TARGET) { out.config = patch; continue }
    if (target === IMAGEGEN_TARGET) { out.imagegen = patch; continue }
    const slot = bodySlotId(target)
    if (slot) body[slot] = patch
  }
  if (Object.keys(body).length) out.body = body
  return out
}
