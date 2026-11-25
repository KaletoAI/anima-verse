#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/rig_stand_ref.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_rig_stand_ref.mjs
 *         (bundles the client modules itself; reads shared/models/rig/reference.fbx
 *          and the clips `idle` / `get-up-chair` in shared/models/clips — READ ONLY)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
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
        + ' restCorrections, hipsTrackMedian, mapHipsTrack } from \'@anima/scene-render\';',
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
    const vectors = runVectors(loadVectors('hips_tracks'), {
      standingHipsRef: C.standingHipsRef,
      clipHipsDrop: C.clipHipsDrop,
      hipsTrackMedian: C.hipsTrackMedian,
      mapHipsTrack: (values, times, options) => {
        const out = C.mapHipsTrack(values, times, options);
        return { values: Array.from(out.values),
          rootPath: out.rootPath ? { times: Array.from(out.rootPath.times), xz: Array.from(out.rootPath.xz) } : null };
      },
    });
    passed += vectors.passed; failed += vectors.failed;
    const nan = C.standingHipsRef(NaN, 110.179);
    check('[R2] rig height NaN → idle', nan.ref === 110.179 && nan.source === 'idle', JSON.stringify(nan));
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
