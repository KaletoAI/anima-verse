/**
 * THE SHADOW CAMERA'S TEXEL GRID — why the sun's frustum may only move in whole
 * shadow-map texels (finding round 2026-08-21).
 *
 * The sun in `scene/engine.ts` is not a world light: it follows the camera
 * target, so a 140 m shadow map can serve a world of kilometres. That is right
 * and stays — but until this round the frustum followed the target CONTINUOUSLY,
 * and a shadow map is a raster. Move a raster by a third of a texel and every
 * depth sample lands on a different piece of the world: the shadow edge of a
 * figure, a fence or a roof jitters along its own outline, one texel wide, on
 * every frame the camera pans. That is "shadow swimming", and it is a defect of
 * the SAMPLING, not of the bias — a smaller bias only sharpens the crawl.
 *
 * THE FIX IS THE STANDARD ONE: quantise the frustum's centre to the texel grid
 * of the light's own view. Then a pan that is smaller than a texel does not move
 * the raster at all, and a bigger one moves it by whole texels — every world
 * point keeps falling into the SAME texel it fell into before, so the shadow
 * edge stands still and the map still travels with the player.
 *
 * ONE TEXEL, HAND-DERIVED. The frustum is `SHADOW_HALF_M` = 70 m to each side,
 * i.e. 140 m across, over `SHADOW_MAP_PX` = 2 048 texels:
 *
 *     140 / 2048 = 0.068359375 m — 6.8 cm of ground per shadow texel.
 *
 * (An exact binary fraction, because both numbers are powers of two times a
 * small integer; nothing here rounds twice.)
 *
 * WHAT IS *NOT* SNAPPED is the light's distance along its own axis. Depth is
 * quantised in the texel's VALUE, not in its position, so moving the near plane
 * by a centimetre does not resample anything; the depth bias
 * (`sun.shadow.bias`) owns that end.
 *
 * The arithmetic lives here, on plain numbers and away from three, so
 * `scripts/smoke_shadow_snap.mjs` can measure the shipped rule rather than a
 * copy of it.
 */

/** Half the width of the sun's orthographic shadow frustum, metres. 70 m to
 *  each side covers the 150 m the camera may zoom out to plus the figures at
 *  its rim; it is the number `engine.ts` has always used, now named because the
 *  texel size is derived from it. */
export const SHADOW_HALF_M = 70;

/** Shadow map resolution per axis, texels — `sun.shadow.mapSize`. */
export const SHADOW_MAP_PX = 2048;

/** Metres of ground per shadow texel: the frustum width over the map width.
 *  0.068359375 m for the numbers above. */
export function shadowTexelM(halfM: number = SHADOW_HALF_M,
                             mapPx: number = SHADOW_MAP_PX): number {
  if (!(mapPx > 0)) return 0;
  return (2 * halfM) / mapPx;
}

/** A point in world metres, as three numbers — the tuple this module speaks so
 *  it can be checked without a vector class. */
export type Vec3 = readonly [number, number, number];

/** What `snapShadowCentre` has to be told. `offset` is the light's position
 *  MINUS its target (`engine.ts` keeps it constant per sun angle), which is
 *  what fixes the light's view axes. */
export interface ShadowSnapOpts {
  /** Where the frustum wants to be centred — the camera target. */
  target: Vec3;
  /** Light position − target, any length. */
  offset: Vec3;
  /** Half the frustum width, metres (`SHADOW_HALF_M`). */
  halfM?: number;
  /** Shadow map texels per axis (`SHADOW_MAP_PX`). */
  mapPx?: number;
}

function dot(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function cross(a: Vec3, b: Vec3): [number, number, number] {
  return [a[1] * b[2] - a[2] * b[1],
          a[2] * b[0] - a[0] * b[2],
          a[0] * b[1] - a[1] * b[0]];
}

function normalize(v: Vec3): [number, number, number] {
  const len = Math.hypot(v[0], v[1], v[2]);
  if (!(len > 0)) return [0, 0, 1];
  return [v[0] / len, v[1] / len, v[2] / len];
}

/**
 * The light's own view basis, three's `Matrix4.lookAt` written out.
 *
 * A camera looks down its −Z, so `zAxis` points FROM the target TO the light —
 * i.e. along `offset` — and the two remaining axes are the shadow map's own u
 * and v. The world up (0, 1, 0) is the reference three uses; when the light
 * stands within a thousandth of straight overhead the cross product degenerates
 * and +Z takes over as the reference, exactly as `Object3D.lookAt` guards it.
 */
export function lightBasis(offset: Vec3): { x: Vec3; y: Vec3; z: Vec3 } {
  const z = normalize(offset);
  let x = cross([0, 1, 0], z);
  if (Math.hypot(x[0], x[1], x[2]) < 1e-3) x = cross([0, 0, 1], z);
  const xn = normalize(x);
  return { x: xn, y: cross(z, xn), z };
}

/**
 * The frustum centre the sun may really use: `target`, moved by less than one
 * texel so that its light-space u and v are whole multiples of the texel size.
 *
 * The shift is applied IN THE LIGHT'S OWN PLANE (`x`/`y` of `lightBasis`), so
 * the light keeps looking at the same piece of ground from the same direction;
 * only the raster underneath it stops sliding. The caller moves the light
 * position by the same vector — the offset is constant, so both stay put
 * relative to each other.
 *
 * The displacement is bounded by half a texel per axis, i.e. at most
 * √2 · 0.0342 m = 4.8 cm of frustum travel — nothing a 140 m frustum notices.
 */
export function snapShadowCentre(o: ShadowSnapOpts): [number, number, number] {
  const texel = shadowTexelM(o.halfM ?? SHADOW_HALF_M, o.mapPx ?? SHADOW_MAP_PX);
  if (!(texel > 0)) return [o.target[0], o.target[1], o.target[2]];
  const b = lightBasis(o.offset);
  const u = dot(o.target, b.x);
  const v = dot(o.target, b.y);
  const du = Math.round(u / texel) * texel - u;
  const dv = Math.round(v / texel) * texel - v;
  return [o.target[0] + du * b.x[0] + dv * b.y[0],
          o.target[1] + du * b.x[1] + dv * b.y[1],
          o.target[2] + du * b.x[2] + dv * b.y[2]];
}
