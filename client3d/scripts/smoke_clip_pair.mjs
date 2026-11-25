#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/clip_pair.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_clip_pair.mjs
 *         (needs three, esbuild and the converted clips in shared/models/clips:
 *          greeting-handshake__a.fbx / __b.fbx / greeting-handshake.json — the
 *          animation studio's handshake, anims/greeting-handshake.py)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runPairVectors } from './pairVectorDispatch.mjs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const CLIP_DIR = join(ROOT, 'shared/models/clips');

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
  if (ok) { passed += 1; console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`); }
  else { failed += 1; console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`); }
}
const near = (label, actual, expected, eps) =>
  check(label, Number.isFinite(actual) && Math.abs(actual - expected) <= eps,
    `${Number(actual).toFixed(4)} (expected ${expected} ±${eps})`);

async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src/scene');
    const entry = `export { extractRootPath, rootPathAt } from '${src}/figures';`;
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

function arrayBufferOf(buf) {
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

/** The server's placement formula (interaction_engine._rotate). */
function place(anchor, yaw, p) {
  const c = Math.cos(yaw);
  const s = Math.sin(yaw);
  return { x: anchor.x + p.x * c + p.z * s, z: anchor.z - p.x * s + p.z * c };
}

async function main() {
  const { FBXLoader } = await import('three/addons/loaders/FBXLoader.js');
  const { extractRootPath, rootPathAt } = await loadClient();
  const side = JSON.parse(await readFile(join(CLIP_DIR, 'greeting-handshake.json'), 'utf8'));
  const geo = side.geometry;

  const vectors = await runPairVectors('pair_clip_geometry');
  passed += vectors.passed; failed += vectors.failed;

  console.log('\n[2] root paths of the two halves (raw FBX, hips track)');
  const fbx = new FBXLoader();
  const paths = {};
  for (const role of ['a', 'b']) {
    const obj = fbx.parse(arrayBufferOf(await readFile(join(CLIP_DIR, `greeting-handshake__${role}.fbx`))), '');
    const clip = obj.animations?.[0];
    check(`greeting-handshake__${role}: one animation with tracks`, !!clip && clip.tracks.length > 8,
      clip ? `${clip.tracks.length} tracks, ${clip.duration.toFixed(3)} s` : 'none');
    paths[role] = { path: extractRootPath(clip), duration: clip.duration };
  }
  const tA = geo.anchor_s;
  const a = rootPathAt(paths.a.path, tA);
  const b = rootPathAt(paths.b.path, tA);
  const wantA = geo.roles.a.anchor_xz_m;
  const wantB = geo.roles.b.anchor_xz_m;
  near('A at the anchor moment: x', a.x, wantA[0], 0.02);
  near('A at the anchor moment: z', a.z, wantA[1], 0.02);
  near('B at the anchor moment: x', b.x, wantB[0], 0.02);
  near('B at the anchor moment: z', b.z, wantB[1], 0.02);
  near('roots root_distance_m apart at the anchor', Math.hypot(a.x - b.x, a.z - b.z), geo.root_distance_m, 0.03);
  const a0 = rootPathAt(paths.a.path, 0);
  const b0 = rootPathAt(paths.b.path, 0);
  // No walk-up: the studio halves stand still, so t = 0 is the anchor pose.
  near('root_distance_m = hypot(0.72, 0.14)', geo.root_distance_m, Math.hypot(0.72, 0.14), 0.001);
  near('A at t = 0 where it is at the anchor: x', a0.x, a.x, 0.02);
  near('A at t = 0 where it is at the anchor: z', a0.z, a.z, 0.02);
  near('B at t = 0 where it is at the anchor: x', b0.x, b.x, 0.02);
  near('B at t = 0 where it is at the anchor: z', b0.z, b.z, 0.02);
  near('… which is the sidecar start of A', a0.x, geo.roles.a.start_xz_m[0], 0.02);
  near('… and of B', b0.x, geo.roles.b.start_xz_m[0], 0.02);
  check('A on the −X side, B on +X', a0.x < -0.3 && b0.x > 0.3, `${a0.x.toFixed(2)} / ${b0.x.toFixed(2)}`);

  console.log('\n[3] the anchor transformation (server yaw convention)');
  const anchor = { x: 10, z: 22 };
  const yaw = -Math.PI / 2;
  const wa = place(anchor, yaw, a);
  const wb = place(anchor, yaw, b);
  near('A lands south of the anchor: x', wa.x, 10, 0.02);
  near('A lands south of the anchor: z', wa.z, 22 - geo.root_distance_m / 2, 0.02);
  near('B lands north of the anchor: x', wb.x, 10, 0.02);
  near('B lands north of the anchor: z', wb.z, 22 + geo.root_distance_m / 2, 0.02);
  console.log('\n[5] time base');
  near('clip duration == sidecar duration_s', paths.a.duration, side.duration_s, 0.034);
  near('both halves have the same duration', paths.b.duration, paths.a.duration, 1e-3);

  console.log('\n[6] track shape + the admin-preview application on a real GLB');
  const shape = {};
  for (const name of ['greeting-handshake__a', 'greeting-handshake__b', 'dancing-together__a', 'dancing-together__b', 'dance']) {
    const obj = fbx.parse(arrayBufferOf(await readFile(join(CLIP_DIR, `${name}.fbx`))), '');
    const clip = obj.animations[0];
    const pos = clip.tracks.filter((t) => t.name.endsWith('.position'));
    const scl = clip.tracks.filter((t) => t.name.endsWith('.scale'));
    const rot = clip.tracks.filter((t) => t.name.endsWith('.quaternion'));
    check(`${name}: rotations + the hips position only`,
      pos.length === 1 && /Hips\.position$/.test(pos[0].name) && scl.length === 0 && rot.length >= 22,
      `${rot.length} quaternion, ${pos.length} position (${pos.map((t) => t.name).join(',')}), ${scl.length} scale`);
    shape[name] = clip;
  }
  const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
  const THREE = await import('three');
  const glbBytes = arrayBufferOf(await readFile(join(ROOT, 'client3d/public/models/Test3_mia.glb')));
  const gltf = await new Promise((res, rej) => new GLTFLoader().parse(glbBytes, '', res, rej));
  const model = gltf.scene;
  model.updateMatrixWorld(true);
  const bones = [];
  model.traverse((o) => { if (o.isBone) bones.push(o); });
  // The admin preview turns the whole pivot to undo the clip's armature
  // rotation (hips quaternions are authored for a +90° X armature), so the
  // posed skeleton may lie along any axis here: measure the LONGEST extent
  // of the joint cloud (the body length) and the diagonal, not "height".
  const extent = () => {
    model.updateMatrixWorld(true);
    const box = new THREE.Box3();
    const v = new THREE.Vector3();
    for (const b of bones) box.expandByPoint(b.getWorldPosition(v));
    const size = box.getSize(new THREE.Vector3());
    return { height: Math.max(size.x, size.y, size.z), span: size.length() };
  };
  const bind = extent();
  check('Test3_mia binds with a plausible skeleton height', bind.height > 1.2 && bind.height < 2.2,
    `${bind.height.toFixed(3)} m`);
  // The admin preview's application: every track but the hips position, names
  // matched by the bone names the GLB carries (mixamorig prefix without colon).
  const adminApply = (clip) => {
    const tracks = clip.tracks
      .filter((t) => !(/hips/i.test(t.name) && t.name.endsWith('.position')))
      .map((t) => { const c = t.clone(); c.name = c.name.replace(/^mixamorig:?/, 'mixamorig'); return c; });
    const c = new THREE.AnimationClip(clip.name, clip.duration, tracks);
    const mixer = new THREE.AnimationMixer(model);
    const action = mixer.clipAction(c);
    action.play();
    mixer.update(clip.duration * 0.45);
    const e = extent();
    action.stop();
    mixer.stopAllAction();
    mixer.uncacheClip(c);
    return e;
  };
  // the harness reference: the free library's own idle (CMU), present in git
  shape.idle = fbx.parse(arrayBufferOf(await readFile(join(CLIP_DIR, 'idle.fbx'))), '').animations[0];
  for (const name of ['idle', 'greeting-handshake__a', 'dancing-together__b', 'dance']) {
    const e = adminApply(shape[name]);
    check(`${name} applied admin-style keeps the skeleton intact`,
      e.height > bind.height * 0.7 && e.height < bind.height * 1.3 && e.span < 2.6,
      `body length ${e.height.toFixed(3)} m (bind ${bind.height.toFixed(3)}), diagonal ${e.span.toFixed(3)} m`);
  }
  // RED counter-probe: one centimetre translation track on the spine — what
  // the old export wrote for every bone — and the skeleton runs away.
  {
    const clip = shape['greeting-handshake__a'];
    // Centimetre values on a metre skeleton = 100x the bone's own rest
    // offset (the real Rosi model of the finding has metre bones; the public
    // test rigs here carry centimetre bones, so the factor is applied to the
    // rest offset rather than hard-coding "7.24").
    const spineRest = bones.find((b) => /Spine$/.test(b.name));
    const r = spineRest.position.clone().multiplyScalar(100);
    const bad = clip.clone();
    bad.tracks.push(new THREE.VectorKeyframeTrack(`${spineRest.name}.position`, [0, clip.duration],
      [r.x, r.y, r.z, r.x, r.y, r.z]));
    const e = adminApply(bad);
    check('RED: a centimetre translation track blows the skeleton up (> 2x height)',
      e.height > bind.height * 2, `height ${e.height.toFixed(3)} m vs bind ${bind.height.toFixed(3)}`);
  }

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
