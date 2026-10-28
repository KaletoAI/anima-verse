#!/usr/bin/env node
/**
 * Smoke check for the OVERVIEW camera's arithmetic (`client3d/src/scene/cameraMath.ts`,
 * plus `basePitchDeg` of `client3d/src/scene/cameraFraming.ts`) — the pure part;
 * the input events and the render loop that call it need a browser.
 *
 * Usage:  node client3d/scripts/smoke_camera_math.mjs
 *
 * Hand-derived expectations (§ B5a: numbers, no snapshots). Constants of the
 * rules: MIN_DIST 0.8, MAX_DIST 150, half FOV 22.5° (sin 22.5° = 0.3826834324),
 * fit margin 1.15, empty-world distance 70, wheel rate 0.0012 per deltaY unit,
 * easing 1 − e^(−8·min(dt, 0.1)), fly rate 1.6 per second, orbit 0.005 rad and
 * 0.25° per pixel, free pitch ±35° (±85° in first person), drawn pitch 8°..85°
 * (−85°..85° in first person).
 *
 * [1] fitDistance(bounds) = clamp(r · 1.15 / sin 22.5°, 0.8, 150),
 *     r = hypot(max_x − min_x, max_z − min_z) / 2; no bounds or r <= 0 -> 70.
 *     a) no bounds -> 70 (the old boot default)
 *     b) −100..100 × −50..50: r = hypot(200, 100) / 2 = 223.6068 / 2 = 111.8034;
 *        · 1.15 = 128.5739; / 0.3826834 = 335.98 -> above the cap -> 150
 *     c) 10..22 × −20..−4: r = hypot(12, 16) / 2 = 20 / 2 = 10;
 *        10 · 1.15 = 11.5; 11.5 / 0.3826834324 = 30.0509481922
 *     d) 0..60 × 0..80: r = hypot(60, 80) / 2 = 50; 57.5 / 0.3826834 = 150.25
 *        -> just above the cap -> 150
 *     e) 0..0.2 × 0..0.2: r = 0.2828427 / 2 = 0.1414214; · 1.15 = 0.1626346;
 *        / 0.3826834 = 0.42498 -> below the floor -> 0.8
 *     f) a point (5..5 × 7..7): r = 0 -> 70, never a zero distance
 * [2] worldCentreXZ(bounds) = [(min_x + max_x) / 2, (min_z + max_z) / 2]; no bounds -> [0, 0]
 *     a) none -> [0, 0]   b) −100..100 × −50..50 -> [0, 0]   c) 10..22 × −20..−4 -> [16, −12]
 * [3] basePitchDeg(d, near) = near + (62 − near) · sqrt(clamp((d − 0.8) / 149.2, 0, 1))
 *     a) d = 0.8 -> zoomK 0 -> 18                b) d = 150 -> zoomK 1 -> 62
 *     c) d = 400 -> clamped to 1 -> 62           d) d = 0.1 -> clamped to 0 -> 18
 *     e) d = 7: 6.2 / 149.2 = 0.0415550; sqrt = 0.2038505; 18 + 44 · 0.2038505 = 26.9694148
 *     f) d = 75.4: 74.6 / 149.2 = 0.5; sqrt = 0.7071068; 18 + 44 · 0.7071068 = 49.1126984
 *     g) embodied near 8, d = 2: 1.2 / 149.2 = 0.0080429; sqrt = 0.0896823;
 *        8 + 54 · 0.0896823 = 12.8428383
 *     h) no near given -> the overview's 18, so d = 7 again -> 26.9694148
 * [4] clampPitchDeg(deg, firstPerson): overview [8, 85], first person [−85, 85]
 *     40 -> 40; 5 -> 8; 100 -> 85; first person −50 -> −50, −100 -> −85, 90 -> 85
 * [5] wheelZoom(d, deltaY, floor, cap) = clamp(d · e^(deltaY · 0.0012), lo, hi),
 *     lo = max(floor ?? 0.8, 0.8), hi = max(lo, min(cap ?? 150, 150))
 *     a) 80, +100: e^0.12 = 1.1274969; 80 · 1.1274969 = 90.1997481
 *     b) 80, −100: e^−0.12 = 0.8869204; 80 · 0.8869204 = 70.9536349
 *     c) 1, −1000: e^−1.2 = 0.3011942 -> below 0.8 -> 0.8
 *     d) 140, +100: 140 · 1.1274969 = 157.85 -> 150
 *     e) cap 34 (embodied), 30, +200: e^0.24 = 1.2712492; 38.137 -> 34
 *     f) floor 2, 2.2, −200: e^−0.24 = 0.7866279; 1.7306 -> 2
 *     g) floor 0.5 is below the lens -> lo = 0.8; 1, −500: e^−0.6 = 0.5488 -> 0.8
 *     h) cap 500 is beyond the lens -> hi = 150; 140, +100 -> 157.85 -> 150
 *     i) cap 1 below floor 2 -> hi = max(2, 1) = 2; 5, deltaY 0 -> 5 -> 2
 *     j) deltaY 0 changes nothing: 42 -> 42
 * [6] zoomTowardCursor(target, hit, old, new): only while zooming IN (new < old) and with a
 *     hit, target += (hit − target) · (1 − new / old), hit at height 0
 *     a) [10, 0, 10], hit [20, 30], 100 -> 80: k = 0.2 -> [12, 0, 14]
 *     b) [0, 5, 0], hit [10, 10], 50 -> 25: k = 0.5 -> [5, 2.5, 5]
 *     c) zooming out, 50 -> 60 -> unchanged [1, 2, 3]
 *     d) no hit -> unchanged [1, 2, 3]
 *     e) the same distance (k would be 0) -> unchanged [1, 2, 3]
 * [7] damp(dt) = 1 − e^(−8 · min(dt, 0.1))
 *     a) 0 -> 0            b) 0.1 -> 1 − e^−0.8 = 1 − 0.4493290 = 0.5506710
 *     c) 0.5 -> clamped to 0.1 -> 0.5506710
 *     d) 0.05 -> 1 − e^−0.4 = 1 − 0.6703200 = 0.3296800
 *     e) 1/60 -> 1 − e^(−0.1333333) = 1 − 0.8751733 = 0.1248267
 * [8] flyAdvance(t, dt) = min(1, t + 1.6 · dt); flyEase(t) = 3t² − 2t³
 *     flyAdvance: (0, 0.1) -> 0.16; (0.9, 0.1) -> 1.06 -> 1; (0.5, 0) -> 0.5
 *     flyEase: 0 -> 0; 1 -> 1; 0.5 -> 0.75 − 0.25 = 0.5;
 *              0.25 -> 0.1875 − 0.03125 = 0.15625; 0.75 -> 1.6875 − 0.84375 = 0.84375
 * [9] orbitStep(yaw, offset, dx, dy, fp) = {yaw − 0.005 · dx, clamp(offset + 0.25 · dy, ±L)},
 *     L = 35 (85 in first person)
 *     a) (π/4, 0, 10, 20) -> {0.7853982 − 0.05 = 0.7353982, 5}
 *     b) (0, 30, 0, 40) -> 40 -> {0, 35}      c) (0, −30, 0, −40) -> {0, −35}
 *     d) first person (0, 30, 0, 40) -> {0, 40}; (0, 80, 0, 40) -> 90 -> {0, 85}
 *     e) (0, 0, −100, 0) -> dragging left turns the other way -> {0.5, 0}
 * [10] cameraPose(target, dist, yaw, pitchDeg).pos =
 *      target + (sin yaw · cos p, sin p, cos yaw · cos p) · dist
 *     a) [0,0,0], 10, yaw 0, 0° -> [0, 0, 10] (yaw 0: the camera on +Z)
 *     b) [0,0,0], 10, yaw π/2, 0° -> [10, 0, 0] (cos π/2 = 6e−17, inside eps)
 *     c) [0,0,0], 10, yaw 0, 90° -> [0, 10, 0] (straight above)
 *     d) [5,1,−3], 20, yaw 0, 30°: cos 30° = 0.8660254, sin 30° = 0.5
 *        -> [5, 1 + 10, −3 + 17.3205081] = [5, 11, 14.3205081]
 *     e) [0,0,0], 10, yaw π/4, 45°: sin π/4 · cos 45° = 0.5 -> [5, 7.0710678, 5]
 *
 * [11] First-person sequences (smoke_first_person.mjs): enter <=1.2, exit >=1.8,
 *      after .18 continuous seconds. .1+.079 is short, +.001 switches; a band
 *      sample cancels the dwell. Disabled resets both mode and dwell. The full
 *      20-step sequence's true spans are steps 5..11 and 19 (one-based).
 * [12] Rest lens (smoke_first_person_body.mjs): head [0,1.52,.02], crown
 *      [0,1.72,.03], height 1.7: y=1.52+.2*.45=1.61,
 *      z=.02+1.7*.055=.1135. Without crown y=1.7*.94=1.598;
 *      eyeHeight(.5)=.47.
 * [13] viewHeading=atan2(-sin yaw,-cos yaw): yaw 0 -> -pi,
 *      yaw pi/2 -> -pi/2 (the browser's signed-zero atan2 convention).
 * [14] Body threshold 60 degrees: 1 rad stays; 1.1 turns; 3 to -3 has
 *      wrapped difference .2831853 and stays; 4*pi to 1.1 turns. Equal
 *      angles at custom threshold zero stay because the comparison is strict.
 * [15] zoomFloorOf(null/.5/.8/2)=.8/.8/.8/2. Ceiling=max(floor,
 *      min(cap ?? 150,150)): (.8,null/34/500)=150/34/150; (2,1)=2.
 *      These are the floor/cap used by the engine's +1e-6 cap-toast test.
 *
 * The cases (inputs + expectations) live in shared/test-vectors/camera.json, shared with
 * the native client's C# tests; each case label starts with the [n] of its derivation above.
 * What stays inline below: constant pins, properties (frame-rate independence of `damp`,
 * a unit `orbitOffset`, no mutation of the input target) and the source pins that keep
 * `engine.ts` / `main.ts` calling this module instead of a second inline copy.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { embodyDispatch } from './embodyVectorDispatch.mjs';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = join(ROOT, 'client3d/src/scene/cameraMath.ts');
const FRAMING = join(ROOT, 'client3d/src/scene/cameraFraming.ts');

async function load() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const built = await esbuild.build({
      stdin: { contents: `export * from '${SRC}'; export { basePitchDeg } from '${FRAMING}';`,
        resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'camera.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'camera.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally { await rm(dir, { recursive: true, force: true }); }
}

const m = await load();
const { passed: vPassed, failed: vFailed } = runVectors(loadVectors('camera'), {
  ...embodyDispatch,
  fitDistance: m.fitDistance,
  worldCentreXZ: m.worldCentreXZ,
  basePitchDeg: m.basePitchDeg,
  clampPitchDeg: m.clampPitchDeg,
  wheelZoom: m.wheelZoom,
  zoomTowardCursor: m.zoomTowardCursor,
  damp: m.damp,
  flyAdvance: m.flyAdvance,
  flyEase: m.flyEase,
  orbitStep: m.orbitStep,
  cameraPose: m.cameraPose,
});

let passed = vPassed;
let failed = vFailed;
function check(label, ok) {
  if (ok) { passed += 1; console.log(`  ok   ${label}`); }
  else { failed += 1; console.log(`  FAIL ${label}`); }
}
const close = (a, b, eps = 1e-12) => Math.abs(a - b) <= eps;

console.log('\n(inline) constants, properties, source pins');
check('constants: wheel 0.0012, fly 1.6, frame dt 0.1, margin 1.15, empty 70',
  m.WHEEL_ZOOM_RATE === 0.0012 && m.FLY_RATE === 1.6 && m.MAX_FRAME_DT === 0.1
  && m.CAMERA_FIT_MARGIN === 1.15 && m.CAMERA_FIT_EMPTY === 70);
check('constants: orbit 0.005 rad/px, 0.25 deg/px, offset limits 35 / 85',
  m.ORBIT_YAW_PER_PX === 0.005 && m.ORBIT_PITCH_DEG_PER_PX === 0.25
  && m.PITCH_OFFSET_LIMIT_DEG === 35 && m.FIRST_PERSON_PITCH_OFFSET_LIMIT_DEG === 85);
// Two frames of dt/2 close the same share as one frame of dt:
// 1 − (1 − damp(dt/2))² = 1 − e^(−8·dt) = damp(dt) while dt <= 0.1.
check('damp is frame-rate independent (two half frames = one frame)',
  close(1 - (1 - m.damp(0.03)) ** 2, m.damp(0.06)));
const off = m.orbitOffset(0.7, 33);
check('orbitOffset is a unit vector', close(Math.hypot(off[0], off[1], off[2]), 1));
const out = [9, 9, 9];
check('orbitOffset writes into the given tuple and returns it', m.orbitOffset(0, 0, out) === out
  && close(out[2], 1));
const target = [10, 0, 10];
m.zoomTowardCursor(target, [20, 30], 100, 80);
check('zoomTowardCursor leaves the input target untouched',
  target[0] === 10 && target[1] === 0 && target[2] === 10);

const engine = await readFile(join(ROOT, 'client3d/src/scene/engine.ts'), 'utf8');
const main = await readFile(join(ROOT, 'client3d/src/main.ts'), 'utf8');
check('engine.ts imports the camera arithmetic from ./cameraMath',
  /from '\.\/cameraMath'/.test(engine));
for (const [what, re] of [
  ['the wheel factor', /Math\.exp\(e\.deltaY/],
  ['the exp easing', /Math\.exp\(-8 \* dt\)/],
  ['the fly rate', /dt \* 1\.6/],
  ['the orbit yaw step', /dx \* 0\.005/],
  ['the pitch-offset step', /dy \* 0\.25/],
]) check(`engine.ts holds no inline copy of ${what}`, !re.test(engine));
check('main.ts frames the world through cameraMath, no own fitDistance',
  /from '\.\/scene\/cameraMath'/.test(main) && !/function fitDistance/.test(main));

console.log(failed ? `\n${failed} FAILED, ${passed} ok` : `\nall ok (${passed})`);
process.exit(failed ? 1 : 0);
