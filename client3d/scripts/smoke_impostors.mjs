#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/impostors.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_impostors.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

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

/** Section (G2)'s mutant: every failure is held against the PROP, which is
 *  what turns one dropped download into a session without billboards. */
function refuseEveryFailure(source) {
  return source.replace("if (attempt === 'unbakeable') return 'refuse';",
                        "if (attempt !== 'baked') return 'refuse';");
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
    IMPOSTOR_TAIL_FACTOR, impostorBakeVerdict, impostorCorners, impostorFrame,
    impostorInWindow, impostorQuad, impostorReachM, impostorShare,
    impostorVisible, impostorYaw,
    instanceTier, instanceVisible, SCATTER_LOD_DEFAULTS } = lod;
  const vectors = runVectors(loadVectors('impostors'), lod);
  passed += vectors.passed; failed += vectors.failed;
  const cfg = SCATTER_LOD_DEFAULTS;   // 35 / 45 / 120, the defaults a player never touches

  console.log('\n(A) the window — where the meshes stop, the billboards start');
  check('the stage ends at 400 m', IMPOSTOR_FAR_M, 400);
  check('…and the meshes end at 120 m', cfg.cullM, 120);

  check('…and instanceTier really still draws it there',
    instanceTier(120, 1, cfg), 1);

  check('…and instanceTier has let go of it', instanceTier(120.1, 1, cfg), 2);

  check('a non-finite distance draws nothing',
    impostorInWindow(Number.NaN, cfg), false);

  console.log('\n(B) the thinning — it continues the mesh line');
  const REACH = Math.SQRT2 * 3 * 64;   // k = 2 cells to each side, the corner
  check('the tail keeps a quarter of the start', IMPOSTOR_TAIL_FACTOR, 0.25);
  check('the window really reaches 271.529 m, not 400',
    um(impostorReachM(cfg.cullM)), um(REACH));

  // instance 0 has hash 0 and therefore survives as long as anything does

  let drawn = 0;
  for (let i = 0; i < 1000; i += 1) if (impostorVisible(i, 195.76450198781714, cfg)) drawn += 1;
  // The hash is uniform to ~3.5 % over 1000 indices (`instanceHash`), so 0.15625
  // of 1000 must land near 156 — the band is three binomial sigmas
  // (sqrt(1000 · 0.15625 · 0.84375) = 11.5), which is what (I4) of
  // `smoke_scatter_math.mjs` derives for the low shares.
  check('B3 about 15.6 % of 1000 instances survive at the midpoint',
    drawn > 121 && drawn < 191, true);
  let nested = true;
  for (let i = 0; i < 1000; i += 1) {
    if (impostorVisible(i, 121, cfg) && !instanceVisible(i, 119, cfg)) nested = false;
  }
  check('B4 every billboard just outside the line is a mesh just inside it',
    nested, true);

  console.log('\n(C) the quad — a bake frame, and what it becomes in the world');
  check('the bake camera is raised by 10°',
    um(IMPOSTOR_ELEV_RAD), um((10 * Math.PI) / 180));
  check('…and keeps 5 % of air', IMPOSTOR_BAKE_PAD, 1.05);
  const frame = impostorFrame(4, 1);

  const quad = impostorQuad(8, frame);

  check('C3 the FOOT lands on the ground point',
    um(quad.centreY - (8 * Math.cos(IMPOSTOR_ELEV_RAD)) / 2), 0);
  check('C3 …while the quad\'s bottom edge hangs below it (the padding\'s air)',
    um(quad.centreY - quad.h / 2), um(-0.5616227237029956));
  const fatter = impostorQuad(8, { spanH: frame.spanH * 2, aspect: frame.aspect });

  check('C5 a degenerate model gets no frame at all',
    [impostorFrame(0, 1), impostorFrame(4, 0), impostorFrame(Number.NaN, 1)],
    [null, null, null]);

  console.log('\n(D) the billboard itself — the four corners, by hand');
  const { w, h, centreY } = quad;
  const corners = (camX, camY, camZ) =>
    impostorCorners(0, centreY, 0, w, h, camX, camZ).map(um3);
  const BOTTOM = um(-0.5616227237029956);
  const TOP = um(8.44008474780066);

  const R = um(1.48492424049175);

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

  console.log('\n(G) what a failed bake is remembered as');

  const harsh = await loadTs(LOD_SRC, refuseEveryFailure);
  check('G2 the "every failure is the prop\'s fault" mutant refuses a dropped download',
    harsh.impostorBakeVerdict('load-failed'), 'refuse');
  check('G2 …and the truth does not',
    [harsh.impostorBakeVerdict('no-renderer'), impostorBakeVerdict('no-renderer')],
    ['refuse', 'retry']);

  console.log('\n(F) the wiring, read off the source');
  const groundSrc = await readFile(GROUND_SRC, 'utf8');
  const impSrc = await readFile(IMP_SRC, 'utf8');
  const mainSrc = await readFile(MAIN_SRC, 'utf8');
  // NEU on a241a8aa: no lease API. Bake owns one lease only until render
  // returns or throws; both paths must leave held=0, with exactly one release.
  {
    const { transformSync } = await import('esbuild');
    const bakeSource = impSrc.slice(impSrc.indexOf('async function bake('), impSrc.indexOf('/** The lights'));
    const code = transformSync(bakeSource + '\nreturn bake;', { loader: 'ts' }).code;
    for (const throws of [false, true]) {
      let held = 0, releases = 0;
      const leaseGlb = async () => { held++; return { template: {}, release() { held--; releases++; } }; };
      const bake = new Function('renderer', 'leaseGlb', 'render', 'impostorBakeVerdict', 'cache', 'evict', code)(
        {}, leaseGlb, () => { if (throws) throw new Error('render failed'); return null; },
        impostorBakeVerdict, new Map(), () => {});
      await bake('test');
      check(`NEU bake lease released (throw=${throws})`, [held, releases], [0, 1]);
    }
  }

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
  check('F the pass obeys the verdict rather than deciding itself',
    impSrc.includes('const verdict = impostorBakeVerdict(attempt);'), true);
  check('F …and a "retry" leaves the cache untouched',
    impSrc.includes("if (verdict === 'retry') return;"), true);
  check('F …with nothing written before it',
    impSrc.indexOf('const verdict = impostorBakeVerdict(attempt);')
      < impSrc.indexOf('cache.set(url, verdict'), true);
  check('F a missing renderer is one of the attempts, not a silent refusal',
    impSrc.includes("let attempt: ImpostorBakeAttempt = 'no-renderer';"), true);
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
