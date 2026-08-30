#!/usr/bin/env node
/**
 * Smoke run for the JOINT of § A4 and § B2: does the point the SERVER composed
 * as a prop marker land on the very spot of the MESH the renderer places?
 *
 * Usage:  node scripts/smoke_prop_marker_place.mjs
 *
 * Same discipline as the other mjs smokes: every expected number is derived BY
 * HAND below (and pinned on the server side, with the same numbers, in
 * `scripts/smoke_prop_marker_surface.py` part 4) — nothing is recorded from the
 * current output.
 *
 * ============================================================================
 * WHAT WENT WRONG (user finding 2026-08-20)
 * ============================================================================
 * "In the floor-plan preview the figure sits somewhere else on the prop than
 * the marker I set in the props tab."
 *
 * Two ends computed the same seat with two different laws:
 *
 *   § B2 step 4 (place(), both renderers): shift the object until the box of
 *       the FINISHED, YAWED result has its xz centre on `anchor`.
 *   § A4 (compose_prop_marker, server): offset from the object's box centre
 *       BEFORE the yaw, then turn that offset by the yaw.
 *
 * They differ by  centre(AABB(R·mesh)) − R·centre(AABB(mesh))  — zero for an
 * axis-parallel yaw or a symmetric silhouette, and NOT zero otherwise. Measured
 * on the meshes in the field: sectional sofa 0.50 m at yaw 45, cable-crossover
 * station 0.33 m, king-size bed 0.12 m. And the server cannot compute the
 * renderer's version at all: it knows the prop's `bbox`, never the yawed hull
 * of the real mesh. So § B2 step 3/4 was revised — the object hangs on the
 * centre it has BEFORE the yaw, and the yaw spins it about that point.
 *
 * ============================================================================
 * THE FIXTURE: an L, so the hull is NOT its box
 * ============================================================================
 * A symmetric box would pass either law. The source here is
 *
 *   slab  x [0, 1]    y [0, 1]    z [0, 1]
 *   bar   x [0, 0.2]  y [0, 1]    z [1, 2]
 *
 * so the raw AABB is exactly 1 x 1 x 2 (what the server is told as `bbox`)
 * while the shape sits off-centre inside it. Real size: max_m = 1.0,
 * measure "xyz".
 *
 *   scale   s = max_m / max(bbox measured at the 90°-ROUNDED fix)
 *   marker  frac [1.0, 0.45, 0.5] -> the raw point (1, 0.45, 1)
 *
 * (A) fix 0, yaw 30
 *     s = 1.0 / 2 = 0.5;  box centre (0.5, ·, 1.0). The point sits 0.5 raw
 *     units in +x of it and nowhere else, so after the scale it is 0.25 m
 *     straight +x of the seat.
 *     yaw 30:  dx = 0.25·cos30 = 0.2165 -> 0.217
 *              dz = −0.25·sin30 = −0.125
 *     height  = 0.5 · 0.45 = 0.225
 *
 * (B) fix y 90, yaw 217
 *     Ry(90) maps (x,y,z) -> (z, y, −x): box x' [0,2], z' [−1,0], so the
 *     rounded extents are (2,1,1), s = 0.5 again. The point becomes
 *     (1, 0.45, −1), the centre (1, ·, −0.5) -> offset (0, ·, −0.5) raw,
 *     0.25 m in −z after the scale.
 *     yaw 217 (cos −0.798636, sin −0.601815):
 *              dx = −0.25·sin217 = 0.150
 *              dz = −0.25·cos217 = 0.200
 *     height  = 0.225
 *
 * (C) fix y 20, yaw 30 — the KNOWN residual, stated instead of hidden.
 *     The size is still measured at snap(20) = 0 (v5.1 Nr. 4), so s = 0.5 and
 *     the height stays 0.225 — exactly. The SEAT, though, is the centre of the
 *     BOX turned by 20°, and turning a box around a box overestimates: the
 *     renderer's hull has a slightly different centre. The server's answer is
 *     (0.161, −0.192); how far the mesh point really sits from it depends on
 *     the silhouette (8.5 cm on this deliberately extreme L, 5 cm on the one
 *     prop in the field with such a fix). Checked as a BOUND, not a number.
 *
 * The world target in every case: anchor + [dx, dz], bottom_y + height_m.
 *
 * ============================================================================
 * E  THE FIGURE ON THE MARKER (finding 2026-08-21)
 * ============================================================================
 * "The figure sits somewhere else on the prop than the position I set on the
 * prop itself." Three renderers, three laws for the same height:
 *
 *   client3d           anchor the figure in its BIND pose (soles on 0), put
 *                      that root on `y_world − root_offset`.
 *   floor-plan preview the same — but by accident: it grounded on the box of
 *                      the POSED figure, and `Box3.setFromObject` ignores
 *                      skinning, so it silently returned the bind box.
 *   prop viewer        its own: anchor the HIPS BONE of the posed skeleton
 *                      minus 0.03 × H. Every clip is played IN PLACE (the
 *                      Mixamo hips POSITION track is dropped — centimetres),
 *                      so the hips joint never moves and that reading is ONE
 *                      constant for every clip alike: 0.9288 m at H = 1.70 m,
 *                      measured on x-bot.fbx + the clips.
 *
 * The drop itself now comes from the pose catalog (`groups[g].root_drop ×
 * 1.70`, the ONE source) and reaches the renderer as `root_offset`, so
 * `figureRootY(surfaceY, rootOffset)` takes that metre value and nothing else.
 *
 * ============================================================================
 * E5  AND THE CLIP CARRIES ITS OWN HIPS HEIGHT (finding 2026-08-29)
 * ============================================================================
 * Anchoring the figure in its bind pose is only half the height. Every
 * renderer drops the Mixamo hips POSITION track (it is in centimetres and
 * would fling the body across the room), and the 3D client puts that height
 * BACK, rescaled: `client3d/src/scene/figures.adaptExternalClips` keeps the
 * track relative to the standing reference (the hips median of the idle
 * clip). The admin prop viewer dropped the track and never put anything back,
 * so the posed hips sat at the BIND height for every clip alike — measured
 * headless on x-bot.fbx: 0.9801 m at H = 1.70 m, for idle, sit and laying
 * alike (this file's E5 is what measures it).
 *
 * Sitting is therefore drawn `hipsBind × (1 − median(sit)/median(idle))`
 * higher than it is played — 0.4267 m with the served Mixamo clips — and
 * every seat marker aligned in that preview was set that far too low.
 * `clipHipsDrop()` is that missing term, shared by both admin previews.
 *
 * The server half of the same chain is
 * `scripts/smoke_prop_marker_surface.py` part 5.
 */
import { existsSync, readFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'packages/scene-render/src/place.ts');
const require_ = createRequire(import.meta.url);

/** esbuild is a Vite dependency and lives wherever npm hoisted it — the root
 *  in a clean workspace install, otherwise inside the app that pulled it. The
 *  same lookup as `smoke_slot_materials.mjs`, because a bare import of it
 *  fails outright in a checkout where the root has no copy. */
function esbuildModule() {
  for (const cand of ['esbuild',
                      join(ROOT, 'frontend/node_modules/esbuild'),
                      join(ROOT, 'client3d/node_modules/esbuild')]) {
    try {
      return require_(cand);
    } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

async function loadBundled(src, prefix) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), prefix));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({
      entryPoints: [src], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', external: ['three'], logLevel: 'silent',
      absWorkingDir: ROOT,
    });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function near(label, actual, expected, eps = 1e-3) {
  const ok = Math.abs(actual - expected) <= eps;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}: ${actual.toFixed(4)}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}: ${actual.toFixed(4)}`
      + `  (expected ${expected.toFixed(4)}, eps ${eps})`);
  }
}

const THREE = await import('three');
const { placeModelSpec } = await loadBundled(SRC, 'smoke-place-');
const { anchorFigureBind, clipHipsDrop, figureRootY, hipsTrackMedian,
        FIGURE_HEIGHT_M } =
  await loadBundled(join(ROOT, 'packages/scene-render/src/figure.ts'),
                    'smoke-figure-');

/** The L above, plus an empty Object3D at the marker's raw point. A bare
 *  Object3D carries no geometry, so it does not enter any Box3 measurement. */
function fixture() {
  const src = new THREE.Group();
  const add = (w, h, d, x, y, z) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d));
    m.position.set(x + w / 2, y + h / 2, z + d / 2);
    src.add(m);
  };
  add(1, 1, 1, 0, 0, 0);        // slab
  add(0.2, 1, 1, 0, 0, 1);      // bar
  const probe = new THREE.Object3D();
  probe.position.set(1, 0.45, 1);   // rawBox.min + frac × rawSize
  src.add(probe);
  return { src, probe };
}

function place(fixEuler, yawDeg, anchor, bottomY) {
  const { src, probe } = fixture();
  src.updateMatrixWorld(true);
  const raw = new THREE.Box3().setFromObject(src).getSize(new THREE.Vector3());
  const out = placeModelSpec(THREE, src, {
    fix_euler: fixEuler, yaw_deg: yawDeg, max_m: 1.0, measure: 'xyz',
    anchor, bottom_y: bottomY,
  }, { clone: false, clip: false });
  const scene = new THREE.Scene();
  scene.add(out);
  scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(out);
  return {
    raw,
    box,
    point: probe.getWorldPosition(new THREE.Vector3()),
  };
}

console.log('\n0. the fixture is the box the server is told about');
{
  const { raw } = place({ x: 0, y: 0, z: 0 }, 0, [0, 0], 0);
  near('bbox x', raw.x, 1.0, 1e-6);
  near('bbox y', raw.y, 1.0, 1e-6);
  near('bbox z', raw.z, 2.0, 1e-6);
}

// Anchor and floor are arbitrary — they only have to be somewhere that is not
// the origin, so a forgotten term cannot hide in a zero.
const ANCHOR = [2, 3];
const BOTTOM = 0.5;

const CASES = [
  ['A  fix 0,    yaw 30 ', { x: 0, y: 0, z: 0 }, 30, [0.217, -0.125], 0.225],
  ['B  fix y90,  yaw 217', { x: 0, y: 90, z: 0 }, 217, [0.150, 0.200], 0.225],
];

for (const [label, fix, yaw, [dx, dz], height] of CASES) {
  console.log(`\n${label} — the composed marker IS the mesh point`);
  const r = place(fix, yaw, ANCHOR, BOTTOM);
  near('bottom_y is met', r.box.min.y, BOTTOM, 1e-6);
  near('marker x', r.point.x, ANCHOR[0] + dx);
  near('marker z', r.point.z, ANCHOR[1] + dz);
  near('marker y', r.point.y, BOTTOM + height);
}

console.log('\nC  fix y20, yaw 30 — the KNOWN residual of a non-90° fix');
{
  // Size and height stay EXACT: the scale is measured at snap(20) = 0 like the
  // renderer's (v5.1 Nr. 4), and a y-fix does not touch the height at all.
  // The horizontal seat is the one term the server can only approximate — its
  // box turned by 20° is not the hull of the mesh turned by 20°. This fixture
  // is a deliberately extreme L; the one prop in the field with such a fix (a
  // stool at x 350) measures 5 cm.
  const r = place({ x: 0, y: 20, z: 0 }, 30, ANCHOR, BOTTOM);
  near('bottom_y is met', r.box.min.y, BOTTOM, 1e-6);
  near('marker y is exact', r.point.y, BOTTOM + 0.225);
  const off = Math.hypot(r.point.x - (ANCHOR[0] + 0.161),
                         r.point.z - (ANCHOR[1] - 0.192));
  if (off <= 0.1) {
    passed += 1;
    console.log(`  ok   horizontal residual ${off.toFixed(4)} m — the box-proxy`
      + ' approximation, bounded and documented (§ A4)');
  } else {
    failed += 1;
    console.log(`  FAIL horizontal residual ${off.toFixed(4)} m — larger than`
      + ' the documented approximation of a non-90° fix');
  }
}

console.log('\nD  turning the prop must not move it');
{
  // The invariant behind the § B2 revision: the seating point is the anchor at
  // EVERY yaw. Under the old law this drifted with the shape of the hull —
  // that drift is exactly what separated the seat from its prop.
  for (const yaw of [0, 30, 45, 90, 217]) {
    const r = place({ x: 0, y: 0, z: 0 }, yaw, ANCHOR, BOTTOM);
    const c = r.box.getCenter(new THREE.Vector3());
    // Distance of the marker point from the anchor: the raw offset is 0.25 m
    // and a rotation keeps a length.
    const d = Math.hypot(r.point.x - ANCHOR[0], r.point.z - ANCHOR[1]);
    near(`yaw ${yaw}: marker distance from the anchor`, d, 0.25, 1e-3);
    // …and the hull centre is NOT the anchor for a diagonal yaw — the counter
    // probe that proves this fixture would have failed the old law.
    if (yaw % 90 !== 0) {
      const off = Math.hypot(c.x - ANCHOR[0], c.z - ANCHOR[1]);
      if (off > 0.01) {
        passed += 1;
        console.log(`  ok   yaw ${yaw}: hull centre is ${off.toFixed(3)} m off `
          + 'the anchor — the old law would have put it there');
      } else {
        failed += 1;
        console.log(`  FAIL yaw ${yaw}: hull centre and anchor coincide — the `
          + 'fixture is too symmetric to prove anything');
      }
    }
  }
}

console.log('\nE  the figure meets the marker — ONE law for all three renderers');
{
  near('the contract figure is 1.70 m', FIGURE_HEIGHT_M, 1.7, 1e-9);

  // (E1) The bind anchor: soles on 0, XZ centred, scaled to the target height.
  // A deliberately off-origin body, so a forgotten term cannot hide in a zero.
  const body = new THREE.Group();
  const box = new THREE.Mesh(new THREE.BoxGeometry(0.5, 2, 0.4));
  box.position.set(3, 7, -2);          // min.y 6, centre (3, ·, −2)
  body.add(box);
  const k = anchorFigureBind(THREE, body, FIGURE_HEIGHT_M);
  near('scale = 1.70 / 2', k, 0.85, 1e-9);
  const b = new THREE.Box3().setFromObject(body);
  near('soles on 0', b.min.y, 0, 1e-9);
  near('height is the figure height', b.max.y - b.min.y, FIGURE_HEIGHT_M, 1e-9);
  near('XZ centred on the origin', b.getCenter(new THREE.Vector3()).x, 0, 1e-9);
  near('… on z as well', b.getCenter(new THREE.Vector3()).z, 0, 1e-9);

  // (E2) The bench chain of `smoke_prop_marker_surface.py` part 5: the seat
  // surface sits at 0.587 on storey 0, and the seat group's `root_drop` in
  // `shared/templates/pose/pose_catalog.json` is 0.314 — the catalog is the
  // ONE source of that share, and the caller (server or prop tab) has already
  // turned it into metres before `figureRootY` sees it.
  //   seat   0.314 × 1.70 = 0.5338  ->  0.587 − 0.5338 =  0.0532
  //   bed    0.631 × 1.70 = 1.0727  ->  0.587 − 1.0727 = −0.4857
  //   floor  0.051 × 1.70 = 0.0867  ->  0.587 − 0.0867 =  0.5003
  const SURFACE = 0.587;
  const ROOT_OFFSET = {           // catalog `root_drop` × 1.70 m
    seat: 0.314 * FIGURE_HEIGHT_M,
    bed: 0.631 * FIGURE_HEIGHT_M,
    floor: 0.051 * FIGURE_HEIGHT_M,
    stand: 0,
  };
  near('seat root', figureRootY(SURFACE, ROOT_OFFSET.seat), 0.0532);
  near('bed root', figureRootY(SURFACE, ROOT_OFFSET.bed), -0.4857);
  near('floor root', figureRootY(SURFACE, ROOT_OFFSET.floor), 0.5003);
  // A place type with no drop touches at its own root — a stander stands ON
  // the mark, and so does a marker whose group the caller does not know yet.
  near('a standing spot keeps the surface',
       figureRootY(SURFACE, ROOT_OFFSET.stand), SURFACE, 1e-9);
  near('… and so does a missing offset',
       figureRootY(SURFACE, null), SURFACE, 1e-9);
  near('… and an unusable one', figureRootY(SURFACE, NaN), SURFACE, 1e-9);

  // (E3) The offset is used VERBATIM — no consumer re-derives the share it
  // was already given (the payload's `root_offset` is metres, done).
  near('an arbitrary offset is used verbatim',
       figureRootY(SURFACE, 0.25), 0.337, 1e-9);

  // (E4) THE HIPS TRACK OF THE CLIP — the term the prop viewer was missing.
  //
  // The median rule is `client3d`'s (`figures.hipMedian`), so admin and client
  // read the same standing reference off the same file: |y| of every key of
  // the `…hips….position` track, sorted, the element at floor(n/2).
  {
    const track = (name, ys) => ({
      name,
      values: new Float32Array(ys.flatMap((y) => [0, y, 0])),
    });
    // 5 keys -> index 2 of [1,2,3,4,100] = 3; the sign is dropped (a Z-up
    // export writes the height negative), and a non-hips or non-position
    // track contributes nothing.
    const clip = { tracks: [
      track('mixamorig:Hips.position', [3, -1, 100, 2, 4]),
      track('mixamorig:Hips.quaternion', [999, 999, 999]),
      track('mixamorig:Spine.position', [777, 777, 777]),
    ] };
    near('hips median: |y|, sorted, floor(n/2)', hipsTrackMedian(clip), 3, 1e-9);
    if (hipsTrackMedian({ tracks: [track('mixamorig:Spine.position', [1, 2])] })
        === null) {
      passed += 1;
      console.log('  ok   no hips track at all = null, not a zero height');
    } else {
      failed += 1;
      console.log('  FAIL a clip without a hips track must answer null');
    }
  }
  // The drop itself, hand-derived from the medians measured on the SERVED
  // clip library (`shared/models/clips-licensed`, headless FBXLoader.parse,
  // Mixamo centimetres) and the bind hips of x-bot.fbx at H = 1.70 m:
  //
  //   hipsBind 0.9801   idle 110.13   walk 108.53   sit 62.18
  //                     laying 14.56  sleep 119.48  kneeling 53.30
  //
  //   drop = 0.9801 × (1 − median/110.13)
  //     walk      0.9801 × (1 − 0.985472) = 0.9801 × 0.014528 =  0.01424
  //     sit       0.9801 × (1 − 0.564605) = 0.9801 × 0.435395 =  0.42673
  //     laying    0.9801 × (1 − 0.132207) = 0.9801 × 0.867793 =  0.85052
  //     sleep     0.9801 × (1 − 1.084900) = 0.9801 × −0.084900 = −0.08321
  //     kneeling  0.9801 × (1 − 0.483976) = 0.9801 × 0.516024 =  0.50576
  const HIPS_BIND = 0.9801;
  const STAND_REF = 110.13;
  near('idle IS the reference — nothing to put back',
       clipHipsDrop(HIPS_BIND, 110.13, STAND_REF), 0, 1e-9);
  near('walk barely moves', clipHipsDrop(HIPS_BIND, 108.53, STAND_REF), 0.01424);
  near('sit sinks by', clipHipsDrop(HIPS_BIND, 62.18, STAND_REF), 0.42673);
  near('laying sinks by', clipHipsDrop(HIPS_BIND, 14.56, STAND_REF), 0.85052);
  // A sleeper is played ABOVE its own standing hips (the clip is animated on
  // a bed): the term is NEGATIVE and must stay so — clamping it at 0 would
  // bury the sleeper in the mattress by exactly this much.
  near('sleep rises by', clipHipsDrop(HIPS_BIND, 119.48, STAND_REF), -0.08321);
  near('kneeling sinks by', clipHipsDrop(HIPS_BIND, 53.30, STAND_REF), 0.50576);
  // Missing inputs = no correction, never a NaN into a position.
  for (const [label, args] of [
    ['no bind height', [null, 62.18, STAND_REF]],
    ['no clip median', [HIPS_BIND, null, STAND_REF]],
    ['no standing reference', [HIPS_BIND, 62.18, null]],
    ['a zero reference (division)', [HIPS_BIND, 62.18, 0]],
  ]) near(`${label} = no drop`, clipHipsDrop(...args), 0, 1e-9);
}

console.log('\nE5  the real skeleton — x-bot + the served clips, headless');
{
  // The chain of `Model3DViewer.addMarkerFigure`, replayed on the real files:
  // anchor the bind pose to 1.70 m, measure the hips, drop the hips POSITION
  // track, play frame 0, then lower the figure by `clipHipsDrop`. The check is
  // WHERE THE HIPS END UP against the marker surface — that is the number the
  // user aligns a seat marker by.
  //
  // Hand-derived, per set (S = the marked surface):
  //   hipsBind = (104.275 + 0.035) / 180.923 × 1.70 = 0.98013   (x-bot raw:
  //     hips y 104.275, box min.y −0.035, box height 180.923)
  //   posed hips y = S − rootOffset − drop + hipsBind
  //   licensed sit    S − 0.5338 − 0.42673 + 0.9801 = S + 0.01957
  //   licensed laying S − 0.0867 − 0.85052 + 0.9801 = S + 0.04288
  //   free     sit    S − 0.5338 − 0.40376 + 0.9801 = S + 0.04254
  //   free     laying S − 0.0867 − 0.84033 + 0.9801 = S + 0.05307
  //   idle (a standing spot, offset 0 and drop 0) = S + 0.9801
  //
  // The licensed library is not in git (Mixamo/pack licence) and the free one
  // may be incomplete, so a missing set is a SKIP with a named reason, not a
  // failure — the law itself is pinned above and needs no file.
  const FIG = join(ROOT, 'shared/models/figure/x-bot.fbx');
  const SETS = [
    { name: 'free (CMU)', dir: join(ROOT, 'shared/models/clips'),
      files: { idle: 'idle.fbx', sit: 'sit.fbx',
               laying: 'laying.fbx' },
      medians: { idle: 110.86, sit: 65.19, laying: 15.81 },
      drops: { idle: 0, sit: 0.40376, laying: 0.84033 },
      hips: { idle: 0.9801, sit: 0.04254, laying: 0.05307 } },
    { name: 'licensed (Mixamo)', dir: join(ROOT, 'shared/models/clips-licensed'),
      files: { idle: 'idle.fbx', sit: 'sit.fbx', laying: 'laying.fbx' },
      medians: { idle: 110.13, sit: 62.18, laying: 14.56 },
      drops: { idle: 0, sit: 0.42673, laying: 0.85052 },
      hips: { idle: 0.9801, sit: 0.01957, laying: 0.04288 } },
  ];
  const GROUP_OF = { idle: 'stand', sit: 'seat', laying: 'floor' };
  const OFFSET = { stand: 0, seat: 0.314 * FIGURE_HEIGHT_M,
                   floor: 0.051 * FIGURE_HEIGHT_M };
  const SURFACE = 0.587;          // the bench of E2, once more

  if (!existsSync(FIG)) {
    console.log(`  SKIP no test figure at ${FIG} — the law is pinned in E4`);
  } else {
    const { FBXLoader } =
      await import('three/examples/jsm/loaders/FBXLoader.js');
    const { clone: skclone } =
      await import('three/examples/jsm/utils/SkeletonUtils.js');
    const loader = new FBXLoader();
    const parse = (path) => {
      const b = readFileSync(path);
      return loader.parse(b.buffer.slice(b.byteOffset,
                                         b.byteOffset + b.byteLength), '');
    };
    const hipsOf = (root) => {
      let found = null;
      root.traverse((o) => { if (!found && /hips/i.test(o.name)) found = o; });
      return found;
    };
    const src = parse(FIG);
    for (const set of SETS) {
      const missing = Object.values(set.files)
        .filter((f) => !existsSync(join(set.dir, f)));
      if (missing.length) {
        console.log(`  SKIP ${set.name}: ${set.dir} has no `
          + `${missing.join(', ')} — the law is pinned in E4`);
        continue;
      }
      const standRef = hipsTrackMedian(parse(join(set.dir, set.files.idle))
        .animations[0]);
      near(`${set.name}: standing reference (idle hips median)`,
           standRef, set.medians.idle, 0.02);
      const residual = {};
      for (const kind of ['idle', 'sit', 'laying']) {
        const clipObj = parse(join(set.dir, set.files[kind]));
        const clip = clipObj.animations[0];
        const median = hipsTrackMedian(clip);
        near(`${set.name}: ${kind} hips median`, median, set.medians[kind], 0.02);
        // ── the viewer's chain ──
        const inst = skclone(src);
        const pivot = new THREE.Group();
        pivot.add(inst);
        const instHips = hipsOf(inst);
        anchorFigureBind(THREE, pivot, FIGURE_HEIGHT_M);
        const hipsBindY =
          instHips.getWorldPosition(new THREE.Vector3()).y;
        near(`${set.name}: ${kind} bind hips`, hipsBindY, 0.98013, 5e-4);
        // Play in place: the Mixamo hips POSITION track is centimetres.
        clip.tracks = clip.tracks.filter(
          (tr) => !(/hips/i.test(tr.name) && tr.name.endsWith('.position')));
        const mixer = new THREE.AnimationMixer(inst);
        mixer.clipAction(clip).play();
        mixer.update(0);
        pivot.updateMatrixWorld(true);
        // RED PROBE — this is the bug: with the track gone the posed hips are
        // ONE height for every clip alike, the bind height.
        near(`${set.name}: ${kind} posed hips before the correction`,
             instHips.getWorldPosition(new THREE.Vector3()).y, 0.98013, 5e-4);
        const drop = clipHipsDrop(hipsBindY, median, standRef);
        near(`${set.name}: ${kind} clip drop`, drop, set.drops[kind], 2e-3);
        // The figure hangs at the marker root, lowered by the clip's own hips.
        const fig = new THREE.Group();
        fig.add(pivot);
        fig.position.set(0, figureRootY(SURFACE, OFFSET[GROUP_OF[kind]]) - drop, 0);
        const scene = new THREE.Scene();
        scene.add(fig);
        scene.updateMatrixWorld(true);
        const hipsY = instHips.getWorldPosition(new THREE.Vector3()).y;
        residual[kind] = hipsY - SURFACE;
        near(`${set.name}: ${kind} hips over the marked surface`,
             residual[kind], set.hips[kind], 2e-3);
      }
      // …and the bound that matters to the user: a seated or lying body meets
      // the surface it was marked on. The residual is the catalog's
      // calibration, not the law — `seat.root_drop` 0.314 is derived on the
      // Mixamo sit clip (2.0 cm), the CMU one sits 3 cm higher (4.3 cm). The
      // hip-joint-versus-buttocks term of the same finding is a pending user
      // decision, so this is checked as a BOUND, like case C above.
      const worst = Math.max(Math.abs(residual.sit), Math.abs(residual.laying));
      if (worst <= 0.06) {
        passed += 1;
        console.log(`  ok   ${set.name}: seated/lying hips within `
          + `${worst.toFixed(3)} m of the marked surface`);
      } else {
        failed += 1;
        console.log(`  FAIL ${set.name}: ${worst.toFixed(3)} m off the marked `
          + 'surface — more than the documented catalog calibration');
      }
    }
  }
}

console.log(`\n${failed ? `FAILED (${failed})` : 'all checks passed'}`
  + `  —  ${passed} ok`);
process.exit(failed ? 1 : 0);
