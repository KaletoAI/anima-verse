/**
 * WHICH music and WHICH ambience should sound right now — the whole choice,
 * without touching an audio API (stage 4, task 5).
 *
 * `game/audio.ts` plays URL lists and has no opinion about them; this module
 * is the opinion, and it is pure: manifest in, string list out. No DOM, no
 * imports beyond a type, no module state — every rule below is checked with
 * hand-computed cases in `scripts/smoke_walk_math.mjs`, which is the only
 * reason a "the music flickers at dusk" bug can be found without listening.
 *
 * The two decisions that need more than a lookup:
 *
 * TIME OF DAY IS HYSTERETIC. `engine.nightFactor` is a continuous 0…1 ramp,
 * so a single threshold would sit exactly where the sun does at dusk and flip
 * back and forth across it — with a 4 s crossfade on every flip. Music
 * therefore switches to night only above `NIGHT_ON` and back to day only below
 * `NIGHT_OFF`; between the two the last decision holds (see `nightForMusic`).
 *
 * TERRAIN IS DEBOUNCED. Walking a cell boundary or panning the camera crosses
 * terrains in a second, and the ambience bed must not restart for a cell one
 * passes through. `terrainSwitch` holds a new terrain for `AMBIENT_HOLD_MS`
 * before it counts; the FIRST terrain of a session is taken immediately,
 * because a debounce is there to stop flapping, not to open with silence.
 *
 * NO SUBSTITUTIONS ANYWHERE. A missing night folder means silence at night,
 * not the day playlist; an unknown terrain means silence, not "the closest
 * one". The folder is user data — playing something the user did not put
 * there for this situation is worse than playing nothing.
 */
import type { Cell } from './walk';

/** What `GET /assets/audio` lists — ready-made URLs, never built from a name
 *  by the client (`app/routes/game_audio.py`). `music` always carries both
 *  buckets; `ambient` carries one key per terrain directory that holds
 *  playable files. */
export interface AudioManifest {
  music: { day: string[]; night: string[] };
  ambient: Record<string, string[]>;
}

/** A world with no audio at all — also what a failed request yields, so a
 *  server without the route is silence and never an exception. */
export function emptyManifest(): AudioManifest {
  return { music: { day: [], night: [] }, ambient: {} };
}

function urls(raw: unknown): string[] {
  return Array.isArray(raw) ? raw.filter((u): u is string => typeof u === 'string' && !!u) : [];
}

/**
 * The parsed response → a complete manifest. Defensive for the same reason
 * `loadPrefs` is: this is the one place where outside data enters, and every
 * consumer downstream may then assume two string lists and a plain object.
 * Anything unexpected becomes an empty list, never an exception.
 */
export function readManifest(raw: unknown): AudioManifest {
  const out = emptyManifest();
  if (typeof raw !== 'object' || raw === null) return out;
  const data = raw as Record<string, unknown>;
  const music = (typeof data.music === 'object' && data.music !== null)
    ? data.music as Record<string, unknown> : {};
  out.music.day = urls(music.day);
  out.music.night = urls(music.night);
  const ambient = (typeof data.ambient === 'object' && data.ambient !== null
    && !Array.isArray(data.ambient)) ? data.ambient as Record<string, unknown> : {};
  for (const [terrain, list] of Object.entries(ambient)) {
    const files = urls(list);
    if (files.length) out.ambient[terrain] = files;
  }
  return out;
}

/** Above this much night, the music becomes night music. */
export const NIGHT_ON = 0.8;
/** Below this much night, it becomes day music again. */
export const NIGHT_OFF = 0.2;

/**
 * The hysteresis: the night state that follows `wasNight` at `factor`
 * (`engine.nightFactor`, 0 = full day … 1 = full night). Strictly outside the
 * band decides, the band itself keeps what was; the comparisons are strict, so
 * standing exactly on a threshold changes nothing.
 */
export function nightForMusic(wasNight: boolean, factor: number): boolean {
  if (factor > NIGHT_ON) return true;
  if (factor < NIGHT_OFF) return false;
  return wasNight;
}

/** The music playlist for this time of day — empty when that bucket is
 *  empty (silence, never the other bucket). */
export function pickMusic(manifest: AudioManifest, night: boolean): string[] {
  return night ? manifest.music.night : manifest.music.day;
}

/**
 * The ambience playlist for a terrain. The terrain comes from the worldmap and
 * the key is a DIRECTORY NAME, so the match is case-insensitive on top of the
 * exact one: `audio/ambient/Forest/` is meant for terrain `forest`. An unknown
 * terrain (and the empty one) is silence.
 */
export function pickAmbient(manifest: AudioManifest, terrain: string): string[] {
  if (!terrain) return [];
  const exact = manifest.ambient[terrain];
  if (exact) return exact;
  const wanted = terrain.toLowerCase();
  for (const [key, list] of Object.entries(manifest.ambient)) {
    if (key.toLowerCase() === wanted) return list;
  }
  return [];
}

/** The two camera modes of the client (`hud/bus.ts`). */
export type ViewMode = 'overview' | 'embodied';

/** Terrain of a grid cell, as the caller knows it — `main.ts` reads it off the
 *  tile that stands there, so a tile rebuilt with a new terrain takes effect
 *  without any cache here. */
export type TerrainAt = (cell: Cell) => string;

/**
 * WHOSE surroundings one hears: embodied it is the ground the avatar stands
 * on, in the overview the cell the camera looks at. Both cells may be missing
 * (no figure yet, nothing under the camera) — that is silence, not a fallback
 * to the other one: hearing the avatar's forest while looking at the coast is
 * exactly the confusion this split avoids.
 *
 * The result is normalised (trimmed, lower case) so the directory match has
 * one shape to deal with.
 */
export function ambientTerrainFor(
  mode: ViewMode,
  avatarCell: Cell | null,
  cameraCell: Cell | null,
  terrainAt: TerrainAt,
): string {
  const cell = mode === 'embodied' ? avatarCell : cameraCell;
  if (!cell) return '';
  return (terrainAt(cell) || '').trim().toLowerCase();
}

/** How long a new terrain has to hold before the ambience follows it. Long
 *  enough to walk through a corner cell without the bed restarting, short
 *  enough that arriving somewhere sounds like arriving. */
export const AMBIENT_HOLD_MS = 5000;

/**
 * The debounce state: what is playing (`applied`), what is trying to take over
 * (`pending`) and since when. `started` separates "nothing playing yet" from
 * "silence is what holds" — the first terrain of a session skips the hold.
 */
export interface TerrainSwitch {
  applied: string;
  pending: string;
  since: number;
  started: boolean;
}

export function newTerrainSwitch(): TerrainSwitch {
  return { applied: '', pending: '', since: 0, started: false };
}

/**
 * One step of the debounce: the state that follows `state` when `candidate` is
 * what one hears at `nowMs`. The caller plays `applied` whenever it changed.
 *
 * - nothing has ever played and there IS a terrain → take it at once;
 * - the candidate is what already plays → the hold is cancelled;
 * - a new candidate → the hold starts now;
 * - the same candidate for `holdMs` → it takes over;
 * - otherwise nothing changes (the same object comes back).
 */
export function terrainSwitch(state: TerrainSwitch, candidate: string, nowMs: number,
                              holdMs: number = AMBIENT_HOLD_MS): TerrainSwitch {
  if (!state.started) {
    if (!candidate) return state;
    return { applied: candidate, pending: candidate, since: nowMs, started: true };
  }
  if (candidate === state.applied) {
    return { applied: state.applied, pending: state.applied, since: nowMs, started: true };
  }
  if (candidate !== state.pending) {
    return { applied: state.applied, pending: candidate, since: nowMs, started: true };
  }
  if (nowMs - state.since >= holdMs) {
    return { applied: candidate, pending: candidate, since: nowMs, started: true };
  }
  return state;
}
