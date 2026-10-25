/** Bench anchor selection: pure, no DOM and no three.
 *
 *  The position comes from the WORLDMAP location rows (`/play/worldmap →
 *  locations`), which are authoritative for placement; `/world/locations`
 *  rows carry no position and only lend a name to a worldmap row without one.
 *  Preference: `&goto=` → the avatar's current location → world origin. */
import type { Vec3 } from './benchPath';

/** The slice of a worldmap location row the anchor reads. */
export interface AnchorRow {
  id: string;
  name?: string | null;
  pos_x?: number | null;
  pos_z?: number | null;
}

export interface BenchAnchor {
  pos: Vec3;
  locationId: string | null;
  heightSource: string;
}

export interface AnchorInput {
  /** The raw `&goto=` value; empty/absent = no explicit pick. */
  goto?: string | null;
  /** Location rows of the CURRENT worldmap snapshot. */
  rows: readonly AnchorRow[];
  /** Fallback display name for a row that carries none (e.g. from `/world/locations`). */
  nameOf?: (id: string) => string | undefined;
  /** The avatar's current location id, if any. */
  currentId?: string | null;
  /** Ground height at a world position. */
  heightAt: (x: number, z: number) => number;
  /** Label of the height rule, reported with a placed anchor. */
  heightSource: string;
}

/** `pos_x`/`pos_z` null, undefined or non-finite = unplaced. */
export function isPlaced(row: AnchorRow): row is AnchorRow & {pos_x: number; pos_z: number} {
  return Number.isFinite(row.pos_x) && Number.isFinite(row.pos_z);
}

/** `&goto=` match: an exact id (case-insensitive) anywhere in the list beats a
 *  case-insensitive name substring. */
export function matchGoto(rows: readonly AnchorRow[], goto: string,
  nameOf?: (id: string) => string | undefined): AnchorRow | undefined {
  const q = goto.toLowerCase();
  return rows.find(r => r.id.toLowerCase() === q)
    ?? rows.find(r => (r.name || nameOf?.(r.id) || '').toLowerCase().includes(q));
}

export function pickBenchAnchor(input: AnchorInput): BenchAnchor {
  const goto = input.goto?.trim();
  const row = goto
    ? matchGoto(input.rows, goto, input.nameOf)
    : input.currentId ? input.rows.find(r => r.id === input.currentId) : undefined;
  if (goto && (!row || !isPlaced(row))) {
    throw new Error(`Bench goto location is unknown or unplaced: ${goto}`);
  }
  if (!row || !isPlaced(row)) return {pos: [0, 0, 0], locationId: null, heightSource: 'world origin'};
  return {pos: [row.pos_x, input.heightAt(row.pos_x, row.pos_z), row.pos_z],
    locationId: row.id, heightSource: input.heightSource};
}
