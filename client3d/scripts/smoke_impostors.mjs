#!/usr/bin/env node
/**
 * Smoke check for the FAR IMPOSTORS of the ground scatter — the render stage
 * that draws a wood beyond the cull line as billboards
 * (`client3d/src/scene/scatterLod.ts`, the `IMPOSTOR_*` half; the GPU side is
 * `client3d/src/scene/impostors.ts`).
 *
 * Usage:  node client3d/scripts/smoke_impostors.mjs
 *
 * Same discipline as `smoke_scatter_math.mjs` and `smoke_occlusion.mjs`: every
 * expected number below is derived BY HAND in this header and never recorded
 * from the current output. `scatterLod.ts` has no import (see its header), so a
 * plain esbuild transpile is enough — no bundler, no three.
 *
 * WHAT IS NOT CHECKED HERE, and it is a stated limit rather than an oversight:
 * the offscreen BAKE itself. It needs a GPU and a WebGL context; what a texture
 * looks like is a matter for the visual acceptance. What CAN be checked without
 * one is everything that decides geometry — the window, the thinning, the yaw
 * and the quad — and all of it lives in the import-free module for exactly that
 * reason. The wiring that connects the two is pinned against the source text in
 * section (F), the way `smoke_occlusion.mjs` pins its callers.
 *
 * ============================================================================
 * (A) THE WINDOW — where the meshes stop, the billboards start
 * ============================================================================
 * The mesh LOD hides an instance beyond `cullM` (120 m by default); the stage
 * runs from there to `IMPOSTOR_FAR_M` = 400 m. The window is OPEN at the near
 * end and CLOSED at the far one, which is exactly the complement of what
 * `instanceTier` draws — one line, two representations, never both:
 *
 *   119.9 m -> no billboard (the mesh has it)
 *   120.0 m -> no billboard (`instanceTier` hides only ABOVE cullM)
 *   120.1 m -> billboard
 *   400.0 m -> billboard, the very edge
 *   400.1 m -> nothing at all
 *
 * (A5) A CULL DISTANCE PUSHED PAST THE STAGE. The menu lets a player set the
 * cull out to 2000 m (`game/prefs.ts`). With cullM = 500 the window is
 * `(500, 400]` — empty, and it must come out empty rather than inverted: the
 * meshes then simply reach further than the stage that exists to replace them.
 *
 * ============================================================================
 * (B) THE THINNING — flat 1 at the cull line, a quarter at 400 m
 * ============================================================================
 * A straight line over the stage's OWN span, `1 → IMPOSTOR_MIN_SHARE` (0.25)
 * over `cullM → 400`. With the default cull of 120 the span is 280 m, so
 *
 *   share(d) = 1 − ((d − 120) / 280) · 0.75
 *
 *   260 m: (260−120)/280 = 0.5    -> 1 − 0.375  = 0.625
 *   190 m: (190−120)/280 = 0.25   -> 1 − 0.1875 = 0.8125
 *   400 m: 1                      -> 0.25       (the floor, at the very edge)
 *   120 m and nearer: 0 — outside the window there is no share at all.
 *
 * (B4) THE SETS NEST, and that is what makes the swap invisible. Both
 * thinnings pick by `instanceHash(index)`, so an instance drawn as a MESH just
 * inside the line (share 0.25 there) is drawn as a BILLBOARD just outside it
 * (share 1). Checked over 1000 indices: mesh-visible at 119 m implies
 * impostor-visible at 121 m, without exception. The reverse does not hold, and
 * that is the honest cost of two spans: crossing the line outward the wood
 * gets FULLER (billboards are cheap, meshes are not). Nothing moves while it
 * happens, which is the property that matters.
 *
 * ============================================================================
 * (C) THE QUAD — a bake frame, and what it becomes in the world
 * ============================================================================
 * A prop model 4 m tall whose horizontal reach from its own origin is 1 m,
 * baked with the camera raised by 10° and 5 % of padding
 * (`IMPOSTOR_ELEV_RAD`, `IMPOSTOR_BAKE_PAD`):
 *
 *   halfW = 1.0 · 1.05                                  = 1.05
 *   halfH = ((4/2)·cos10° + 1.0·sin10°) · 1.05
 *         = (1.969615506… + 0.173648177…) · 1.05        = 2.250426867875914
 *   spanH = 2·halfH / 4                                 = 1.125213433937957
 *   aspect = halfW / halfH                              = 0.46657814790091456
 *
 * The depth term in `halfH` is not decoration: the image's up axis is
 * (0, cos e, −sin e), so a point at the box's rim contributes its DEPTH as
 * well, and without it the raised camera would cut the crown off.
 *
 * (C2) THE SAME PROP SCATTERED AT 8 m (the entry's `targetH` — the very number
 * the mesh is scaled to, which is what makes the swap a swap and not a jump in
 * size):
 *   h = 8 · 1.125213433937957 = 9.001707471503655
 *   w = h · 0.46657814790091456 = 4.2   — and 4.2 is derivable a second way,
 *       2·halfW · (8/4) = 2·1.05·2, which is the check that the two ratios
 *       really describe ONE frame.
 *   centreY = 8 · cos10° / 2 = 3.939231012048832
 *
 * (C3) THE FOOT IS ON THE GROUND. In the image the model's base sits
 * (height/2)·cos e below the image centre, so the quad centre has to stand
 * `targetH·cos e / 2` above the instance's ground point — which is exactly
 * `centreY`, i.e. the foot lands at y = 0 of the point the instance sits on.
 * The quad's BOTTOM EDGE lies below that, at 3.939231… − 4.500853… =
 * −0.5616227237029956: that is the transparent air the padding bought, and the
 * check that the padding is NOT what carries the foot.
 *
 * (C4) …and it must stay there when the padding changes. A frame with twice
 * the vertical span (a hypothetical fatter pad) gives twice the quad height
 * and the SAME `centreY` — the foot cannot move because somebody changed how
 * much air the bake keeps.
 *
 * (C5) A DEGENERATE MODEL (no height, no width, junk) gets NO frame: `null`,
 * and the caller then bakes nothing at all. A quad scaled by an infinity would
 * be a white flash across the map.
 *
 * ============================================================================
 * (D) THE BILLBOARD ITSELF — the four corners, by hand
 * ============================================================================
 * The quad of (C2) at the world origin, i.e. centre (0, 3.939231…, 0),
 * w = 4.2, h = 9.001707…
 *
 * (D1) CAMERA DUE +X, at (200, 60, 0). yaw = atan2(200−0, 0−0) = π/2, so the
 * quad's own +X axis (cos yaw, 0, −sin yaw)·(w/2) is (0, 0, −2.1): the quad
 * lies in the plane x = 0 and faces the camera. Corners, in the order
 * bottom-left, bottom-right, top-right, top-left:
 *   (0, −0.5616227237029956, +2.1)
 *   (0, −0.5616227237029956, −2.1)
 *   (0, +8.44008474780066,   −2.1)
 *   (0, +8.44008474780066,   +2.1)
 *
 * (D2) CAMERA ON THE DIAGONAL, at (100, 80, 100). yaw = atan2(100, 100) = π/4,
 * so w/2 · (cos45°, 0, −sin45°) = (1.48492424049175, 0, −1.48492424049175):
 * the corners move off the axes and the quad's own edge stands perpendicular
 * to the line of sight — checked as a dot product of 0 with the HORIZONTAL
 * camera direction.
 *
 * (D3) THE ONE PROPERTY THAT MUST NEVER BE LOST: it is a Y billboard. Every
 * corner keeps the y of its edge — the two bottom corners at −0.5616227…, the
 * two top ones at 8.4400847… — and those numbers do not move when the camera
 * climbs from y = 5 to y = 500. A tree stands upright whatever one looks at it
 * from.
 *
 * (D4) THE RED COUNTER-CHECK: A FULL BILLBOARD. Built here by hand, the way
 * one would if one "fixed" the quads to face the camera outright: view
 * direction v = normalize(cam − centre), right r = normalize(worldUp × v), up
 * u = v × r. With the camera at (200, 203.939231…, 0) — exactly 45° above the
 * quad's centre — u is (−cos45°, cos45°, 0), so
 *   the bottom edge rises to 3.939231… − 4.500853… · cos45° = 0.7566468143699092
 *   the top edge sinks to                                     7.121815209727755
 *   and the drawn height collapses from 9.0017… to 9.0017…·cos45° = 6.365168395357846
 * i.e. the tree hangs 0.76 m in the air and is a fifth shorter — the two
 * failures a Y billboard does not have, measured on the y component exactly as
 * the rule says to.
 *
 * ============================================================================
 * (E) THE RED COUNTER-CHECK OF THE WINDOW — one mutant, one double picture
 * ============================================================================
 * The module is transpiled a second time with the near end of the window
 * dropped (`distM > cfg.cullM` becomes `distM > 0`) — the mistake that would
 * draw a billboard AND a mesh for the same instance at 60 m, one inside the
 * other, and nobody would see anything wrong until the fill rate went. The
 * mutant says "billboard" at 60 m where the truth says nothing, and where
 * `instanceTier` is drawing a full mesh.
 *
 * ============================================================================
 * (F) THE WIRING, pinned by reading the source
 * ============================================================================
 * None of this can be called from here — it lives inside closures over fetched
 * payloads and a WebGL context — so it is pinned against the source text:
 *  - `ground.ts` bins the far half BEFORE the entry-wide early-out, or a
 *    distant wood would be switched off whole before its billboards were ever
 *    considered;
 *  - it composes them from `prop.pos`, the array the meshes are binned from —
 *    that identity IS the promise that nothing jumps at the swap;
 *  - `impostors.ts` uses the app's renderer and creates none of its own;
 *  - a bake a billboard mesh is drawing with is CLAIMED, and the claim is
 *    given back with that mesh — the LRU may not free a texture out from under
 *    a live material, which would show a wood of black rectangles;
 *  - the impostor material is NOT patched with the camera corridor: the gate
 *    closes at 25 m and every billboard is beyond 120 m.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const LOD_SRC = join(ROOT, 'client3d/src/scene/scatterLod.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');
const IMP_SRC = join(ROOT, 'client3d/src/scene/impostors.ts');
const MAIN_SRC = join(ROOT, 'client3d/src/main.ts');

/** The module has no runtime import (see its header), so a transpile is all it
 *  takes. Should someone add one, this fails loudly — that is the alarm.
 *
 *  `mutate` rewrites the SOURCE before the transpile: section (E) gets its
 *  wrong module that way, without a second copy of the maths lying around to
 *  rot. */
async function loadTs(src, mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'impostors-'));
  try {
    const original = await readFile(src, 'utf8');
    const source = mutate ? mutate(original) : original;
    if (mutate && source === original) {
      throw new Error('the mutant changed nothing — the counter-check would be vacuous');
    }
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'module.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Section (E)'s mutant: the window loses its near end, so an instance drawn
 *  as a full mesh at 60 m would carry a billboard on top of it. */
function windowWithoutCull(source) {
  return source.replace('return distM > cfg.cullM && distM <= IMPOSTOR_FAR_M;',
                        'return distM > 0 && distM <= IMPOSTOR_FAR_M;');
}

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}

/** Metres to the micrometre: these are ratios of hand-derived cosines, and
 *  comparing raw doubles would only measure the last bit of `Math.cos`. */
const um = (v) => Math.round(v * 1e6) / 1e6;
const um3 = (p) => p.map(um);

async function main() {
  const lod = await loadTs(LOD_SRC);
  const { IMPOSTOR_BAKE_PAD, IMPOSTOR_ELEV_RAD, IMPOSTOR_FAR_M,
    IMPOSTOR_MIN_SHARE, impostorCorners, impostorFrame, impostorInWindow,
    impostorQuad, impostorShare, impostorVisible, impostorYaw, instanceTier,
    instanceVisible, SCATTER_LOD_DEFAULTS } = lod;
  const cfg = SCATTER_LOD_DEFAULTS;   // 35 / 45 / 120, the defaults a player never touches

  console.log('\n(A) the window — where the meshes stop, the billboards start');
  check('the stage ends at 400 m', IMPOSTOR_FAR_M, 400);
  check('…and the meshes end at 120 m', cfg.cullM, 120);
  check('119.9 m is the mesh\'s', impostorInWindow(119.9, cfg), false);
  check('120.0 m still is (the window is OPEN at the near end)',
    impostorInWindow(120, cfg), false);
  check('…and instanceTier really still draws it there',
    instanceTier(120, 1, cfg), 1);
  check('120.1 m is a billboard', impostorInWindow(120.1, cfg), true);
  check('…and instanceTier has let go of it', instanceTier(120.1, 1, cfg), 2);
  check('400.0 m is the edge, and inside it', impostorInWindow(400, cfg), true);
  check('400.1 m is nothing at all', impostorInWindow(400.1, cfg), false);
  check('a non-finite distance draws nothing',
    impostorInWindow(Number.NaN, cfg), false);
  const farCull = { nearM: 35, farM: 45, cullM: 500 };
  check('A5 a cull pushed past the stage empties the window',
    [impostorInWindow(450, farCull), impostorInWindow(300, farCull)],
    [false, false]);
  check('A5 …and its share is 0, not a negative one',
    impostorShare(450, farCull), 0);

  console.log('\n(B) the thinning — 1 at the cull line, a quarter at 400 m');
  check('the floor is a quarter', IMPOSTOR_MIN_SHARE, 0.25);
  check('260 m -> 0.625', um(impostorShare(260, cfg)), 0.625);
  check('190 m -> 0.8125', um(impostorShare(190, cfg)), 0.8125);
  check('400 m -> the floor', um(impostorShare(400, cfg)), 0.25);
  check('120 m -> nothing (outside the window)', impostorShare(120, cfg), 0);
  check('60 m -> nothing either', impostorShare(60, cfg), 0);
  // instance 0 has hash 0 and therefore survives as long as anything does
  check('instance 0 is drawn at the very edge', impostorVisible(0, 400, cfg), true);
  check('…and nothing is drawn beyond it', impostorVisible(0, 401, cfg), false);
  let drawn = 0;
  for (let i = 0; i < 1000; i += 1) if (impostorVisible(i, 260, cfg)) drawn += 1;
  // The hash is uniform to ~3.5 % over 1000 indices (`instanceHash`), so 0.625
  // of 1000 must land near 625 — the band is the mixer's measured quality, not
  // a recorded number.
  check('B3 about 62.5 % of 1000 instances survive at 260 m',
    drawn > 590 && drawn < 660, true);
  let nested = true;
  for (let i = 0; i < 1000; i += 1) {
    if (instanceVisible(i, 119, cfg) && !impostorVisible(i, 121, cfg)) nested = false;
  }
  check('B4 every mesh drawn just inside the line is a billboard just outside it',
    nested, true);

  console.log('\n(C) the quad — a bake frame, and what it becomes in the world');
  check('the bake camera is raised by 10°',
    um(IMPOSTOR_ELEV_RAD), um((10 * Math.PI) / 180));
  check('…and keeps 5 % of air', IMPOSTOR_BAKE_PAD, 1.05);
  const frame = impostorFrame(4, 1);
  check('C1 spanH of a 4 m prop with a 1 m reach',
    um(frame.spanH), um(1.125213433937957));
  check('C1 …and its aspect', um(frame.aspect), um(0.46657814790091456));
  const quad = impostorQuad(8, frame);
  check('C2 the quad of that prop scattered at 8 m', um(quad.h),
    um(9.001707471503655));
  check('C2 …its width, which is 2·halfW·(8/4)', um(quad.w), 4.2);
  check('C2 …and its centre above the ground point', um(quad.centreY),
    um(3.939231012048832));
  check('C3 the FOOT lands on the ground point',
    um(quad.centreY - (8 * Math.cos(IMPOSTOR_ELEV_RAD)) / 2), 0);
  check('C3 …while the quad\'s bottom edge hangs below it (the padding\'s air)',
    um(quad.centreY - quad.h / 2), um(-0.5616227237029956));
  const fatter = impostorQuad(8, { spanH: frame.spanH * 2, aspect: frame.aspect });
  check('C4 twice the padding is twice the quad…', um(fatter.h),
    um(2 * 9.001707471503655));
  check('C4 …and the foot has not moved', um(fatter.centreY), um(quad.centreY));
  check('C5 a degenerate model gets no frame at all',
    [impostorFrame(0, 1), impostorFrame(4, 0), impostorFrame(Number.NaN, 1)],
    [null, null, null]);

  console.log('\n(D) the billboard itself — the four corners, by hand');
  const { w, h, centreY } = quad;
  const corners = (camX, camY, camZ) =>
    impostorCorners(0, centreY, 0, w, h, camX, camZ).map(um3);
  const BOTTOM = um(-0.5616227237029956);
  const TOP = um(8.44008474780066);
  check('D1 camera due +X: yaw', um(impostorYaw(0, 0, 200, 0)), um(Math.PI / 2));
  check('D1 …and the quad stands in the plane x = 0', corners(200, 60, 0), [
    [0, BOTTOM, 2.1],
    [0, BOTTOM, -2.1],
    [0, TOP, -2.1],
    [0, TOP, 2.1],
  ]);
  check('D2 camera on the diagonal: yaw',
    um(impostorYaw(0, 0, 100, 100)), um(Math.PI / 4));
  const R = um(1.48492424049175);
  check('D2 …and the corners turn with it', corners(100, 80, 100), [
    [-R, BOTTOM, R],
    [R, BOTTOM, -R],
    [R, TOP, -R],
    [-R, TOP, R],
  ]);
  const diag = corners(100, 80, 100);
  // The quad's own edge must stand perpendicular to the HORIZONTAL line of
  // sight — that is what "faces the camera" means for a Y billboard.
  const edge = [diag[1][0] - diag[0][0], diag[1][2] - diag[0][2]];
  check('D2 …perpendicular to the horizontal line of sight',
    um(edge[0] * 100 + edge[1] * 100), 0);
  check('D3 the corners do not move when the camera climbs',
    corners(200, 500, 0), corners(200, 5, 0));
  check('D3 …and every corner keeps the y of its edge',
    [...new Set(corners(100, 80, 100).map((c) => c[1]))].sort((a, b) => a - b),
    [BOTTOM, TOP]);

  // (D4) the red counter-check: the full billboard, built here by hand
  const cam = [200, centreY + 200, 0];
  const v = [cam[0], cam[1] - centreY, cam[2]];
  const vLen = Math.hypot(v[0], v[1], v[2]);
  const vn = v.map((c) => c / vLen);
  // right = worldUp x view, up = view x right
  const r = [
    1 * vn[2] - 0 * vn[1],
    0 * vn[0] - 0 * vn[2],
    0 * vn[1] - 1 * vn[0],
  ];
  const rLen = Math.hypot(r[0], r[1], r[2]);
  const rn = r.map((c) => c / rLen);
  const upY = vn[2] * rn[0] - vn[0] * rn[2];   // the y of view x right
  check('D4 a FULL billboard tilts: its up axis loses height',
    um(upY), um(Math.cos(Math.PI / 4)));
  check('D4 …its foot leaves the ground', um(centreY - (h / 2) * upY),
    um(0.7566468143699092));
  check('D4 …its top sinks', um(centreY + (h / 2) * upY),
    um(7.121815209727755));
  check('D4 …and the tree loses a fifth of its height', um(h * upY),
    um(6.365168395357846));
  check('D4 …none of which the Y billboard does', [
    um(centreY - h / 2), um(centreY + h / 2), um(h),
  ], [BOTTOM, TOP, um(9.001707471503655)]);

  console.log('\n(E) the red counter-check of the window — one mutant');
  const loose = await loadTs(LOD_SRC, windowWithoutCull);
  check('E the "no cull line" mutant draws a billboard at 60 m',
    loose.impostorInWindow(60, cfg), true);
  check('E …ON TOP of a full mesh',
    [instanceTier(60, 1, cfg) !== 2, impostorInWindow(60, cfg)], [true, false]);

  console.log('\n(F) the wiring, read off the source');
  const groundSrc = await readFile(GROUND_SRC, 'utf8');
  const impSrc = await readFile(IMP_SRC, 'utf8');
  const mainSrc = await readFile(MAIN_SRC, 'utf8');
  check('F the far half is binned BEFORE the entry-wide early-out',
    groundSrc.indexOf('binImpostors(prop, cam, cfg);')
      < groundSrc.indexOf('if (cam.distanceTo(prop.sphere.center) - prop.sphere.radius > cfg.cullM) {'),
    true);
  check('F …and the far half is asked at all',
    groundSrc.includes('binImpostors(prop, cam, cfg);'), true);
  check('F the billboards stand on the entry\'s OWN positions',
    groundSrc.includes('const px = prop.pos[i * 3];'), true);
  check('F …turned by the pure yaw', groundSrc.includes('impostorYaw(px, pz, cam.x, cam.z)'), true);
  check('F …on the pure quad', groundSrc.includes('impostorQuad(prop.targetH, bake.frame)'), true);
  check('F the bake is CLAIMED while a mesh draws with it',
    groundSrc.includes('acquireImpostor(prop.loUrl, prop.near)'), true);
  check('F …and given back with that mesh',
    groundSrc.includes('releaseImpostor(prop.loUrl);'), true);
  check('F …so the LRU can only evict what nobody draws',
    impSrc.includes('if (entry.refs <= 0)'), true);
  check('F the bake borrows the app renderer and creates none',
    impSrc.includes('new THREE.WebGLRenderer'), false);
  check('F …which main.ts hands it once',
    mainSrc.includes('setImpostorRenderer(engine.renderer);'), true);
  // The module NAMES the corridor in its header (it says why it is not
  // patched) — what must be absent is the import, i.e. the patch itself.
  check('F the impostor material is NOT patched with the camera corridor',
    impSrc.includes("from './occlusion'"), false);
  check('F …and the header says why it is not', impSrc.includes('OCC_GATE_M'), true);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
