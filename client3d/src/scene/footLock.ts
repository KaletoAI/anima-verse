/**
 * Foot-contact root motion — the TypeScript twin of
 * `app/blender/scripts/_root_motion.py` (the importer's copy). The two must
 * answer alike: `scripts/fixtures/root_motion_cases.json` holds hand-derived
 * cases both `scripts/smoke_root_motion_math.py` and
 * `client3d/scripts/smoke_foot_lock_math.mjs` check. Change one side, change
 * the other and the fixture with it.
 *
 * Frame: clip frame, Y up, +Z forward, +X the figure's left, centimetres.
 * Input tracks are IN PLACE (the hips' XZ stripped) — a foot planted in the
 * world slides backwards here by exactly the travel the path rebuilds.
 *
 * A point in FULL contact outranks a half-planted one: while any point is
 * fully planted, only the fully planted points steer the root; partial
 * weights steer only when nothing is fully planted (the Python module
 * docstring has the reasoning).
 *
 * Pure: no three, no DOM.
 */

/** Height above a point's own ground at which contact fades out, cm. */
export const BAND_LO_CM = 2.0;
export const BAND_HI_CM = 5.0;
/** Vertical speed at which contact fades out, cm/s. */
export const VY_LO_CM_S = 15.0;
export const VY_HI_CM_S = 30.0;
/** Percentile of a point's heights taken as its ground. */
export const GROUND_PCT = 0.05;
/** Below this summed weight a frame has no planted point. */
export const MIN_WEIGHT = 1e-3;
/** A frame pair at or above this weight counts as FULL contact. */
export const FULL = 0.999;
/** Ankle and ball of each foot: one rigid foot, two points. */
export const CONTACT_POINTS = ['LeftFoot', 'LeftToeBase', 'RightFoot', 'RightToeBase'] as const;

export type Vec3 = [number, number, number];
export type Tracks = Record<string, Vec3[]>;

/** 1 at or below `lo`, 0 at or above `hi`, linear in between; NaN → 0. */
export function ramp(v: number, lo: number, hi: number): number {
  if (!Number.isFinite(v)) return 0;
  if (v <= lo) return 1;
  if (v >= hi) return 0;
  return (hi - v) / (hi - lo);
}

const finite = (p: Vec3 | undefined): p is Vec3 =>
  !!p && Number.isFinite(p[0]) && Number.isFinite(p[1]) && Number.isFinite(p[2]);

/**
 * Per point the height it rests at when planted: the low percentile of its
 * own heights, but never above its height in the rig's rest pose plus
 * `liftTolCm` (0 = the importer's rule; the client passes
 * `footLockMeasure.GROUND_LIFT_TOL_CM` for adapted clips).
 */
export function groundHeights(tracks: Tracks, restHeights: Record<string, number>,
                              liftTolCm = 0): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [name, pts] of Object.entries(tracks)) {
    const ys = pts.filter(finite).map((p) => p[1]).sort((a, b) => a - b);
    if (!ys.length) continue;
    const pct = ys[Math.min(ys.length - 1, Math.floor(GROUND_PCT * (ys.length - 1)))];
    out[name] = Math.min(pct, (restHeights[name] ?? Infinity) + liftTolCm);
  }
  return out;
}

/**
 * Per point and frame: how planted it is, 0..1 — height band times
 * vertical-speed band (central difference, one-sided at the ends).
 */
export function contactWeights(tracks: Tracks, ground: Record<string, number>,
                               fps: number): Record<string, number[]> {
  const out: Record<string, number[]> = {};
  for (const [name, pts] of Object.entries(tracks)) {
    const n = pts.length;
    const g = ground[name];
    const w: number[] = [];
    for (let f = 0; f < n; f++) {
      const p = pts[f];
      if (g === undefined || !finite(p)) { w.push(0); continue; }
      const a = Math.max(f - 1, 0);
      const b = Math.min(f + 1, n - 1);
      const vy = b > a && finite(pts[a]) && finite(pts[b])
        ? (pts[b][1] - pts[a][1]) / ((b - a) / fps) : 0;
      w.push(ramp(p[1] - g, BAND_LO_CM, BAND_HI_CM) * ramp(Math.abs(vy), VY_LO_CM_S, VY_HI_CM_S));
    }
    out[name] = w;
  }
  return out;
}

/**
 * Root XZ offset per frame (frame 0 = origin): each step moves the root by
 * the weighted opposite of the planted points' horizontal slide — of the
 * FULLY planted points only, whenever there is one.
 */
export function footLockPath(tracks: Tracks,
                             weights: Record<string, number[]>): Array<[number, number]> {
  const n = Math.max(0, ...Object.values(tracks).map((p) => p.length));
  if (n === 0) return [];
  const path: Array<[number, number]> = [[0, 0]];
  for (let f = 0; f < n - 1; f++) {
    const steps: Array<[number, number, number]> = []; // (pair weight, dx, dz)
    for (const [name, pts] of Object.entries(tracks)) {
      const w = weights[name] ?? [];
      if (f + 1 >= pts.length || f + 1 >= w.length) continue;
      const ws = Math.min(w[f], w[f + 1]);
      if (ws <= 0 || !finite(pts[f]) || !finite(pts[f + 1])) continue;
      steps.push([ws, pts[f + 1][0] - pts[f][0], pts[f + 1][2] - pts[f][2]]);
    }
    const full = steps.filter((s) => s[0] >= FULL);
    const use = full.length ? full : steps;
    const sw = use.reduce((a, s) => a + s[0], 0);
    let [x, z] = path[path.length - 1];
    if (sw >= MIN_WEIGHT) {
      x -= use.reduce((a, s) => a + s[0] * s[1], 0) / sw;
      z -= use.reduce((a, s) => a + s[0] * s[2], 0) / sw;
    }
    path.push([x, z]);
  }
  return path;
}

/**
 * Largest horizontal distance a point travels in the WORLD (track + path)
 * during one unbroken run of full contact, cm. 0 = every planted point stood
 * exactly still.
 */
export function maxPlantedDrift(tracks: Tracks, weights: Record<string, number[]>,
                                path: Array<[number, number]>): number {
  let worst = 0;
  for (const [name, pts] of Object.entries(tracks)) {
    const w = weights[name] ?? [];
    let start: [number, number] | null = null;
    for (let f = 0; f < Math.min(pts.length, w.length, path.length); f++) {
      const p = pts[f];
      if (w[f] >= FULL && finite(p)) {
        const wx = p[0] + path[f][0];
        const wz = p[2] + path[f][1];
        if (!start) start = [wx, wz];
        worst = Math.max(worst, Math.hypot(wx - start[0], wz - start[1]));
      } else {
        start = null;
      }
    }
  }
  return worst;
}
