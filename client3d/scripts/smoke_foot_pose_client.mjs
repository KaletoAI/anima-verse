#!/usr/bin/env node
/**
 * Smoke check for the SHOD FIGURE in the 3D client — the wiring of the fitted
 * shoe's foot pose through `figures.ts` (`adaptExternalClips`'s shoe step,
 * `modelFootPose`, `Figure.setClipHeight`) and `clipGround.measureGroundOffsets`
 * (§ B5a: numbers, no screenshots). A SYNTHETIC rig, no clip files, no server.
 *
 * Usage:  node client3d/scripts/smoke_foot_pose_client.mjs
 *         (bundles the client modules itself; needs esbuild and three)
 *
 * THE RIG (metres, bind identity rotations) — the two-bone leg of
 * `scripts/smoke_foot_plant.mjs`, mirrored to two legs so a clip reaches the
 * eight-track bar of `adaptExternalClips`: root → `mixamorigHips` (0, 0.98, 0)
 * → per side `mixamorig<Side>UpLeg` (±0.10, 0, 0) → `…Leg` (0, −0.45, 0.15) →
 * `…Foot` (0, −0.45, −0.15), ankle at (±0.10, 0.08, 0) → `…ToeBase` (0, 0, 0).
 * A body SkinnedMesh, 100 % LeftFoot: (0.05, 0, 0.05), (−0.05, 0, −0.05) — the
 * bind soles on y = 0 — and (0, 0.30, 0); a shoe garment node
 * `garment_footwear_i_left` (userData.garment {kind footwear, item_id i, fsig
 * abc}) with its own SkinnedMesh, 100 % LeftFoot: (0, −0.02, −0.05),
 * (0, −0.02, 0.10), (0, 0.05, 0.10). `fp` as in the plant smoke (contacts on
 * the left only, root_lift_m 0.052, LeftFoot axis (1, 0, 0), deg 0).
 *
 * THE CLIPS: `idle` and `sit`, 31 keys at f/30 s, ten tracks — the hips
 * position (0, 0.98, 0) throughout and nine identity quaternion tracks (hips,
 * both UpLegs, Legs, Feet, ToeBases). The whole clip is stance (the ankle and
 * ball joints never move, their weights are 1), so the plant lowers the left
 * ankle by the sole's 0.032 m float over the lifted floor in every frame.
 *
 * [C1] `adaptExternalClips(clips, rig, undefined, undefined, {footPose, unitsPerCm
 *      0.01})`: every adapted clip carries `userData.footPosed` AND
 *      `footPlanted` = 'abc'; a second pass over the same inputs produces
 *      clips whose every track value is identical (the step is a function of
 *      its inputs — nothing accumulates). Without `shoes` no mark at all, and
 *      with a record of another fsig the values equal the bare pass's.
 * [C2] Review Focus 5 — the lift rides the height group: a `Figure` built
 *      with `footPose` plays `sit` on a 'seat' → `inst.position.y` = 0 (the
 *      bind anchor, no lift); back to `idle` on 'ground' → 0.052 (root_lift_m
 *      × scale 1, through `setClipHeight` → `heightCorrection`); 'lie' → 0.
 * [C3] Review Focus 2 — a template WITHOUT the shoe nodes: `modelFootPose`
 *      answers null (the record is not applied), a Figure of it stands at 0
 *      under 'ground'; the template WITH them answers the record itself.
 * [C4] `measureGroundOffsets(clips, rig, fp, footPoseLiftM(fp, 'ground'))` on
 *      the planted idle: the sole contacts stand ON the lifted floor, so the
 *      stored offset is 0 (|offset| ≤ 1e-6, never negative here); sampled by
 *      hand at the lift, the lowest point of the posed figure is the shoe
 *      mesh (its sole vertices at −0.02 − 0.032 + 0.052 = 0) and the bare
 *      soles of the body, riding the same Foot, stand the bind gap of 0.02
 *      above it. The bare chain (no foot pose) stores 0 as before.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

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
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;

async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src/scene');
    const pkg = join(ROOT, 'packages/scene-render/src');
    const entry = [
      `export { adaptExternalClips, Figure, modelFootPose } from '${src}/figures';`,
      `export { clipGroundOffset, measureGroundOffsets } from '${src}/clipGround';`,
      `export { footPoseLiftM, footPoseMatches } from '${pkg}/footPose';`,
      `export { normBoneName } from '${pkg}/clipRetarget';`,
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

async function main() {
  const THREE = await import('three');
  const { adaptExternalClips, Figure, modelFootPose, clipGroundOffset, measureGroundOffsets,
          footPoseLiftM } = await loadClient();

  const fp = {
    version: 1,
    source: { item_id: 'i', fsig: 'abc', glb_sha256: 'x' },
    bones: { 'mixamorig:LeftFoot': { axis: [1, 0, 0], deg: 0 } },
    root_lift_m: 0.052,
    contacts: {
      left: [
        { bone: 'mixamorig:LeftFoot', pos: [0, -0.02, -0.05], role: 'heel' },
        { bone: 'mixamorig:LeftToeBase', pos: [0, -0.02, 0.10], role: 'ball' },
        { bone: 'mixamorig:LeftToeBase', pos: [0, -0.015, 0.14], role: 'toe' },
      ],
      right: [],
    },
  };
  const skinned = (positions, boneIndex) => {
    const n = positions.length / 3;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(Array.from({ length: n * 4 }, (_, i) => (i % 4 === 0 ? boneIndex : 0)), 4));
    geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(Array.from({ length: n * 4 }, (_, i) => (i % 4 === 0 ? 1 : 0)), 4));
    return new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial());
  };
  /** the rig of the docstring; `shoes` false = the same body without the garment node */
  const rig = (shoes = true) => {
    const root = new THREE.Group();
    const bone = (name, x, y, z) => { const b = new THREE.Bone(); b.name = name; b.position.set(x, y, z); return b; };
    const hips = bone('mixamorigHips', 0, 0.98, 0);
    const chain = [hips];
    let leftFoot = null;
    for (const [side, x] of [['Left', 0.10], ['Right', -0.10]]) {
      const up = bone(`mixamorig${side}UpLeg`, x, 0, 0);
      const leg = bone(`mixamorig${side}Leg`, 0, -0.45, 0.15);
      const foot = bone(`mixamorig${side}Foot`, 0, -0.45, -0.15);
      const toe = bone(`mixamorig${side}ToeBase`, 0, 0, 0);
      hips.add(up); up.add(leg); leg.add(foot); foot.add(toe);
      chain.push(up, leg, foot, toe);
      if (side === 'Left') leftFoot = foot;
    }
    root.add(hips);
    const footIndex = chain.indexOf(leftFoot);
    const body = skinned([0.05, 0, 0.05, -0.05, 0, -0.05, 0, 0.30, 0], footIndex);
    root.add(body);
    let shoeMesh = null;
    if (shoes) {
      const shoe = new THREE.Group(); shoe.name = 'garment_footwear_i_left';
      shoe.userData.garment = { kind: 'footwear', item_id: 'i', fsig: 'abc', side: 'left' };
      shoeMesh = skinned([0, -0.02, -0.05, 0, -0.02, 0.10, 0, 0.05, 0.10], footIndex);
      shoe.add(shoeMesh);
      root.add(shoe);
    }
    root.updateMatrixWorld(true);
    const skeleton = new THREE.Skeleton(chain);
    body.bind(skeleton);
    if (shoeMesh) shoeMesh.bind(skeleton);
    return root;
  };
  const TIMES = Array.from({ length: 31 }, (_, f) => f / 30);
  const ID = TIMES.flatMap(() => [0, 0, 0, 1]);
  const clip = (name) => new THREE.AnimationClip(name, 1, [
    new THREE.VectorKeyframeTrack('mixamorigHips.position', TIMES, TIMES.flatMap(() => [0, 0.98, 0])),
    ...['Hips', 'LeftUpLeg', 'LeftLeg', 'LeftFoot', 'LeftToeBase', 'RightUpLeg', 'RightLeg', 'RightFoot', 'RightToeBase']
      .map((b) => new THREE.QuaternionKeyframeTrack(`mixamorig${b}.quaternion`, TIMES, ID)),
  ]);
  const library = () => [clip('idle'), clip('sit')];
  const sameValues = (a, b) => a.length === b.length && a.every((c, i) => c.tracks.length === b[i].tracks.length
    && c.tracks.every((t, j) => t.name === b[i].tracks[j].name && t.values.length === b[i].tracks[j].values.length
      && t.values.every((x, k) => x === b[i].tracks[j].values[k])));

  console.log('[C1] the shoe step of adaptExternalClips: marked, idempotent, bare otherwise');
  const shoes = { footPose: fp, unitsPerCm: 0.01 };
  const first = adaptExternalClips(library(), rig(), undefined, undefined, shoes);
  check('both clips survive the adaptation', first.length === 2, `${first.length} clips`);
  check('every adapted clip carries footPosed = footPlanted = abc',
    first.every((c) => c.userData.footPosed === 'abc' && c.userData.footPlanted === 'abc'));
  const second = adaptExternalClips(library(), rig(), undefined, undefined, shoes);
  check('a second pass over the same inputs: every value identical', sameValues(first, second));
  const bare = adaptExternalClips(library(), rig());
  check('without shoes: no mark', bare.every((c) => !c.userData.footPosed && !c.userData.footPlanted));
  const other = adaptExternalClips(library(), rig(), undefined, undefined, { ...shoes, footPose: { ...fp, source: { ...fp.source, fsig: 'zzz' } } });
  check('another fsig: the bare pass, value for value, unmarked', sameValues(bare, other) && !other[0].userData.footPosed);
  check('the shod clip differs from the bare one (the plant moved the leg)', !sameValues(first, bare));

  console.log('\n[C2] the lift rides the height group (Review Focus 5)');
  const template = rig();
  const figure = new Figure({
    name: 'shod', template, clips: adaptExternalClips(library(), template, undefined, undefined, shoes), scale: 1,
    height: 1.70, assignOnly: true, noClips: false, tier: 'full', libraryFits: true, footPose: fp,
  });
  const inst = figure.root.children[0];
  figure.play('sit', false, 0, 'seat');
  check('sit on a seat: height term 0 — inst.position.y = 0', near(inst.position.y, 0), inst.position.y.toFixed(7));
  figure.play('idle', false, 0, 'ground');
  check('back to idle on the ground: root_lift_m through heightCorrection — 0.052', near(inst.position.y, 0.052), inst.position.y.toFixed(7));
  figure.play('sit', false, 0, 'lie');
  check('lie: 0 again', near(inst.position.y, 0), inst.position.y.toFixed(7));
  figure.play('idle', false, 0, 'ground');
  check('and ground once more: 0.052', near(inst.position.y, 0.052));

  console.log('\n[C3] a model swap to a template without the shoe nodes (Review Focus 2)');
  check('modelFootPose(template with shoes) → the record', modelFootPose(rig(), fp) === fp);
  check('modelFootPose(template without shoes) → null', modelFootPose(rig(false), fp) === null);
  check('modelFootPose(…, null) → null', modelFootPose(rig(), null) === null);
  const bareTemplate = rig(false);
  const bareFigure = new Figure({
    name: 'bare', template: bareTemplate, clips: adaptExternalClips(library(), bareTemplate, undefined, undefined, shoes), scale: 1,
    height: 1.70, assignOnly: true, noClips: false, tier: 'full', libraryFits: true, footPose: modelFootPose(bareTemplate, fp),
  });
  bareFigure.play('idle', false, 0, 'ground');
  check('a figure without the shoes stands at 0 under ground (lift 0)', near(bareFigure.root.children[0].position.y, 0));

  console.log('\n[C4] measureGroundOffsets with the lift: the sole on the floor');
  const probeRig = rig();
  const planted = adaptExternalClips(library(), probeRig, undefined, undefined, shoes);
  measureGroundOffsets(planted, probeRig, fp, footPoseLiftM(fp, 'ground'));
  const off = clipGroundOffset(planted[0]);
  check('the planted idle stores offset 0 (|offset| ≤ 1e-6, not negative)', Math.abs(off) <= 1e-6 && off >= -1e-6, off.toExponential(3));
  {
    // Own sampling at the lift: the shoe sole is the lowest point, on y = 0.
    const r = rig();
    const mixer = new THREE.AnimationMixer(r);
    const a = mixer.clipAction(planted[0]); a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true; a.play();
    r.position.y = footPoseLiftM(fp, 'ground');
    let body = Infinity; let shoe = Infinity;
    const v = new THREE.Vector3();
    for (const t of [0, 0.5, 1]) {
      a.paused = false; mixer.setTime(t); r.updateMatrixWorld(true);
      r.traverse((o) => {
        if (!o.isSkinnedMesh) return;
        const garment = o.parent?.name === 'garment_footwear_i_left';
        for (let i = 0; i < o.geometry.attributes.position.count; i++) {
          o.getVertexPosition(i, v); o.localToWorld(v);
          if (garment) shoe = Math.min(shoe, v.y); else body = Math.min(body, v.y);
        }
      });
    }
    check('the lowest sampled point is the shoe sole, on the floor (0)', near(shoe, 0), shoe.toFixed(7));
    check('the bare soles of the body stand the bind gap 0.02 above it', near(body, 0.020), body.toFixed(7));
  }
  const bareClips = adaptExternalClips(library(), rig());
  measureGroundOffsets(bareClips, rig());
  check('the bare chain stores 0 as before', clipGroundOffset(bareClips[0]) === 0);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
