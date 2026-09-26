#!/usr/bin/env node
/**
 * Smoke check for the STANDING REFERENCE of the clip library —
 * `standingHipsRef` / `rigHipsHeight` of `@anima/scene-render` and their
 * consumer `client3d/src/scene/figures.adaptExternalClips` (§ B5a: numbers,
 * never screenshots).
 *
 * Usage:  node client3d/scripts/smoke_rig_stand_ref.mjs
 *         (bundles the client modules itself; reads shared/models/rig/reference.fbx
 *          and the clips `idle` / `get-up-chair` in shared/models/clips — READ ONLY)
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * A clip's hips track is in the units of the rig it was retargeted onto: every
 * import drives its take onto `shared/models/rig/reference.fbx`. The client
 * rescales that track so a hips height equal to the STANDING reference lands
 * on the target rig's own rest hips. That reference used to be the idle
 * clip's hips median (110.179 units) — but the idle stance has slightly bent
 * knees, while the reference rig's REST hips (113.032) is the straight-legged
 * stance the take was measured against. Mapping 110.179 onto the rest lifted
 * every figure by 113.032 / 110.179 − 1 = 2.59 % of its hips height, ~2.85 cm
 * on the reference rig (hips 113.032 cm × 0.0259 = 2.93 cm of hips lift; the
 * feet follow with the legs' own bend, measured +2.87 cm). With the rig rest
 * as the reference the reference rig reproduces its raw take exactly.
 *
 * ---------------------------------------------------------------------------
 * Expected numbers, derived by hand
 * ---------------------------------------------------------------------------
 * [R1] standingHipsRef(113.032, 110.179) → {ref 113.032, source 'rig'}
 *      (a served rig with a finite, positive rest hips height wins).
 * [R2] standingHipsRef(undefined, 110.179) → {ref 110.179, source 'idle'};
 *      standingHipsRef(0, 110.179) and (NaN, 110.179) → 'idle' as well
 *      (0 and NaN are not a height).
 * [R3] standingHipsRef(undefined, null) → {ref null, source 'none'};
 *      clipHipsDrop(0.98013, 65.961, null) = 0 (no NaN).
 * [R4] clipHipsDrop(0.98013, 65.961, 113.032) = 0.98013·(1 − 65.961/113.032)
 *      65.961 / 113.032 = 0.58356 → 1 − 0.58356 = 0.41644
 *      = 0.98013 · 0.41644 = 0.40816 (±1e-5)
 * [R5] rigHipsHeight on shared/models/rig/reference.fbx = 113.032 (±0.01) —
 *      the number the analysis measured; a synthetic rig with hips at y=90 → 90;
 *      a rig without a hips bone → undefined.
 * [R6] REFERENCE RIG (instance scale 0.01, its centimetres → metres), idle
 *      clip through adaptExternalClips with the rig served (donorHipsY =
 *      113.032): lowest foot/toe bone over the bind floor (the lowest of the
 *      same bones in the bind pose), median over the clip, in cm:
 *      |value| ≤ 0.3 cm (raw take: +0.01 — the clip IS on this rig, the
 *      rescale factor is 113.032 / 113.032 = 1, nothing is lifted).
 *      Counter-probe in the same run with donorHipsY omitted (idle fallback):
 *      ≥ 2.5 cm (measured +2.87; hand: the hips rise 2.59 % of 113.032 cm =
 *      2.93 cm, the straightening legs keep the feet within a few mm of that).
 *      The fallback says so in ONE console.warn per session.
 * [R7] get-up-chair, last 0.5 s (the figure is standing again), reference
 *      rig, rig served: LEFT foot lowest bone (LeftFoot / LeftToeBase /
 *      LeftToe_End) over the bind floor, median over the window:
 *      |value| ≤ 0.5 cm (measured −0.18 with the rig reference).
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const CLIP_DIR = join(ROOT, 'shared/models/clips');
const RIG_FILE = join(ROOT, 'shared/models/rig/reference.fbx');

globalThis.self = globalThis;
if (!globalThis.window) globalThis.window = globalThis;
if (!globalThis.document) {
  globalThis.document = {
    createElement: () => ({ style: {}, getContext: () => null, setAttribute() {} }),
  };
}

let failed = 0;
let passed = 0;
function check(label, ok, detail) {
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
  }
}
const near = (label, actual, expected, eps) =>
  check(label, Number.isFinite(actual) && Math.abs(actual - expected) <= eps,
    `${Number(actual).toFixed(5)} (expected ${expected} ±${eps})`);

/** Bundle the client modules into ONE file next to this script (three stays
 *  external so the bundle and this script share one three). */
async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src');
    const entry = [
      `export { adaptExternalClips } from '${src}/scene/figures';`,
      'export { standingHipsRef, rigHipsHeight, clipHipsDrop, restPoseOf,'
        + ' restCorrections } from \'@anima/scene-render\';',
    ].join('\n');
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'client.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'client.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const arrayBufferOf = (buf) => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
const median = (a) => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
const keyOf = (name) => name.replace(/^mixamorig:?/i, '').replace(/[^a-z0-9_]/gi, '').toLowerCase();
const LEFT_FOOT = ['leftfoot', 'lefttoebase', 'lefttoeend', 'lefttoe_end'];
const FOOT = [...LEFT_FOOT, 'rightfoot', 'righttoebase', 'righttoeend', 'righttoe_end'];

async function main() {
  const THREE = await import('three');
  const { FBXLoader } = await import('three/addons/loaders/FBXLoader.js');
  const SkeletonUtils = await import('three/addons/utils/SkeletonUtils.js');
  const C = await loadClient();
  const fbx = new FBXLoader();

  console.log('[R1-R4] the rule');
  {
    const r = C.standingHipsRef(113.032, 110.179);
    check('[R1] rig served → the rig rest', r.ref === 113.032 && r.source === 'rig', JSON.stringify(r));
    const idle = C.standingHipsRef(undefined, 110.179);
    check('[R2] no rig → the idle median', idle.ref === 110.179 && idle.source === 'idle', JSON.stringify(idle));
    const zero = C.standingHipsRef(0, 110.179);
    check('[R2] rig height 0 → idle', zero.ref === 110.179 && zero.source === 'idle', JSON.stringify(zero));
    const nan = C.standingHipsRef(NaN, 110.179);
    check('[R2] rig height NaN → idle', nan.ref === 110.179 && nan.source === 'idle', JSON.stringify(nan));
    const none = C.standingHipsRef(undefined, null);
    check('[R3] neither → none', none.ref === null && none.source === 'none', JSON.stringify(none));
    const drop0 = C.clipHipsDrop(0.98013, 65.961, none.ref);
    check('[R3] clipHipsDrop without a reference = 0', drop0 === 0, String(drop0));
    near('[R4] clipHipsDrop(0.98013, 65.961, 113.032)', C.clipHipsDrop(0.98013, 65.961, 113.032), 0.40816, 1e-5);
  }

  console.log('[R5] rigHipsHeight');
  const refRig = fbx.parse(arrayBufferOf(await readFile(RIG_FILE)), '');
  const rigHips = C.rigHipsHeight(THREE, refRig);
  near('[R5] reference.fbx rest hips', rigHips, 113.032, 0.01);
  {
    const synth = new THREE.Group();
    const hips = new THREE.Bone();
    hips.name = 'mixamorig:Hips';
    hips.position.set(0, 90, 0);
    synth.add(hips);
    near('[R5] synthetic rig, hips at y=90', C.rigHipsHeight(THREE, synth), 90, 1e-9);
    const bare = new THREE.Group();
    const spine = new THREE.Bone();
    spine.name = 'Spine';
    bare.add(spine);
    check('[R5] no hips bone → undefined', C.rigHipsHeight(THREE, bare) === undefined);
  }

  console.log('[R6/R7] the reference rig reproduces its own take');
  const loadClip = async (kind) => {
    const obj = fbx.parse(arrayBufferOf(await readFile(join(CLIP_DIR, `${kind}.fbx`))), '');
    const c = obj.animations[0].clone();
    c.name = kind;
    return c;
  };
  const raw = { idle: await loadClip('idle'), 'get-up-chair': await loadClip('get-up-chair') };
  const template = fbx.parse(arrayBufferOf(await readFile(RIG_FILE)), '');
  template.updateMatrixWorld(true);
  const corrections = C.restCorrections(THREE, C.restPoseOf(THREE, refRig), template);
  const SCALE = 0.01;
  const adapt = (donorHipsY) => {
    const lib = Object.values(raw).map((c) => { const cc = c.clone(); cc.name = c.name; return cc; });
    return Object.fromEntries(C.adaptExternalClips(lib, template, corrections, donorHipsY)
      .map((c) => [c.name, c]));
  };
  /** Lowest of `keys` over the bind floor, cm, median over [t0, t1] at 30 fps. */
  const footLift = (clip, keys, t0, t1) => {
    const inst = SkeletonUtils.clone(template);
    inst.scale.setScalar(SCALE);
    const g = new THREE.Group();
    g.add(inst);
    g.updateMatrixWorld(true);
    const all = [];
    const sel = [];
    inst.traverse((o) => {
      if (!o.isBone) return;
      const k = keyOf(o.name);
      if (FOOT.includes(k)) all.push(o);
      if (keys.includes(k)) sel.push(o);
    });
    const v = new THREE.Vector3();
    const bindFloor = Math.min(...all.map((b) => b.getWorldPosition(v).y));
    const mixer = new THREE.AnimationMixer(inst);
    mixer.clipAction(clip).play();
    const lifts = [];
    for (let t = t0; t <= t1 + 1e-9; t += 1 / 30) {
      mixer.setTime(Math.min(t, clip.duration - 1e-4));
      g.updateMatrixWorld(true);
      lifts.push(Math.min(...sel.map((b) => b.getWorldPosition(v).y)) - bindFloor);
    }
    return { cm: median(lifts) * 100, bones: sel.length };
  };

  const withRig = adapt(rigHips);
  const idleRig = footLift(withRig.idle, FOOT, 0, withRig.idle.duration);
  check('[R6] idle, rig served: lowest foot bone |lift| <= 0.3 cm',
    idleRig.bones >= 4 && Math.abs(idleRig.cm) <= 0.3, `${idleRig.cm.toFixed(2)} cm over ${idleRig.bones} bones`);

  const warned = [];
  const warn = console.warn;
  console.warn = (...a) => warned.push(a.join(' '));
  let fallback;
  try {
    fallback = adapt(undefined);
    adapt(undefined);
  } finally {
    console.warn = warn;
  }
  const idleFallback = footLift(fallback.idle, FOOT, 0, fallback.idle.duration);
  check('[R6] counter-probe, idle fallback: lowest foot bone lift >= 2.5 cm',
    idleFallback.cm >= 2.5, `${idleFallback.cm.toFixed(2)} cm`);
  const standWarnings = warned.filter((w) => /standing height falls back/.test(w));
  check('[R6] the fallback warns once over two adaptations', standWarnings.length === 1,
    `${standWarnings.length}: ${standWarnings[0] ?? '-'}`);

  const gu = withRig['get-up-chair'];
  const left = footLift(gu, LEFT_FOOT, gu.duration - 0.5, gu.duration);
  check('[R7] get-up-chair, last 0.5 s: LEFT foot lowest bone |lift| <= 0.5 cm',
    left.bones >= 2 && Math.abs(left.cm) <= 0.5, `${left.cm.toFixed(2)} cm over ${left.bones} bones`);

  console.log(`\n${passed + failed} checks, ${failed} failures`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
