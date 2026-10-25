/** Keep tint in sRGB while easing; the caller converts it to Three's working colour space. */
export interface Ambience {
  daylight: number;
  tint: [number, number, number];
}

/** Missing room ambience must restore neutral lighting when leaving a tinted room. */
export function ambienceTarget(a?: { daylight: number; tint: string | null }): Ambience {
  const hex = a?.tint;
  return {
    daylight: a?.daylight ?? 1,
    tint: hex
      ? [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255) as Ambience['tint']
      : [1, 1, 1],
  };
}

/** Exponential easing with a half-second time constant keeps transitions independent of frame rate. */
export function stepAmbience(cur: Ambience, target: Ambience, dt: number): Ambience {
  const k = 1 - Math.exp(-dt / .5);
  return {
    daylight: cur.daylight + (target.daylight - cur.daylight) * k,
    tint: cur.tint.map((v, i) => v + (target.tint[i] - v) * k) as Ambience['tint'],
  };
}

/**
 * How deep in the night the world clock stands: 0 = bright day, 1 = deep night
 * (`Engine.nightFactor` — the gate of night lamps, window glow and the night
 * music). The sun arc of `Engine.setGameHour`: hour h (wrapped into 0..24)
 * puts the sun at ((h − 6) / 12)·π, `day` = clamp(sin(angle), 0, 1), and the
 * night is clamp(1 − 3·day, 0, 1) — full night until the sun is a third of
 * the way up its sine.
 */
export function nightFactorAt(hour: number): number {
  const h = ((hour % 24) + 24) % 24;
  const day = Math.min(Math.max(Math.sin(((h - 6) / 12) * Math.PI), 0), 1);
  return Math.min(Math.max(1 - day * 3, 0), 1);
}
