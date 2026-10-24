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
