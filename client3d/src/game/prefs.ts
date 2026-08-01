/**
 * Audio preferences — volumes and switches, stored locally in the browser
 * (stage 4, task 2).
 *
 * These are LOCAL settings, deliberately not world state: they say how loud
 * this machine is, which is nothing the server or another player has an
 * opinion about. So there is no API call here, only a string in
 * `localStorage` under `PREFS_KEY`.
 *
 * Pure like `walk.ts` and `proximity.ts`: no DOM, no import, no module state —
 * `loadPrefs` takes the raw string (or null) the store returned and
 * `savePrefs` returns the string to put back. That is what lets
 * `scripts/smoke_walk_math.mjs` check the whole fallback behaviour with
 * hand-written cases. The DOM side is two lines in the caller
 * (`localStorage.getItem/setItem`).
 *
 * `loadPrefs` must never throw and never return a half-filled object: the
 * store is user-writable, survives every version of this client and may hold
 * anything at all. Unknown or wrong-typed values fall back FIELD BY FIELD, so
 * one bad slider cannot reset the other six settings.
 */

/** Playback mode for spoken lines. `auto` = follow the server (play when TTS
 *  is enabled there), `on`/`off` = the user has decided. */
export type TtsMode = 'auto' | 'on' | 'off';

export interface Prefs {
  /** Master volume, multiplied onto every bus. */
  master: number;
  music: number;
  ambient: number;
  tts: number;
  musicOn: boolean;
  ambientOn: boolean;
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
