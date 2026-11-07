/**
 * The open dropdown panels of the top bar, as ONE ordered list (oldest first).
 *
 * The panels hang below the top bar side by side, left to right in the order
 * they were opened. At most `MAX_DROPS` stand at once: opening one more closes
 * the OLDEST, so the newest is always the one the player just asked for. Pure
 * functions on a plain array, so the rule is checkable outside React and the
 * open state never needs a second store next to the order.
 */
export const MAX_DROPS = 3;

/** Open `id` at the right end; already open = unchanged (it keeps its place). */
export function openDrop<T>(list: readonly T[], id: T, max = MAX_DROPS): T[] {
  if (list.includes(id)) return list as T[];
  const next = [...list, id];
  return next.length > max ? next.slice(next.length - max) : next;
}

export function closeDrop<T>(list: readonly T[], id: T): T[] {
  return list.includes(id) ? list.filter((x) => x !== id) : list as T[];
}

export function toggleDrop<T>(list: readonly T[], id: T, max = MAX_DROPS): T[] {
  return list.includes(id) ? closeDrop(list, id) : openDrop(list, id, max);
}

/** Storage key of the widths the player dragged, per panel id. */
export const DROP_WIDTHS_KEY = 'av3d.dropWidths.v1';
/** Narrower than this and MindPanel folds its navigation to bare icons; wider
 *  and one dropdown is most of a laptop screen. A stored value outside the
 *  range is dropped rather than honoured. */
export const DROP_MIN = 280;
export const DROP_MAX = 720;

/** The stored widths, keeping only well-formed entries — one bad value in
 *  `localStorage` must never make a panel unusable. */
export function readDropWidths(raw: string | null): Record<string, number> {
  if (!raw) return {};
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { return {}; }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
  const out: Record<string, number> = {};
  for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
    if (typeof value === 'number' && Number.isFinite(value)
        && value >= DROP_MIN && value <= DROP_MAX) out[id] = Math.round(value);
  }
  return out;
}
