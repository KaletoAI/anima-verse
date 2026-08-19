/**
 * Local preferences of this browser: the audio volumes and switches (stage 4,
 * task 2) and, at the bottom of the file, the scatter detail distances.
 *
 * These are LOCAL settings, deliberately not world state: they say how loud
 * this machine is, which is nothing the server or another player has an
 * opinion about. So there is no API call here, only a string in
 * `localStorage` under `PREFS_KEY`.
 *
 * Pure like `walk.ts` and `proximity.ts`: no DOM, no import, no module state —
 * `loadPrefs` takes the raw string (or null) the store returned and
 * `savePrefs` returns the string to put back. That is what lets
 * `client3d/scripts/smoke_walk_math.mjs` check the whole fallback behaviour with
 * hand-written cases. The DOM side is two lines in the caller
 * (`localStorage.getItem/setItem`).
 *
 * `loadPrefs` must never throw and never return a half-filled object: the
 * store is user-writable, survives every version of this client and may hold
 * anything at all. Unknown or wrong-typed values fall back FIELD BY FIELD, so
 * one bad slider cannot reset the other six settings.
 */

/** `localStorage` key of the admin's "show all locations" switch — the ONE
 *  setting that decides which worldmap view is fetched (filtered by
 *  `known_locations`, or everything). Only ever honoured for role `admin`: a
 *  stale value in anybody else's browser is ignored, and the server would
 *  answer 403 anyway. It lived in `game/fog.ts` until the veil was struck
 *  (contract v6 Nr. 8) — it was never about the veil, only about which places
 *  arrive. */
export const SHOW_ALL_KEY = 'av3d.showAllLocations';

/** Playback mode for spoken lines. `auto` = follow the server (play when TTS
 *  is enabled there), `on`/`off` = the user has decided. */
export type TtsMode = 'auto' | 'on' | 'off';

/**
 * TWO KINDS OF FIELD, and the menu (E4-T4) treats them differently:
 * the VOLUMES go straight to `AudioEngine.setVolume` as they are dragged, the
 * SWITCHES are only stored. A switch says what should play AT ALL, and that is
 * the business of the music/ambience/speech drivers (stage 4, tasks 5 + 6) —
 * they read these fields (`gameActions.applyAudioPrefs` carries every change
 * to them) and start or stop accordingly. A menu that stopped the music
 * itself would be a second driver fighting the first.
 */
export interface Prefs {
  /** Master volume, multiplied onto every bus. */
  master: number;
  music: number;
  ambient: number;
  tts: number;
  /** play background music at all — read by the music driver */
  musicOn: boolean;
  /** play the ambience bed at all — read by the ambience driver */
  ambientOn: boolean;
  /** speak lines at all — read by the speech driver */
  ttsOn: TtsMode;
}

/** `localStorage` key. Versioned: a future shape change gets a new key
 *  instead of a migration reader. */
export const PREFS_KEY = 'av3d.audio.v1';

/** What a fresh install sounds like: music sits under the ambience, ambience
 *  under speech, and speech is never quieter than it was rendered. */
export const DEFAULT_PREFS: Prefs = {
  master: 0.8,
  music: 0.5,
  ambient: 0.6,
  tts: 1,
  musicOn: true,
  ambientOn: true,
  ttsOn: 'auto',
};

const TTS_MODES: readonly TtsMode[] = ['auto', 'on', 'off'];

/** A volume is taken only if it is a finite number — a numeric string is NOT
 *  a number here, and NaN/Infinity are not finite. What is taken is clamped
 *  to [0,1]; 0 survives, because muting a bus is a setting and not a missing
 *  value. */
function volume(raw: unknown, fallback: number): number {
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return fallback;
  return Math.min(1, Math.max(0, raw));
}

function flag(raw: unknown, fallback: boolean): boolean {
  return typeof raw === 'boolean' ? raw : fallback;
}

/**
 * The stored string → a complete, sane `Prefs`. `null` (nothing stored yet),
 * unparsable text and any JSON value that is not a plain object all give the
 * defaults.
 */
export function loadPrefs(raw: string | null): Prefs {
  let parsed: unknown = null;
  if (raw) {
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = null;
    }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ...DEFAULT_PREFS };
  }
  const p = parsed as Record<string, unknown>;
  return {
    master: volume(p.master, DEFAULT_PREFS.master),
    music: volume(p.music, DEFAULT_PREFS.music),
    ambient: volume(p.ambient, DEFAULT_PREFS.ambient),
    tts: volume(p.tts, DEFAULT_PREFS.tts),
    musicOn: flag(p.musicOn, DEFAULT_PREFS.musicOn),
    ambientOn: flag(p.ambientOn, DEFAULT_PREFS.ambientOn),
    ttsOn: TTS_MODES.includes(p.ttsOn as TtsMode)
      ? (p.ttsOn as TtsMode) : DEFAULT_PREFS.ttsOn,
  };
}

/** `Prefs` → the string to store. Plain JSON, so the round trip
 *  `loadPrefs(savePrefs(p))` returns `p` unchanged for any valid `p`. */
export function savePrefs(p: Prefs): string {
  return JSON.stringify({
    master: p.master,
    music: p.music,
    ambient: p.ambient,
    tts: p.tts,
    musicOn: p.musicOn,
    ambientOn: p.ambientOn,
    ttsOn: p.ttsOn,
  });
}

/* ==========================================================================
 * THE SCATTER DETAIL DISTANCES (per-object scatter LOD, 2026-08-15)
 * ========================================================================== */

/**
 * How far away a scattered prop drops to the cheap mesh and when it stops
 * being drawn — three metre values, and a LOCAL setting for the same reason
 * the volumes are one: they say what this machine can draw, which is nothing
 * the server or another player has an opinion about.
 *
 * Its OWN storage key, like the performance readout and the minimap switch in
 * `Hud.tsx`: `PREFS_KEY` is versioned as the AUDIO prefs, and a view setting
 * has no business in there.
 *
 * The field names carry the `scatter` prefix although the object holds nothing
 * else — they are what is written into the store, and a store key called
 * `nearM` would be unreadable next to whatever the next view setting brings.
 * `scatterLodCfgOf` turns them into the `ScatterLodCfg` the maths wants.
 */
export interface ScatterPrefs {
  scatterNearM: number;
  scatterFarM: number;
  scatterCullM: number;
}

/** `localStorage` key. Versioned like `PREFS_KEY`, and separate from it. */
export const SCATTER_PREFS_KEY = 'av3d.view.scatter.v1';

/** What a distance may be at all (metres). The lower end keeps a typo from
 *  culling the ground the player stands on; the upper end is far past any
 *  view distance this client draws, and exists so a pasted 1e9 cannot ask the
 *  LOD tick to keep an entire continent at the full mesh. */
export const SCATTER_PREF_MIN_M = 5;
export const SCATTER_PREF_MAX_M = 2000;

/** The same three numbers as `SCATTER_LOD_DEFAULTS` in
 *  `scene/scatterLod.ts` — written out rather than imported, because this
 *  module has no imports (see the header) and the smoke check pins the two
 *  against each other so they cannot drift apart. */
export const DEFAULT_SCATTER_PREFS: ScatterPrefs = {
  scatterNearM: 35,
  scatterFarM: 45,
  scatterCullM: 120,
};

/** A distance out of range is CLAMPED, never refused: a player who types 3000
 *  wants "as far as it goes", not the default back. */
function clampM(v: number): number {
  return Math.min(SCATTER_PREF_MAX_M, Math.max(SCATTER_PREF_MIN_M, v));
}

/** A stored distance is taken only if it is a finite NUMBER — same rule as
 *  `volume`, and a numeric string is not a number here either. */
function distanceM(raw: unknown, fallback: number): number {
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return fallback;
  return clampM(raw);
}

/** near < far < cull, strictly. Equal values are refused too: a band of zero
 *  width is no hysteresis, and `far === cull` would leave the thinning line no
 *  metres to fall over. */
export function scatterPrefsOrdered(p: ScatterPrefs): boolean {
  return p.scatterNearM < p.scatterFarM && p.scatterFarM < p.scatterCullM;
}

/**
 * What a menu learns about the three numbers a player typed: either the
 * finished prefs, or WHY they were not taken — the menu shows a hint and
 * keeps the old values.
 *
 * `'number'` is an empty or unparsable field (a number input hands NaN in),
 * `'order'` a triple that does not climb. Note that the order is checked on
 * the CLAMPED values, so 2500 and 3000 collide at the ceiling and are refused
 * as unordered rather than silently becoming the same distance twice.
 */
export type ScatterPrefsCheck =
  | { ok: true; prefs: ScatterPrefs }
  | { ok: false; error: 'number' | 'order' };

export function checkScatterPrefs(
  near: unknown, far: unknown, cull: unknown,
): ScatterPrefsCheck {
  const metres: number[] = [];
  for (const raw of [near, far, cull]) {
    if (typeof raw !== 'number' || !Number.isFinite(raw)) {
      return { ok: false, error: 'number' };
    }
    metres.push(clampM(raw));
  }
  const prefs: ScatterPrefs = {
    scatterNearM: metres[0],
    scatterFarM: metres[1],
    scatterCullM: metres[2],
  };
  if (!scatterPrefsOrdered(prefs)) return { ok: false, error: 'order' };
  return { ok: true, prefs };
}

/**
 * The stored string → three usable distances. Never throws, never returns
 * half a setting — the same contract as `loadPrefs`, and for the same reason.
 *
 * Field by field first, exactly like the volumes. But then the TRIPLE is
 * checked as a whole and falls back completely if it does not climb: unlike a
 * volume, these three numbers only mean anything together, and a stored
 * `near` of 100 next to the default `far` of 45 would leave the band inverted
 * — the LOD would still answer, it would just answer nonsense forever.
 */
export function loadScatterPrefs(raw: string | null): ScatterPrefs {
  let parsed: unknown = null;
  if (raw) {
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = null;
    }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ...DEFAULT_SCATTER_PREFS };
  }
  const p = parsed as Record<string, unknown>;
  const prefs: ScatterPrefs = {
    scatterNearM: distanceM(p.scatterNearM, DEFAULT_SCATTER_PREFS.scatterNearM),
    scatterFarM: distanceM(p.scatterFarM, DEFAULT_SCATTER_PREFS.scatterFarM),
    scatterCullM: distanceM(p.scatterCullM, DEFAULT_SCATTER_PREFS.scatterCullM),
  };
  return scatterPrefsOrdered(prefs) ? prefs : { ...DEFAULT_SCATTER_PREFS };
}

/** `ScatterPrefs` → the string to store, so that
 *  `loadScatterPrefs(saveScatterPrefs(p))` returns `p` for any ordered `p`. */
export function saveScatterPrefs(p: ScatterPrefs): string {
  return JSON.stringify({
    scatterNearM: p.scatterNearM,
    scatterFarM: p.scatterFarM,
    scatterCullM: p.scatterCullM,
  });
}

/** The stored shape → the `ScatterLodCfg` the LOD maths takes. Structural, not
 *  an imported type: this module stays import-free, and the field names are
 *  what the two sides agree on. */
export function scatterLodCfgOf(p: ScatterPrefs): {
  nearM: number; farM: number; cullM: number;
} {
  return { nearM: p.scatterNearM, farM: p.scatterFarM, cullM: p.scatterCullM };
}
