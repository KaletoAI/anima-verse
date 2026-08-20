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
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'packages/scene-render/src/place.ts');

async function loadBundled(src, prefix) {
  const esbuild = await import('esbuild');
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

console.log(`\n${failed ? `FAILED (${failed})` : 'all checks passed'}`
  + `  —  ${passed} ok`);
process.exit(failed ? 1 : 0);
