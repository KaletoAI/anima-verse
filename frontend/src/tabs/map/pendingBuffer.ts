/**
 * The map editor's CHANGE BUFFER — one local draft, one explicit Save.
 *
 * The map tab used to write every single edit straight through (`putArea` next
 * to `patchAreaLocal`, one PUT per brush stroke). Each of those writes settled
 * water, re-rastered the world relief, moved the terrain signature and made
 * every client refetch, so drawing a map paid for dozens of bakes to reach one
 * result (plan `plan-map-save-batch.md`). Now the edits land here and go out in
 * ONE bulk request per object kind.
 *
 * WHAT IT IS: a map from the object's id to the LAST thing that was decided
 * about it. Not a journal — nobody wants six intermediate polygons of one
 * dragged vertex on the wire, and the server would only store the last of them
 * anyway. Three buffers of this shape exist side by side (terrain areas, height
 * areas, world props); the rules below are identical for all three, which is
 * why they are here and not three times inside the tab.
 *
 * THE RULES, each one a case somebody actually produces:
 *
 * - Edit, edit, edit, save → ONE upsert with the last version. `queueUpsert`
 *   overwrites the entry and keeps the STAMP of the first one: the stamp is
 *   the version the object was LOADED at, and that is what the server checks
 *   the change against (optimistic concurrency, `core/bulk_edit.py`).
 * - Edit, then delete → one delete. The intermediate versions are moot.
 * - Delete, then draw over it again → an upsert. The buffer holds the last
 *   decision, not both.
 * - DRAW SOMETHING NEW, then delete it → NOTHING AT ALL. An object that never
 *   reached the server has nothing to delete there; sending its temp id would
 *   be asking the server about something it has never heard of.
 *
 * IDS: a new object gets a client-side `tempId` and carries it as its local
 * `id` so the whole editor (selection, layers, hit test) can go on treating it
 * like any other object. The bulk answer names the temp id next to the real
 * one the server minted, and the tab swaps them then — the server stays the
 * only place ids are made.
 *
 * The module is PURE: every function returns a new Map and touches no state of
 * its own, which is what makes it testable without React
 * (`scripts/smoke_pending_buffer.mjs`) and safe as React state.
 */

/** What is to happen to one object when Save is pressed. */
export type PendingOp = 'upsert' | 'delete'

export interface PendingEntry<T> {
  op: PendingOp
  /** The object as it should be stored (for a delete: the last version seen,
   *  which nothing sends but which keeps the entry self-describing). */
  obj: T
  /** The `updated_at` this object was LOADED with — the version token the
   *  server checks against. Empty for an object that is new here. */
  stamp: string
  /** Non-empty only while the object has never reached the server. */
  tempId: string
  /** Why the last Save refused this entry, if it did — `changed on the
   *  server` and friends. Set by {@link keepRejected}, shown by the tab. */
  reason?: string
}

export type PendingMap<T> = ReadonlyMap<string, PendingEntry<T>>

/** One object as the bulk routes read it: the whole body, plus the two
 *  transport keys (`temp_id` for something new, `updated_at` for the version
 *  it was loaded at). */
export interface BulkBody {
  upserts: Array<Record<string, unknown>>
  deletes: Array<{ id: string, updated_at: string }>
}

/** What one refused object looks like in a bulk answer. */
export interface BulkRejection {
  op: PendingOp
  id: string
  temp_id: string
  reason: string
}

export function emptyBuffer<T>(): PendingMap<T> {
  return new Map<string, PendingEntry<T>>()
}

/** How many objects are waiting — the number in the Save button. */
export function pendingCount<T>(buf: PendingMap<T>): number {
  return buf.size
}

/** Is anything waiting? The dirty flag behind the guards. */
export function isDirty<T>(buf: PendingMap<T>): boolean {
  return buf.size > 0
}

/** Do any of the waiting objects carry a refusal from the last Save? */
export function hasConflicts<T>(buf: PendingMap<T>): boolean {
  for (const entry of buf.values()) if (entry.reason) return true
  return false
}

/**
 * Remember the object as it now is. `stamp` is only used the FIRST time an
 * object enters the buffer — later edits keep the version it was loaded at,
 * because that is what the server has to judge the change against.
 *
 * `tempId` marks an object that does not exist on the server yet; it is kept
 * across every later edit of the same object.
 */
export function queueUpsert<T>(buf: PendingMap<T>, id: string, obj: T,
  stamp: string, tempId = ''): PendingMap<T> {
  const next = new Map(buf)
  const prev = buf.get(id)
  next.set(id, {
    op: 'upsert',
    obj,
    stamp: prev ? prev.stamp : stamp,
    tempId: prev ? (prev.tempId || tempId) : tempId,
  })
  return next
}

/**
 * Remember that the object is to go. An object that was only ever local
 * (a `tempId` and no stamp) leaves the buffer entirely instead — there is
 * nothing on the server to delete.
 */
export function queueDelete<T>(buf: PendingMap<T>, id: string, obj: T,
  stamp: string): PendingMap<T> {
  const next = new Map(buf)
  const prev = buf.get(id)
  if (prev && prev.tempId) {
    next.delete(id)
    return next
  }
  next.set(id, {
    op: 'delete',
    obj,
    stamp: prev ? prev.stamp : stamp,
    tempId: '',
  })
  return next
}

/** Forget one object's pending change (it was saved, or its conflict was
 *  resolved by taking the server's version). */
export function dropPending<T>(buf: PendingMap<T>, id: string): PendingMap<T> {
  const next = new Map(buf)
  next.delete(id)
  return next
}

/** Drop every entry the last Save refused — what an explicit Reload does:
 *  taking the server's version IS the resolution of a conflict. */
export function dropConflicts<T>(buf: PendingMap<T>): PendingMap<T> {
  const next = new Map<string, PendingEntry<T>>()
  for (const [id, entry] of buf) if (!entry.reason) next.set(id, entry)
  return next
}

/**
 * The request body of one bulk save.
 *
 * A new object travels WITHOUT an id (the local one is a placeholder the
 * server has never seen) and with its `temp_id`; an existing one travels with
 * its id and the `updated_at` it was loaded at. An object whose stamp is
 * unknown sends none, which the server reads as a deliberate overwrite —
 * exactly what the singular PUT always did.
 */
export function toBulkBody<T extends { id: string }>(
  buf: PendingMap<T>): BulkBody {
  const upserts: Array<Record<string, unknown>> = []
  const deletes: Array<{ id: string, updated_at: string }> = []
  for (const [id, entry] of buf) {
    if (entry.op === 'delete') {
      deletes.push({ id, updated_at: entry.stamp })
      continue
    }
    const body: Record<string, unknown> = { ...entry.obj }
    if (entry.tempId) {
      delete body.id
      body.temp_id = entry.tempId
    } else {
      body.id = id
      if (entry.stamp) body.updated_at = entry.stamp
    }
    upserts.push(body)
  }
  return { upserts, deletes }
}

/**
 * The list as the DRAFT sees it: the server's objects with every buffered
 * change laid on top — edits replacing their object, deletions removed, and
 * the locally drawn ones appended.
 *
 * This is what keeps a refetch from eating unsaved work: Reload, and every
 * reload after a save, loads the server's truth and then puts the draft back
 * on it. The order of the server's list is preserved; new objects come last,
 * which is where they were drawn.
 */
export function applyPending<T extends { id: string }>(
  list: T[], buf: PendingMap<T>): T[] {
  if (!buf.size) return list
  const out: T[] = []
  const known = new Set<string>()
  for (const obj of list) {
    known.add(obj.id)
    const entry = buf.get(obj.id)
    if (entry?.op === 'delete') continue
    out.push(entry ? entry.obj : obj)
  }
  for (const [id, entry] of buf) {
    if (entry.op === 'upsert' && !known.has(id)) out.push(entry.obj)
  }
  return out
}

/**
 * The buffer after a save: EXACTLY the refused objects, each carrying its
 * reason. Everything else is on the server now.
 *
 * A rejection names the object by its temp id when it had one (the server
 * never learned another name for it) and by its id otherwise.
 */
export function keepRejected<T>(buf: PendingMap<T>,
  rejected: BulkRejection[]): PendingMap<T> {
  const next = new Map<string, PendingEntry<T>>()
  for (const row of rejected || []) {
    for (const [id, entry] of buf) {
      const named = row.temp_id ? entry.tempId === row.temp_id : id === row.id
      if (named && entry.op === row.op) {
        next.set(id, { ...entry, reason: row.reason })
        break
      }
    }
  }
  return next
}
