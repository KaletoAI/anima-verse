#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/shadow_snap.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_shadow_snap.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { vectorCase, vectorArgs, vectorValue } from './e3VectorSupport.mjs';
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

function vector(label, fns) {
  const result = vectorCase("sky_light", label, fns);
  passed += result.passed; failed += result.failed;
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
vector("[1] shadow_snap: (a) 140 / 2048", { shadowTexelM: (...args) => shadowTexelM(...vectorArgs(args)) });
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
vector("[2] shadow_snap: …x-axis = (5/13, 0, 12/13): x", { lightBasisValue: (args, path) => vectorValue(lightBasis(...vectorArgs(args)), path) });
vector("[2] shadow_snap: …y", { lightBasisValue: (args, path) => vectorValue(lightBasis(...vectorArgs(args)), path) });
vector("[2] shadow_snap: …z", { lightBasisValue: (args, path) => vectorValue(lightBasis(...vectorArgs(args)), path) });
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
