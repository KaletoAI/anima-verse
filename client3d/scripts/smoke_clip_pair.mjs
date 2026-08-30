#!/usr/bin/env node
/**
 * Smoke check for PAIR CLIPS at the consumer (§ B5a: numbers, no screenshots):
 * the two halves of a CMU-converted pair clip loaded with three's own
 * FBXLoader, the root path the client extracts from them, and the anchor
 * transformation the server and the client agree on (§ A8a).
 *
 * Usage:  node client3d/scripts/smoke_clip_pair.mjs
 *         (needs three, esbuild and the converted clips in shared/models/clips:
 *          handshake__a.fbx / handshake__b.fbx / handshake.json)
 *
 * Hand-derived expectations
 * -------------------------
 * The converter (`app/blender/scripts/cmu_clip.py`) writes both halves in ONE
 * frame: origin at the XZ midpoint of the two roots at the anchor frame, +X
 * pointing from A to B. The sidecar states that frame's numbers; the
 * handshake's are `root_distance_m` at `anchor_s` 1.1 with A at
 * (−d/2, 0) and B at (+d/2, 0) (rounded to 3 decimals in the file). So:
 *
 *   [1] naming/role: `parse` of the two file names yields the halves, the
 *       client indexes them as `handshake__a` / `handshake__b`
 *       (`isPairClipName` true; `idle` false, `a__b` style names that are
 *       not a/b roles false).
 *
 *   [2] the root path of each half, read from the raw hips position track in
 *       Mixamo centimetres → metres: at `anchor_s` A sits at x = −d/2 (0.317 after the contact fit) and
 *       B at x = +d/2 (±0.02 m — the sidecar rounds, and the client
 *       interpolates between 30 fps keys), both at z = 0 (±0.02); the two
 *       roots `root_distance_m` apart (±0.03). At t = 0 they are 1.98 m minus
 *       the contact-fit shift apart (the actors started 1.98 m apart; the
 *       converter moves both halves `contact.shift_m` towards each other so
 *       the rig's hands meet as the actors' did): the walk-up.
 *
 *   [3] the anchor transformation, the SAME formula on both sides
 *       (`interaction_engine._rotate` ↔ `npcs.tickInteraction`):
 *       x' = ax + x·cos(yaw) + z·sin(yaw), z' = az − x·sin(yaw) + z·cos(yaw).
 *       With the server's yaw for a partner standing in +Z of the actor
 *       (yaw = −π/2, see `scripts/smoke_interaction.py` [2]) and the anchor
 *       at (10, 22), A's root at the anchor moment lands at (10, 22 − d/2)
 *       and B's at (10, 22 + d/2): A stands south, B north, d = `root_distance_m` apart,
 *       the line between them along +Z exactly as the server placed them.
 *
 *   [4] `rootPathAt` clamps: before the first key it answers the first key,
 *       after the last the last, and between two keys it interpolates
 *       linearly (hand case: keys at t = 0 → x 0 and t = 1 → x 2 give x = 1
 *       at t = 0.5).
 *
 *   [5] the time base: the clip's duration equals the sidecar's
 *       `duration_s` (±1 frame = 0.034 s) — the server ends the interaction
 *       on that number, the client seeks the action with it.
 *
 *   [6] TRACK SHAPE — the Mixamo library's: rotation tracks plus ONE
 *       position track (the hips), no scale tracks. Checked on all three
 *       converted clips. And the consequence, measured the way the ADMIN
 *       PREVIEW applies a clip (every track but the hips position, straight
 *       onto a metre-scaled GLB, `Model3DViewer.tsx`): on `Test3_mia.glb`
 *       the posed skeleton's body length (longest extent of the joint cloud
 *       — the admin pivot may turn it onto any axis) stays within 0.7 … 1.3
 *       of its bind length and the diagonal under 2.6 m; the library's own
 *       `idle-wait.fbx` is run first as the reference of the harness. The
 *       2026-08-21 finding was the opposite — per-bone translation/scale
 *       tracks in centimetres left "a stick figure of the mesh" (measured on
 *       the character model of the finding: 151 m joint extent against 1.4 m
 *       with the fixed export); the RED counter-probe below re-creates it by
 *       adding one such track (100x the bone's rest offset) and watches the
 *       body length run away (> 2×).
 */
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
    const entry = `export { extractRootPath, isPairClipName, rootPathAt } from '${src}/figures';`;
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
  const { extractRootPath, isPairClipName, rootPathAt } = await loadClient();
  const side = JSON.parse(await readFile(join(CLIP_DIR, 'handshake.json'), 'utf8'));
  const geo = side.geometry;

  console.log('[1] naming');
  check('handshake__a is a pair half', isPairClipName('handshake__a'));
  check('handshake__b is a pair half', isPairClipName('handshake__b'));
  check('idle is not', !isPairClipName('idle'));
  check('x__c is not (only a/b are roles)', !isPairClipName('x__c'));

  console.log('\n[2] root paths of the two halves (raw FBX, hips track)');
  const fbx = new FBXLoader();
  const paths = {};
  for (const role of ['a', 'b']) {
    const obj = fbx.parse(arrayBufferOf(await readFile(join(CLIP_DIR, `handshake__${role}.fbx`))), '');
    const clip = obj.animations?.[0];
    check(`handshake__${role}: one animation with tracks`, !!clip && clip.tracks.length > 8,
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
  // The walk-up: the actors started 1.98 m apart; minus the contact-fit shift
  // (`geometry.contact.shift_m`, 0.106 m — both halves moved towards each
  // other so the rig's hands meet like the actors') that is what the sidecar
  // states as the start distance.
  const startD = Math.hypot(geo.roles.a.start_xz_m[0] - geo.roles.b.start_xz_m[0],
    geo.roles.a.start_xz_m[1] - geo.roles.b.start_xz_m[1]);
  near('the take starts 1.98 m minus the contact shift apart', Math.hypot(a0.x - b0.x, a0.z - b0.z),
    1.98 - (geo.contact?.shift_m ?? 0), 0.05);
  near('… which is the sidecar start distance', Math.hypot(a0.x - b0.x, a0.z - b0.z), startD, 0.03);
  check('A starts on the −X side, B on +X', a0.x < -0.5 && b0.x > 0.5, `${a0.x.toFixed(2)} / ${b0.x.toFixed(2)}`);

  console.log('\n[3] the anchor transformation (server yaw convention)');
  const anchor = { x: 10, z: 22 };
  const yaw = -Math.PI / 2;
  const wa = place(anchor, yaw, a);
  const wb = place(anchor, yaw, b);
  near('A lands south of the anchor: x', wa.x, 10, 0.02);
  near('A lands south of the anchor: z', wa.z, 22 - geo.root_distance_m / 2, 0.02);
  near('B lands north of the anchor: x', wb.x, 10, 0.02);
  near('B lands north of the anchor: z', wb.z, 22 + geo.root_distance_m / 2, 0.02);
  // the clip's +X axis itself must come out as world +Z
  const ux = place({ x: 0, z: 0 }, yaw, { x: 1, z: 0 });
  near('clip +X → world +Z (x)', ux.x, 0, 1e-9);
  near('clip +X → world +Z (z)', ux.z, 1, 1e-9);

  console.log('\n[4] rootPathAt — clamping and interpolation (hand cases)');
  const toy = { times: new Float32Array([0, 1]), xz: new Float32Array([0, 0, 2, 4]) };
  near('before the first key → first key', rootPathAt(toy, -1).x, 0, 1e-9);
  near('after the last key → last key', rootPathAt(toy, 5).x, 2, 1e-9);
  near('midway → linear (x)', rootPathAt(toy, 0.5).x, 1, 1e-9);
  near('midway → linear (z)', rootPathAt(toy, 0.5).z, 2, 1e-9);

  console.log('\n[5] time base');
  near('clip duration == sidecar duration_s', paths.a.duration, side.duration_s, 0.034);
  near('both halves have the same duration', paths.b.duration, paths.a.duration, 1e-3);

  console.log('\n[6] track shape + the admin-preview application on a real GLB');
  const shape = {};
  for (const name of ['handshake__a', 'handshake__b', 'salsa__a', 'salsa__b', 'dance']) {
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
  for (const name of ['idle', 'handshake__a', 'salsa__b', 'dance']) {
    const e = adminApply(shape[name]);
    check(`${name} applied admin-style keeps the skeleton intact`,
      e.height > bind.height * 0.7 && e.height < bind.height * 1.3 && e.span < 2.6,
      `body length ${e.height.toFixed(3)} m (bind ${bind.height.toFixed(3)}), diagonal ${e.span.toFixed(3)} m`);
  }
  // RED counter-probe: one centimetre translation track on the spine — what
  // the old export wrote for every bone — and the skeleton runs away.
  {
    const clip = shape.handshake__a;
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
