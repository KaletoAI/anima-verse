/**
 * The arc-length maths of a server journey (contract § A11) — and nothing else.
 *
 * A journey is a polyline of world points in METRES (`travel.waypoints`) plus
 * ONE number: `travel.progress_m`, the distance already walked along it. There
 * is deliberately no segment index in the payload; it would be a second truth
 * beside `progress_m`. Everything a client needs is therefore a walk along the
 * line, and that walk lives HERE — once — because two places do it: `main.ts`
 * derives the render position of every traveller from a fresh poll, and
 * `npcs.ts` extrapolates it forward on every frame in between.
 *
 * NO IMPORTS, not even a type-only one. The module is plain arithmetic on
 * `[x, z]` number pairs, which is what lets `client3d/scripts/smoke_travel_math.mjs`
 * transpile and load it without a bundler, a DOM or three — the same discipline
 * as `packages/scene-render/src/groundAreas.ts` and `game/walk.ts`. Anything
 * that needs a `THREE.Vector3` builds one from the pair at the call site; the
 * y of a traveller is the ground plane (`GROUND_Y`), never a number from here.
 */

/** A world point in metres, exactly the payload's `[x, z]` shape. */
export type MetrePoint = [number, number];

/**
 * How far apart the server's `progress_m` and the locally extrapolated one may
 * be before the client adopts the server's, in METRES.
 *
 * Absolute since E4: v1 compared "0.5 cells", a unit that no longer exists.
 * Two metres is a bit more than half a step of the 3.4 m/s walk and well below
 * what a segment change between two polls can accumulate — below it the local
 * extrapolation keeps running, so poll jitter never makes a figure stutter.
 */
export const TRAVEL_SNAP_M = 2;

function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** Length of one segment, 0 for anything malformed. */
function segLength(a: MetrePoint, b: MetrePoint): number {
  if (!a || !b) return 0;
  const dx = b[0] - a[0];
  const dz = b[1] - a[1];
  const l = Math.sqrt(dx * dx + dz * dz);
  return Number.isFinite(l) ? l : 0;
}

/** Total length of the polyline in metres; 0 for a one-point or empty line. */
export function polylineLength(points: MetrePoint[] | null | undefined): number {
  if (!points || points.length < 2) return 0;
  let total = 0;
  for (let i = 0; i < points.length - 1; i++) total += segLength(points[i], points[i + 1]);
  return total;
}

/**
 * The § A11 walk: the point `d` metres along the polyline.
 *
 * `d` is clamped into [0, length] first, so neither a payload glitch nor an
 * over-run extrapolation can put a figure before the start or past the end —
 * the cap the plan binds. `null` only when there is no line at all; a
 * degenerate one-point line answers with that point (a journey without a way).
 */
export function pointAtDistance(
  points: MetrePoint[] | null | undefined, d: number
): MetrePoint | null {
  if (!points || !points.length) return null;
  const last = points[points.length - 1];
  if (points.length === 1) return [last[0], last[1]];
  let rest = clampProgress(d, polylineLength(points));
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    const L = segLength(a, b);
    // A zero-length segment is SKIPPED, never entered: `rest <= L` would be
    // true for rest = 0 and the lerp would divide by it (0/0 = NaN, and a NaN
    // position takes the figure out of the picture without a word). The
    // server rounds waypoints to two decimals, so a collapsed pair is a
    // payload the client actually sees.
    if (L <= 0) continue;
    if (rest <= L) {
      const t = rest / L;
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    }
    rest -= L;
  }
  return [last[0], last[1]];
}

/**
 * How coarsely the drawn travel line follows the walker, in METRES.
 *
 * The line is TRIMMED to what is still ahead (see `remainingPoints`) — the
 * part already walked is behind the figure and drawing it promises a way that
 * has been used up. Rebuilding the geometry every frame for that would be a
 * new buffer sixty times a second per traveller, so the trim advances in
 * buckets: five metres, about one and a half seconds of the 3.4 m/s walk, and
 * a length one cannot mistake for the figure standing still.
 */
export const TRIM_BUCKET_M = 5;

/**
 * Which trim bucket a walked distance falls into.
 *
 * Part of the drawn line's IDENTITY (`npcs.ts` puts it in the travel key), so
 * the geometry is rebuilt exactly when the bucket rolls over. Anything that is
 * not a positive finite number is bucket 0 — the untrimmed whole line, which
 * is what a journey that has not said how far it has come deserves.
 */
export function trimBucket(progressM: number): number {
  if (!isNum(progressM) || progressM <= 0) return 0;
  return Math.floor(progressM / TRIM_BUCKET_M);
}

/**
 * The polyline that is still AHEAD: the point `progressM` metres along the
 * line, followed by every waypoint after it.
 *
 * The first point is `pointAtDistance(points, progressM)` — the walker's own
 * foot point — so the drawn line starts at the figure and not at the place it
 * set off from. A corner the walk has exactly reached is NOT repeated: at
 * `rest === L` the foot point IS that corner, and the tail therefore starts
 * behind it.
 *
 * Degenerate inputs answer with something that draws nothing rather than with
 * a lie: no points at all give an empty list, and a walk that has reached the
 * end gives the single end point (`npcs.ts` draws from two points up).
 */
export function remainingPoints(
  points: MetrePoint[] | null | undefined, progressM: number
): MetrePoint[] {
  if (!points || !points.length) return [];
  const last = points[points.length - 1];
  const tail = (from: number): MetrePoint[] =>
    points.slice(from).map((p) => [p[0], p[1]] as MetrePoint);
  if (points.length === 1) return [[last[0], last[1]]];
  let rest = clampProgress(progressM, polylineLength(points));
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    const L = segLength(a, b);
    if (L <= 0) continue;          // never entered — see `pointAtDistance`
    if (rest <= L) {
      const t = rest / L;
      const foot: MetrePoint = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      return [foot, ...tail(rest >= L ? i + 2 : i + 1)];
    }
    rest -= L;
  }
  return [[last[0], last[1]]];
}

/**
 * Pin a walked distance into [0, total].
 *
 * NaN is the one input that has no place on the line and becomes 0 — the whole
 * reason this exists is that a NaN position removes a figure from the picture
 * without a word. An INFINITE value is not the same thing: it is an over-run
 * and clamps like any other, to the end (or to the start for -Infinity).
 */
export function clampProgress(value: number, totalM: number): number {
  const total = isNum(totalM) && totalM > 0 ? totalM : 0;
  if (typeof value !== 'number' || Number.isNaN(value)) return 0;
  return value < 0 ? 0 : value > total ? total : value;
}

/**
 * One frame of client-side extrapolation: `progress + rate * dt`, capped at
 * the end of the polyline.
 *
 * `rateMS` is METRES PER REAL SECOND — `pace_m_s_real ?? speed_m_s_real` of
 * § A11 — and `null` means "do not extrapolate at all": a frozen world, an
 * arrival already reached, a degenerate segment. Rate 0, a negative rate and
 * any non-finite input mean the same thing, because each of them would be a
 * lie about how fast the figure is moving.
 *
 * The INPUT is clamped before it is advanced, not only afterwards: a payload
 * that hands in a negative `progress_m` starts the frame at the beginning of
 * the line and then walks its `rate * dt` from there.
 */
export function advanceProgress(
  progressM: number, rateMS: number | null | undefined, dt: number, totalM: number
): number {
  const from = clampProgress(progressM, totalM);
  if (!isNum(rateMS) || rateMS <= 0 || !isNum(dt) || dt <= 0) return from;
  return clampProgress(from + rateMS * dt, totalM);
}

/**
 * How far a figure may move TOWARDS its interpolated journey point this frame.
 *
 * The rendered figure does not jump onto the point the polyline says; it walks
 * there, so a poll correction stays a walk. The bound for that walk is the
 * normal pace OR the journey's own, whichever is greater — a fixed walking
 * pace is a brake, not a smoother: `pace_m_s_real` carries the game time
 * factor (§ A11), so on a fast clock the point outruns the figure and it lags
 * behind its own journey the whole way, then teleports on arrival.
 *
 * Never further than `distanceM`, so the step cannot overshoot the point it is
 * correcting towards.
 */
export function catchUpStep(
  distanceM: number, rateMS: number | null | undefined, dt: number, walkSpeedMS: number
): number {
  if (!isNum(distanceM) || distanceM <= 0 || !isNum(dt) || dt <= 0) return 0;
  const walk = isNum(walkSpeedMS) && walkSpeedMS > 0 ? walkSpeedMS : 0;
  const pace = isNum(rateMS) && rateMS > 0 ? rateMS : 0;
  return Math.min(distanceM, Math.max(walk, pace) * dt);
}

/**
 * Does a freshly polled `progress_m` override the locally extrapolated one?
 *
 * Only past `TRAVEL_SNAP_M`. Both numbers are pre-clamped finite metres (the
 * caller runs the payload through `clampProgress`), so this is the plain
 * distance comparison it looks like.
 */
export function shouldSnap(serverM: number, localM: number): boolean {
  return Math.abs(serverM - localM) > TRAVEL_SNAP_M;
}
