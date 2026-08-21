#!/usr/bin/env node
/**
 * Smoke check for the CLIP GROUND OFFSET — `client3d/src/scene/clipGround.ts`
 * and its one consumer, `figures.Figure.play` (§ B5a: numbers, no screenshots).
 *
 * Usage:  node client3d/scripts/smoke_clip_ground.mjs
 *         (bundles the client modules itself; needs three + the shared clips)
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * Acceptance round 2026-08-13, finding 3: a character crossing painted water
 * SWAM — and swam a third of a metre over the lake. The clip chain was right
 * (terrain `move_anim` → payload → `moveClip` → bound clip); the CLIP is
 * authored on a water line. Measured on the library's own `swim.fbx`: hip
 * median 78.38 against the standing reference of 110.13 Mixamo units, the body
 * 74° prone. A figure is anchored ONCE, in its bind pose (`Figure`'s
 * constructor drops the instance by `box.min.y`), so a clip that holds the body
 * higher than the bind pose holds it over the ground — measured at the END of
 * the chain on three real Mixamo rigs: +0.26 … +0.32 m.
 *
 * The fix carries no clip name: measure every adapted clip once, apply the
 * measurement only while the figure MOVES over terrain.
 *
 * ---------------------------------------------------------------------------
 * [1] groundOffsetOf(clipMinY, bindMinY) — the pure rule, hand-derived
 * ---------------------------------------------------------------------------
 * The drop is `clipMinY − bindMinY`, and only when that is positive:
 *
 *   (0.30, 0.00) -> 0.30    the swim case: the body hangs 30 cm over the
 *                           anchor, so the figure has to come down 30 cm
 *   (0.00, 0.00) -> 0       a clip authored on the floor needs nothing
 *   (0.146, 0.00) -> 0.146  `laying.fbx` measures 14.6 Mixamo units at the
 *                           hips and lies ON the floor; whatever it measures,
 *                           the rule is the same subtraction
 *   (−0.05, 0.00) -> 0      a crouch dipping BELOW the bind pose is NOT
 *                           lifted — raising a figure is not what this is for
 *   (0.30, 0.10) -> 0.20    the anchor is not always 0: only the DIFFERENCE
 *                           counts, and the bind box is where the figure was
 *                           put on the ground
 *   (0.05, 0.30) -> 0       a bind pose above the clip is the same case as
 *                           the crouch
 *   (NaN, 0) / (0.3, NaN) / (Infinity, 0) -> 0
 *                           a non-measurement is no measurement: 0 is the
 *                           behaviour of before, a NaN would move the figure
 *                           to nowhere for good
 *
 * ---------------------------------------------------------------------------
 * [2] THE WHOLE CHAIN on real rigs — measured at the CONSUMER
 * ---------------------------------------------------------------------------
 * Two real rigs plus the neutral clip library, through the real
 * `adaptExternalClips`, the real `measureGroundOffsets` and a real `Figure`:
 * `Test3_mia.glb` (a character model out of the server's own mesh pipeline,
 * normalised) and `Soldier.glb` (the Mixamo fallback rig of the manifest).
 * What is measured is the lowest MESH point of the posed instance over the
 * figure root — the figure root IS the ground (`npcs` puts it on the ground
 * height), so this number is how high the body floats.
 *
 * Sampling here is INDEPENDENT of the module under test: every 17th vertex
 * over 25 poses (the headless diagnosis run), against the module's own budget
 * of 1024 vertices spread by one stride. Both must find the same floor.
 *
 * Expected, from the diagnosis above and the authoring of the clips:
 *
 *   swim  GATE OFF (the RED COUNTER-PROBE — today's behaviour, and the finding
 *                 itself): +0.26 … +0.32 m over the ground, the band measured
 *                 on three real rigs. The check allows 0.25 … 0.35, which is
 *                 the band plus the centimetre the vertex stride costs.
 *   swim  GATE ON: on the ground, |minY| <= 0.10 m — and within ±0.10 m of the
 *                 idle floor of the same rig. The body reaches the water line
 *                 it was authored on because the figure came down to it.
 *   walk  GATE ON: |minY| <= 0.10 m as well. Its own offset is a couple of
 *                 centimetres, which is what makes the fix generic rather than
 *                 a swim special case — the SAME rule moves both.
 *   THE GATE ONLY EVER LOWERS: `gate off − gate on >= 0` for every clip, and
 *                 the difference IS the measured offset × the figure scale.
 *   THE GROUND'S SINK DEPTH rides the same gate (§ A9, the water round of
 *                 2026-08-13): the normalisation puts the LOWEST body point —
 *                 a bent knee — on the surface, so the swimmer lies ON the
 *                 lake. The ground says how much of the body belongs below it,
 *                 and the arithmetic is
 *
 *                     drop = clip offset × figure scale + depth
 *
 *                 with the depth in WORLD metres, unscaled: half a metre of
 *                 water is half a metre for a child and for a giant.
 *                 THE DEPTH IS ONE OF TWO (finding 13): the ground carries
 *                 `meta.move_sink_m` for the moving pose and
 *                 `meta.idle_sink_m` for the waiting one (water: 0.35 / 1.3),
 *                 because a swimmer lies flat and a treader hangs upright.
 *                 WHICH one arrives here is `walk.sinkForState`'s decision
 *                 (its own hand cases live in `smoke_walk_math.mjs`); this
 *                 file checks that whatever arrives lands on the anchor to the
 *                 micrometre. Hand cases per rig, against the anchor its bind
 *                 pose gave it:
 *                     swim, gate on, depth 0     -> anchor − off·scale
 *                     swim, gate on, depth 0.35  -> anchor − off·scale − 0.35
 *                                                (the MOVING water depth)
 *                     treading-water, gate on, depth 1.3
 *                                                -> anchor − off·scale − 1.3
 *                                                (the WAITING one, on the clip
 *                                                 that actually plays then)
 *                     swim, gate on, depth 1.5   -> anchor − off·scale − 1.5
 *                     swim, gate OFF, depth 0.35 -> anchor  (no gate, no sink:
 *                                                 an activity clip is never
 *                                                 sunk by the ground)
 *                     swim, gate on, depth NaN/−1 -> anchor − off·scale
 *                 and the RESTORATION is exact: back to a standing clip and
 *                 the instance sits at the anchor to the micrometre.
 *                 RED COUNTER-PROBE: the pre-sink rule (offset alone) leaves
 *                 the swimmer 0.35 m higher than the sunk one — measured as
 *                 the difference of the two anchors. A SECOND one for the
 *                 split: giving the treader the MOVING depth leaves it
 *                 1.3 − 0.35 = 0.95 m over where it belongs, which is the
 *                 treader standing on the lake that finding 13 reported.
 *   laying/sleep/sit  NEVER touched: they are standing clips, the gate never
 *                 opens for them, and the instance keeps the exact anchor its
 *                 bind pose gave it (`inst.position.y`, compared to the
 *                 millimetre). `sleep` floats +0.69 … +0.90 m on purpose — it
 *                 was animated on a BED, and that is a parked finding.
 *
 * ---------------------------------------------------------------------------
 * [3] THE LIBRARY GATE for foreign bone conventions (finding 7, same round)
 * ---------------------------------------------------------------------------
 * The swimmer of finding 3 had a second problem on the fallback rig `Xbot`:
 * limbs folded over the torso. `adaptExternalClips` copies LOCAL quaternion
 * tracks 1:1, which is only right while both sides rest their bones in the
 * same frame. The Mixamo library points every bone at its child along the
 * bone's own +Y; Xbot has identity rest rotations, so its frames are
 * world-parallel (legs −Y, arms +X) and the elbow track of the library becomes
 * a fold. Acceptance never caught it because clips were accepted on TRACK
 * COUNT alone — Xbot reports 23 of 23 fitted.
 *
 * `restFrameDeviation` is the missing measurement: the angle between the
 * direction to a bone's first child (in that bone's own rest frame, i.e.
 * `child.position`) and +Y, meaned over the bones the clips address. Hand
 * values from the diagnosis: Xbot 95.6° mean / 179.6° max, Soldier 8.3°/37.4°,
 * eight server-generated models 1.3–1.7°/7.0°. This check re-measures at the
 * consumer and lands at Xbot 92.4°/179.6°, Soldier 9.3°/39.2°, Test3_mia
 * 9.8°/64.8° — a little above the diagnosis on the well-behaved rigs because
 * it means over ALL addressed bones, fingers and thumbs included (those carry
 * the top single readings on Soldier). The verdict is untouched by that: the
 * two groups sit a factor of ten apart, `MAX_REST_FRAME_DEV_DEG = 30` in
 * between.
 *
 * The GEOMETRIC consequence is measured with it, on the adapted `idle` and the
 * plainest number the finding gave: where the left foot sits relative to the
 * hips.
 *
 *   Xbot   gate fires: 92.4° > 30 -> `fits` false, no library clip bound.
 *   Xbot   RED COUNTER-PROBE, threshold 999 (the gate decision is a
 *          comparison, so raising the limit is the whole "gate off" case):
 *          the library adapts as before — and the left foot lands +0.78 m
 *          ABOVE the hips. That IS the finding.
 *   Soldier  9.3° < 30 -> fits, 23 clips, and the foot hangs −0.85 … −0.91 m
 *          BELOW the hips, where a leg belongs.
 *   Test3_mia  the server's own pipeline: 9.8° < 30, foot below the hips. The
 *          gate must not touch the everyday case.
 */
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
// The numbers below were measured on the MIXAMO library, which lives in the
// LICENSED clip directory since 2026-08-21 (the free one holds the CMU
// conversions, authored on the floor — a different yardstick). Per
// installation, not in git: without it this check has nothing to measure.
const CLIP_DIR = join(ROOT, 'shared/models/clips-licensed');
const MODELS = join(ROOT, 'client3d/public/models');
/** The rigs the chain is walked on. `Test3_mia` comes out of the server's own
 *  mesh pipeline (normalised, the everyday case), `Soldier` is the Mixamo
 *  fallback rig of the manifest. */
const RIGS = [join(MODELS, 'Test3_mia.glb'), join(MODELS, 'Soldier.glb')];

// three is a browser library; these three globals are all it misses in node.
// They have to stand BEFORE three is loaded, which is why every import below
// is dynamic.
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
    `${actual.toFixed(4)} (expected ${expected} ±${eps})`);
const between = (label, actual, lo, hi) =>
  check(label, Number.isFinite(actual) && actual >= lo && actual <= hi,
    `${actual.toFixed(4)} (expected ${lo} … ${hi})`);

/**
 * Bundle the client modules under test into ONE file next to this script and
 * import it. Inside the repo on purpose: node resolves `three` upwards from
 * the file, so the bundle and this script share ONE three — `external` keeps
 * it out of the bundle for exactly that reason. `figures.ts` reaches the DOM
 * only inside functions, so it loads here.
 */
async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src/scene');
    const entry = [
      `export { adaptExternalClips, Figure } from '${src}/figures';`,
      `export { MAX_REST_FRAME_DEV_DEG, restFrameDeviation } from '${src}/figures';`,
      `export { clipGroundOffset, groundOffsetOf, measureGroundOffsets }`,
      `  from '${src}/clipGround';`,
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

function arrayBufferOf(buf) {
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

async function main() {
  const THREE = await import('three');
  const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
  const { FBXLoader } = await import('three/addons/loaders/FBXLoader.js');
  const { adaptExternalClips, Figure, clipGroundOffset, groundOffsetOf,
          measureGroundOffsets, restFrameDeviation,
          MAX_REST_FRAME_DEV_DEG } = await loadClient();

  console.log('[1] groundOffsetOf — the drop a clip needs (hand-derived)');
  near('the swim case: body 0.30 over an anchor at 0',
    groundOffsetOf(0.30, 0), 0.30, 1e-9);
  near('a clip on the floor needs no drop', groundOffsetOf(0, 0), 0, 1e-9);
  near('laying, 0.146 over the anchor', groundOffsetOf(0.146, 0), 0.146, 1e-9);
  near('a crouch BELOW the bind pose is not lifted',
    groundOffsetOf(-0.05, 0), 0, 1e-9);
  near('only the difference counts', groundOffsetOf(0.30, 0.10), 0.20, 1e-9);
  near('bind pose above the clip -> no drop', groundOffsetOf(0.05, 0.30), 0, 1e-9);
  near('NaN clip reading is no measurement', groundOffsetOf(NaN, 0), 0, 1e-9);
  near('NaN anchor is no measurement', groundOffsetOf(0.3, NaN), 0, 1e-9);
  near('an empty sample stays Infinity and answers 0',
    groundOffsetOf(Infinity, 0), 0, 1e-9);

  console.log('\n[2] the whole chain on real rigs + the neutral clip library');
  const fbx = new FBXLoader();
  const wanted = ['idle', 'walk', 'swim', 'laying', 'sleep', 'sit'];
  let files = [];
  try {
    files = (await readdir(CLIP_DIR)).filter((n) => n.endsWith('.fbx')).sort();
  } catch { files = []; }
  if (!files.length) {
    console.log(`  skip — no licensed clip library at ${CLIP_DIR} (Mixamo clips are per installation)`);
    console.log(`\n${passed} ok, ${failed} failed`);
    process.exit(failed ? 1 : 0);
  }
  const library = [];
  for (const name of files) {
    // The standing reference of `adaptExternalClips` is derived ACROSS the
    // clips it is handed, so the whole library goes in — handing it the six
    // clips of interest alone would rescale them against another yardstick.
    const obj = fbx.parse(arrayBufferOf(await readFile(join(CLIP_DIR, name))), '');
    const clip = obj.animations?.[0];
    if (!clip) continue;
    const c = clip.clone();
    // The KIND is the file name minus the extension — the server's
    // `animation_clips.parse_clip_name` (a trailing `_<number>` would be cut
    // too; the library carries none). `swim-idle` and `treading-water` are
    // therefore kinds of their own, not two more `swim`/`treading`.
    c.name = name.replace(/\.fbx$/, '').replace(/_\d+$/, '');
    library.push(c);
  }
  check('the clip library is readable', library.length > 10,
    `${library.length} clips`);

  const v = new THREE.Vector3();
  for (const rig of RIGS) {
    const label = rig.split('/').pop();
    console.log(`  --- ${label}`);
    const rigBytes = arrayBufferOf(await readFile(rig));
    const gltf = await new Promise((res, rej) =>
      new GLTFLoader().parse(rigBytes, '', res, rej));
    const template = gltf.scene;
    template.updateMatrixWorld(true);

    const adapted = adaptExternalClips(library.map((c) => c.clone()), template);
    check(`${label}: the library adapts onto the rig`,
      wanted.every((k) => adapted.some((c) => c.name === k)),
      `${adapted.length}/${library.length} adapted`);
    measureGroundOffsets(adapted, template);
    const offsetOf = (kind) =>
      clipGroundOffset(adapted.find((c) => c.name === kind));

    const bbox = new THREE.Box3().setFromObject(template);
    const rawHeight = bbox.max.y - bbox.min.y;
    const scale = 1.70 / rawHeight;
    const figure = new Figure({
      name: label, template, clips: adapted, scale,
      height: 1.70, assignOnly: true, noClips: false, tier: 'full',
      libraryFits: true,
    });
    const inst = figure.root.children[0];
    // The anchor the bind pose gave the instance. The constructor plays `idle`
    // as a STANDING clip, so no drop is applied yet — this is the untouched
    // number every standing clip has to keep.
    const anchorY = inst.position.y;
    const skins = [];
    inst.traverse((o) => { if (o.isSkinnedMesh) skins.push(o); });
    check(`${label}: the figure carries a skinned body`, skins.length > 0,
      `${skins.length} skinned mesh(es)`);

    /** Lowest mesh point of the FIGURE over its root, in world metres — the
     *  number the finding is about. Own sampling (every 17th vertex, 25 poses),
     *  independent of the module's budget. */
    function figureMinY(kind, terrainClip) {
      figure.play(kind, terrainClip);
      for (let i = 0; i < 20; i++) figure.update(0.05);   // let the crossfade end
      let min = Infinity;
      for (let f = 0; f < 25; f++) {
        figure.update(1 / 24);
        figure.root.updateMatrixWorld(true);
        for (const skin of skins) {
          const count = skin.geometry.attributes.position.count;
          for (let i = 0; i < count; i += 17) {
            skin.getVertexPosition(i, v);
            skin.localToWorld(v);
            if (v.y < min) min = v.y;
          }
        }
      }
      return min;
    }

    console.log(`      rawHeight ${rawHeight.toFixed(3)} -> scale ${scale.toFixed(4)};`
      + ` measured offsets (template metres):`
      + ` ${wanted.map((k) => `${k} ${offsetOf(k).toFixed(3)}`).join(', ')}`);

    const idleY = figureMinY('idle', false);
    const swimOff = figureMinY('swim', false);
    between(`${label}: RED COUNTER-PROBE — gate off, the swimmer floats`,
      swimOff, 0.25, 0.35);
    const swimOn = figureMinY('swim', true);
    near(`${label}: gate on — the swimmer is on the ground`, swimOn, 0, 0.10);
    near(`${label}: gate on — and level with the idle floor`, swimOn, idleY, 0.10);
    check(`${label}: the drop IS the measured offset × scale`,
      Math.abs((swimOff - swimOn) - offsetOf('swim') * scale) <= 0.02,
      `${(swimOff - swimOn).toFixed(4)} vs ${(offsetOf('swim') * scale).toFixed(4)}`);

    const walkOff = figureMinY('walk', false);
    const walkOn = figureMinY('walk', true);
    near(`${label}: gate on — the walker is on the ground`, walkOn, 0, 0.10);
    check(`${label}: the gate only ever lowers (walk)`, walkOff - walkOn >= -1e-6,
      `off ${walkOff.toFixed(4)} vs on ${walkOn.toFixed(4)}`);

    // The lying/sitting clips are NEVER a terrain move: the gate stays shut and
    // the instance keeps its bind anchor — `sleep` floats on the bed it was
    // animated on, which is the parked finding, not this one.
    for (const kind of ['laying', 'sleep', 'sit']) {
      figureMinY(kind, false);
      near(`${label}: ${kind} keeps the bind anchor`, inst.position.y, anchorY, 1e-6);
    }
    const sleepY = figureMinY('sleep', false);
    check(`${label}: sleep still floats on its bed (parked finding)`,
      sleepY > 0.4, `${sleepY.toFixed(3)} m`);
    figureMinY('swim', true);
    near(`${label}: a terrain move DOES move the anchor`, inst.position.y,
      anchorY - offsetOf('swim') * scale, 1e-6);

    // --- the GROUND's sink depth on top of the clip offset ----------------
    // `figureMinY` cannot be used here: the sink is about WHERE THE ANCHOR
    // sits, and the anchor is the exact number `setClipDrop` writes. Read it
    // directly, which is also what makes the arithmetic checkable to the
    // micrometre.
    const swimDrop = offsetOf('swim') * scale;
    const anchorFor = (kind, terrain, sink) => {
      figure.play('idle', false);           // leave the state, then enter it
      figure.play(kind, terrain, sink);
      return inst.position.y;
    };
    // The two depths of the water seed: the swimmer's while it moves, the
    // treader's while it waits (`meta.move_sink_m` / `meta.idle_sink_m`).
    const MOVE_SINK = 0.35;
    const IDLE_SINK = 1.3;
    const treadDrop = offsetOf('treading-water') * scale;
    near(`${label}: depth 0 is the clip offset alone`,
      anchorFor('swim', true, 0), anchorY - swimDrop, 1e-6);
    near(`${label}: the MOVING depth goes on top of it, unscaled`,
      anchorFor('swim', true, MOVE_SINK), anchorY - swimDrop - MOVE_SINK, 1e-6);
    near(`${label}: the WAITING depth does the same on the waiting clip`,
      anchorFor('treading-water', true, IDLE_SINK),
      anchorY - treadDrop - IDLE_SINK, 1e-6);
    near(`${label}: ...and 1.5, the clamp of the catalog`,
      anchorFor('swim', true, 1.5), anchorY - swimDrop - 1.5, 1e-6);
    near(`${label}: an ACTIVITY clip is never sunk by the ground`,
      anchorFor('swim', false, MOVE_SINK), anchorY, 1e-6);
    near(`${label}: a NaN depth is no depth`,
      anchorFor('swim', true, NaN), anchorY - swimDrop, 1e-6);
    near(`${label}: ...and neither is a negative one`,
      anchorFor('swim', true, -1), anchorY - swimDrop, 1e-6);
    // RED COUNTER-PROBE: the rule before the sink existed was the offset
    // alone. It must land 0.35 m HIGHER than the sunk swimmer — otherwise the
    // sink is not reaching the anchor at all.
    check(`${label}: RED COUNTER-PROBE — offset alone floats ${MOVE_SINK} m over the sunk one`,
      Math.abs((anchorFor('swim', true, 0) - anchorFor('swim', true, MOVE_SINK))
        - MOVE_SINK) <= 1e-6,
      `${(anchorFor('swim', true, 0) - anchorFor('swim', true, MOVE_SINK)).toFixed(6)} m`);
    // RED COUNTER-PROBE for the SPLIT (finding 13): the treader handed the
    // MOVING depth hangs 0.95 m over where the waiting depth puts it — the
    // treader standing on the lake.
    check(`${label}: RED COUNTER-PROBE — the treader on the moving depth floats 0.95 m`,
      Math.abs((anchorFor('treading-water', true, MOVE_SINK)
        - anchorFor('treading-water', true, IDLE_SINK))
        - (IDLE_SINK - MOVE_SINK)) <= 1e-6,
      `${(anchorFor('treading-water', true, MOVE_SINK)
        - anchorFor('treading-water', true, IDLE_SINK)).toFixed(6)} m`);
    // Leaving the water restores the bind anchor EXACTLY, sink or no sink.
    figure.play('swim', true, MOVE_SINK);
    figure.play('sit', false);
    near(`${label}: back on dry land, the anchor is exactly the bind one`,
      inst.position.y, anchorY, 1e-6);

    // The hyphenated kinds are PLAYABLE kinds since the parser fix of
    // 2026-08-13 — `swim-idle` used to be filed as a second `swim` and
    // `treading-water` as `treading`, so the kind an author writes into
    // `idle_anim` was bound to nothing. Proven at the consumer: the figure
    // reports the kind as bound, and the anchor moves by THAT clip's own
    // offset, which is how one sees it is not the `swim` clip again.
    for (const kind of ['swim-idle', 'treading-water']) {
      figureMinY(kind, true);
      check(`${label}: ${kind} is a kind of its own and is bound`,
        figure.root.userData.clipKind === kind && figure.root.userData.clipBound === true,
        `${figure.root.userData.clipKind}, bound ${figure.root.userData.clipBound}`);
      near(`${label}: ...and the anchor follows ITS offset`, inst.position.y,
        anchorY - offsetOf(kind) * scale, 1e-6);
    }
  }

  console.log('\n[3] the library gate against foreign bone conventions');
  check(`the threshold is ${MAX_REST_FRAME_DEV_DEG}° mean deviation`,
    MAX_REST_FRAME_DEV_DEG === 30, `${MAX_REST_FRAME_DEV_DEG}`);

  /** Left foot minus hips in the rig's own units, on the adapted `idle` — a
   *  leg hangs BELOW the hips, and the fold of the finding puts it above. */
  function footOverHips(template, clips) {
    const idle = clips.find((c) => c.name === 'idle');
    if (!idle) return NaN;
    const mixer = new THREE.AnimationMixer(template);
    const action = mixer.clipAction(idle);
    action.play();
    mixer.setTime(0.5);
    template.updateMatrixWorld(true);
    let foot = null;
    let hips = null;
    template.traverse((o) => {
      if (!o.isBone) return;
      const n = o.name.replace(/^mixamorig:?/i, '').replace(/:/g, '').toLowerCase();
      if (n === 'leftfoot') foot = o;
      if (n === 'hips') hips = o;
    });
    const dy = foot && hips
      ? foot.getWorldPosition(new THREE.Vector3()).y - hips.getWorldPosition(new THREE.Vector3()).y
      : NaN;
    action.stop();
    mixer.uncacheClip(idle);
    return dy;
  }

  /** The gate as `fitLibrary` decides it: the measured mean against a limit.
   *  Passing the limit in is what makes the counter-probe possible. */
  const libraryFits = (dev, limit) => dev.mean <= limit;

  for (const [file, expect] of [
    ['Xbot.glb', 'foreign'], ['Soldier.glb', 'mixamo'], ['Test3_mia.glb', 'mixamo'],
  ]) {
    const bytes = arrayBufferOf(await readFile(join(MODELS, file)));
    const gltf = await new Promise((res, rej) =>
      new GLTFLoader().parse(bytes, '', res, rej));
    const template = gltf.scene;
    template.updateMatrixWorld(true);
    const dev = restFrameDeviation(library, template);
    const adapted = adaptExternalClips(library.map((c) => c.clone()), template);
    const dy = footOverHips(template, adapted);
    console.log(`  --- ${file}: ${dev.mean.toFixed(1)}° mean / ${dev.max.toFixed(1)}° max`
      + ` over ${dev.bones} bones, ${adapted.length} clips adapted,`
      + ` left foot ${dy >= 0 ? '+' : ''}${dy.toFixed(3)} vs hips`);

    if (expect === 'foreign') {
      between(`${file}: rest pose far off the library convention`, dev.mean, 85, 105);
      between(`${file}: and a limb turned right around`, dev.max, 175, 180);
      check(`${file}: the gate fires — the library does not fit`,
        !libraryFits(dev, MAX_REST_FRAME_DEV_DEG), `${dev.mean.toFixed(1)}° > ${MAX_REST_FRAME_DEV_DEG}°`);
      check(`${file}: RED COUNTER-PROBE — threshold 999, the library "fits" again`,
        libraryFits(dev, 999) && adapted.length >= 20, `${adapted.length} clips adapted`);
      between(`${file}: RED COUNTER-PROBE — and the foot folds ABOVE the hips`,
        dy, 0.70, 0.86);
    } else {
      between(`${file}: rest pose follows the library convention`, dev.mean, 0, 20);
      check(`${file}: the gate stays open — the library fits`,
        libraryFits(dev, MAX_REST_FRAME_DEV_DEG) && adapted.length >= 20,
        `${dev.mean.toFixed(1)}° <= ${MAX_REST_FRAME_DEV_DEG}°, ${adapted.length} clips`);
      between(`${file}: and the foot hangs below the hips, where a leg belongs`,
        dy, -1.00, -0.70);
    }
  }

  console.log(`\n${passed + failed} checks, ${failed} failures`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
