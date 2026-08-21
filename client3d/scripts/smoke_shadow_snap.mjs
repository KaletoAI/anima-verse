#!/usr/bin/env node
/**
 * Smoke check for the SHADOW CAMERA'S TEXEL GRID —
 * `client3d/src/scene/shadowSnap.ts`, used by `scene/engine.ts`.
 *
 * Usage:  node client3d/scripts/smoke_shadow_snap.mjs
 *
 * Every number below is derived BY HAND in this docstring and never recorded
 * from the current output (§ B5a: numbers, not screenshots).
 *
 * WHY THIS FILE EXISTS. The sun of this client is not a world light: its
 * orthographic shadow frustum follows the camera target, so 140 m of shadow map
 * can serve a world of kilometres. Until 2026-08-21 it followed CONTINUOUSLY —
 * and a shadow map is a raster. Slide a raster by a third of a texel and every
 * depth sample lands on a different piece of ground: the shadow edge of a
 * figure, a fence or a roof crawls along its own outline on every frame the
 * camera pans ("shadow swimming"). The fix is the standard one — quantise the
 * frustum's centre to the light's own texel grid.
 *
 * ============================================================================
 * [1] ONE TEXEL
 * ============================================================================
 * The frustum is `SHADOW_HALF_M` = 70 m to each side over `SHADOW_MAP_PX` =
 * 2 048 texels:
 *     140 / 2048 = 0.068359375 m — 6.8 cm of ground per shadow texel.
 * Both numbers are powers of two times a small integer, so the quotient is an
 * exact binary fraction and nothing here rounds twice.
 *
 * ============================================================================
 * [2] THE LIGHT'S BASIS, at the sun `engine.ts` really hangs at 18:00
 * ============================================================================
 * There `sunAngle = π`, so the light stands at
 *     offset = (cos π · 60, max(0.08, sin π) · 80, 25) = (−60, 6.4, 25)
 * over its target. Its HORIZONTAL part (−60, 25) has length exactly 65 (a
 * 5-12-13 triangle scaled by 5), which makes the whole basis hand-derivable:
 *
 *   z = offset / |offset|, |offset| = √(3600 + 40.96 + 625) = √4265.96
 *                                   = 65.31431696…
 *     = (−0.918633…, 0.097987…, 0.382763…)
 *   x = normalize( up × z ) with up = (0, 1, 0); up × z = (z_z, 0, −z_x),
 *       whose length is the cosine of the elevation — so the normalisation
 *       cancels the 65.3143 and leaves the HORIZONTAL perpendicular exactly:
 *       x = (25, 0, 60) / 65 = (5/13, 0, 12/13) = (0.384615…, 0, 0.923076…)
 *   y = z × x, a unit vector perpendicular to both.
 *
 * (a) the texel size, (b) the basis, (c) that the three axes are unit-length,
 *     mutually perpendicular and right-handed.
 *
 * AND ONE LOAD-BEARING CONSEQUENCE: three puts the shadow camera AT THE LIGHT
 * and points it at the target (`LightShadow.updateMatrices`), so the frustum's
 * u/v origin is the light's, not the target's. The offset is parallel to z and
 * hence has neither u nor v — the two share one texel coordinate, which is why
 * moving both by the same world vector is the whole of the snap.
 *
 * ============================================================================
 * [3] A PAN SMALLER THAN A TEXEL DOES NOT MOVE THE RASTER
 * ============================================================================
 * That is the whole property. Start the target at the origin: its light-space
 * u = v = 0, already a whole multiple, so the snapped centre IS the origin.
 * Now walk the target 0.4 texels along the light's own u axis (0.02734375 m in
 * light space, i.e. 0.02734375 m of world travel along `x`): u/texel = 0.4,
 * `round(0.4)` = 0, so the shift is −0.4 texels and the snapped centre is the
 * origin AGAIN, to the last bit. The same holds for 0.49 texels; at 0.51 the
 * centre jumps by exactly one whole texel and never by a part of one.
 *
 * (d) 0.4 and 0.49 texels of travel: the snapped centre does not move at all.
 * (e) 0.51 texels: it moves by exactly one texel — 0.068359375 m, in light
 *     space, along u.
 * (f) A WORLD WALK. Moving the target 1 m along +x moves u by 1 · (5/13) =
 *     0.3846153846 m, which is
 *         (5/13) / (140/2048) = 10240 / 1820 = 5.6263736…  texels.
 *     So over a 1 m pan sampled at 1 cm the snapped centre takes the whole-
 *     texel indices round(5.6263736 · δ) for δ = 0…1, i.e. 0, 1, 2, 3, 4, 5, 6
 *     — SEVEN distinct positions instead of 101, and each of them is a whole
 *     texel apart from the one before it.
 * (g) EVERY snapped centre has whole-texel light-space coordinates, over 4 000
 *     arbitrary targets and four sun angles — that is the invariant itself.
 * (h) THE SHIFT IS PERPENDICULAR TO THE LIGHT: `dot(centre − target, z) = 0`,
 *     so the near/far range along the light axis is untouched (depth is
 *     quantised in a texel's VALUE, not in its position; the bias owns that
 *     end), and the displacement stays under half a texel per axis, i.e.
 *     √2 · 0.0341796875 = 0.04833 m — nothing a 140 m frustum notices.
 * (i) RED COUNTER-PROBE: the target UNSNAPPED (what the engine did before)
 *     lands on a whole texel only when it happens to; over the same 4 000
 *     targets the worst residual is essentially half a texel, i.e. the raster
 *     really was sliding by arbitrary fractions.
 * (j) A LIGHT STRAIGHT OVERHEAD is not a division by zero: `up × z`
 *     degenerates, the +Z reference takes over, and the basis stays finite and
 *     orthonormal.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/** The module under test is import-free by design (its header says so), so a
 *  transpile is all it takes. Should someone add a runtime import, this fails
 *  loudly — that is the alarm, not a nuisance. */
async function loadPure(rel) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'shadowsnap-'));
  try {
    const code = esbuild.transformSync(await readFile(join(ROOT, rel), 'utf8'),
                                       { loader: 'ts', format: 'esm' }).code;
    const file = join(dir, 'mod.mjs');
    await writeFile(file, code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = typeof actual === 'number' && Math.abs(actual - expected) <= eps;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}
function checkBelow(label, actual, ceiling) {
  const ok = typeof actual === 'number' && actual >= 0 && actual < ceiling;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual} (< ${ceiling})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected < ${ceiling}\n       actual   ${actual}`);
  }
}
function checkAbove(label, actual, floor) {
  const ok = typeof actual === 'number' && actual > floor;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual} (> ${floor})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected > ${floor}\n       actual   ${actual}`);
  }
}

const { SHADOW_HALF_M, SHADOW_MAP_PX, shadowTexelM, lightBasis, snapShadowCentre } =
  await loadPure('client3d/src/scene/shadowSnap.ts');

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];

// ── [1] one texel ───────────────────────────────────────────────────────────
console.log('[1] one shadow texel is 6.8 cm of ground');
check('the frustum half-width', SHADOW_HALF_M, 70);
check('the map resolution', SHADOW_MAP_PX, 2048);
check('(a) 140 / 2048', shadowTexelM(), 0.068359375, 0);
const TEXEL = shadowTexelM();

// ── [2] the light basis ─────────────────────────────────────────────────────
console.log('\n[2] the 18:00 sun of engine.ts, hand-derived');
const OFFSET = [Math.cos(Math.PI) * 60, Math.max(0.08, Math.sin(Math.PI)) * 80, 25];
check('the offset x', OFFSET[0], -60);
check('…y', OFFSET[1], 6.4);
check('…z', OFFSET[2], 25);
check('…and its horizontal part is exactly 65 long', Math.hypot(-60, 25), 65, 1e-12);
const B = lightBasis(OFFSET);
const LEN = Math.hypot(...OFFSET);
check('(b) z = offset / |offset|, x', B.z[0], -60 / LEN, 1e-12);
check('…y', B.z[1], 6.4 / LEN, 1e-12);
check('…z', B.z[2], 25 / LEN, 1e-12);
check('…x-axis = (5/13, 0, 12/13): x', B.x[0], 5 / 13, 1e-12);
check('…y', B.x[1], 0, 1e-12);
check('…z', B.x[2], 12 / 13, 1e-12);
check('(c) |x|', Math.hypot(...B.x), 1, 1e-12);
check('…|y|', Math.hypot(...B.y), 1, 1e-12);
check('…|z|', Math.hypot(...B.z), 1, 1e-12);
check('…x ⟂ y', dot(B.x, B.y), 0, 1e-12);
check('…x ⟂ z', dot(B.x, B.z), 0, 1e-12);
check('…y ⟂ z', dot(B.y, B.z), 0, 1e-12);
// right-handed: x × y = z
const cx = [B.x[1] * B.y[2] - B.x[2] * B.y[1],
            B.x[2] * B.y[0] - B.x[0] * B.y[2],
            B.x[0] * B.y[1] - B.x[1] * B.y[0]];
check('…and x × y = z', Math.hypot(...sub(cx, B.z)), 0, 1e-12);
// LOAD-BEARING: three positions the shadow camera AT THE LIGHT and points it at
// the target, so the frustum's own u/v origin is the LIGHT's. The offset is
// parallel to z and therefore has no u and no v at all — light and target snap
// to the same texel, and moving both by the same vector is enough.
check('the offset has no light-space u', dot(OFFSET, B.x), 0, 1e-12);
check('…and no v', dot(OFFSET, B.y), 0, 1e-12);

// ── [3] the snap ────────────────────────────────────────────────────────────
console.log('\n[3] a pan smaller than one texel does not move the raster');
const snap = (t) => snapShadowCentre({ target: t, offset: OFFSET });
const ORIGIN = snap([0, 0, 0]);
check('the origin snaps to itself', Math.hypot(...ORIGIN), 0, 0);
for (const frac of [0.4, 0.49]) {
  const step = frac * TEXEL;
  const moved = snap([step * B.x[0], step * B.x[1], step * B.x[2]]);
  check(`(d) ${frac} texels of pan move the centre by`,
    Math.hypot(...sub(moved, ORIGIN)), 0, 1e-12);
}
const over = 0.51 * TEXEL;
const jumped = snap([over * B.x[0], over * B.x[1], over * B.x[2]]);
check('(e) 0.51 texels of pan move it by exactly one texel',
  Math.hypot(...sub(jumped, ORIGIN)), TEXEL, 1e-12);
check('…along u, and not at all along v', dot(sub(jumped, ORIGIN), B.y), 0, 1e-12);

// (f) the world walk
const seen = new Set();
for (let i = 0; i <= 100; i += 1) {
  const c = snap([i / 100, 0, 0]);
  seen.add(Math.round(dot(c, B.x) / TEXEL));
}
check('(f) 1 m of pan at 1 cm — distinct raster positions', seen.size, 7);
check('…the last texel index', Math.max(...seen), 6);
check('…which is round(5.6263736…)', Math.round((5 / 13) / TEXEL), 6);

// (g)…(i) the invariant over arbitrary targets and four sun angles
let worstResidual = 0;
let worstUnsnapped = 0;
let worstDepth = 0;
let worstShift = 0;
let n = 0;
for (const hour of [7, 11, 15, 18]) {
  const ang = ((hour - 6) / 12) * Math.PI;
  const off = [Math.cos(ang) * 60, Math.max(0.08, Math.sin(ang)) * 80, 25];
  const b = lightBasis(off);
  for (let i = 0; i < 1000; i += 1) {
    // A deterministic spread over a kilometre of world, deliberately not on
    // any lattice — 0.1234567 m per step against a 6.8 cm texel.
    const t = [(i * 0.1234567) % 1000 - 500, ((i * 7) % 40) - 20,
               (i * 0.7654321) % 1000 - 500];
    const c = snapShadowCentre({ target: t, offset: off });
    const u = dot(c, b.x) / TEXEL;
    const v = dot(c, b.y) / TEXEL;
    worstResidual = Math.max(worstResidual, Math.abs(u - Math.round(u)),
                             Math.abs(v - Math.round(v)));
    const u0 = dot(t, b.x) / TEXEL;
    worstUnsnapped = Math.max(worstUnsnapped, Math.abs(u0 - Math.round(u0)));
    worstDepth = Math.max(worstDepth, Math.abs(dot(sub(c, t), b.z)));
    worstShift = Math.max(worstShift, Math.hypot(...sub(c, t)));
    n += 1;
  }
}
check(`(g) whole-texel light-space coordinates over ${n} targets`, worstResidual, 0, 1e-9);
check('(h) the shift never moves the light along its own axis', worstDepth, 0, 1e-9);
checkBelow('…and stays under half a texel per axis, metres', worstShift,
  Math.SQRT2 * TEXEL / 2);
checkAbove('(i) RED: the UNSNAPPED target lands anywhere in the texel',
  worstUnsnapped, 0.49);

// (j) the degenerate light
console.log('\n[4] a light straight overhead is not a division by zero');
const up = lightBasis([0, 1, 0]);
check('(j) |x|', Math.hypot(...up.x), 1, 1e-12);
check('…|y|', Math.hypot(...up.y), 1, 1e-12);
check('…x ⟂ z', dot(up.x, up.z), 0, 1e-12);
const upSnap = snapShadowCentre({ target: [3.3, 7, -2.7], offset: [0, 1, 0] });
check('…and the snap stays finite',
  Number.isFinite(upSnap[0] + upSnap[1] + upSnap[2]) ? 1 : 0, 1);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
