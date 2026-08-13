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
 *   laying/sleep/sit  NEVER touched: they are standing clips, the gate never
 *                 opens for them, and the instance keeps the exact anchor its
 *                 bind pose gave it (`inst.position.y`, compared to the
 *                 millimetre). `sleep` floats +0.69 … +0.90 m on purpose — it
 *                 was animated on a BED, and that is a parked finding.
 */
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const CLIP_DIR = join(ROOT, 'shared/models/clips');
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
          measureGroundOffsets } = await loadClient();

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
  const files = (await readdir(CLIP_DIR)).filter((n) => n.endsWith('.fbx')).sort();
  const library = [];
  for (const name of files) {
    // The standing reference of `adaptExternalClips` is derived ACROSS the
    // clips it is handed, so the whole library goes in — handing it the six
    // clips of interest alone would rescale them against another yardstick.
    const obj = fbx.parse(arrayBufferOf(await readFile(join(CLIP_DIR, name))), '');
    const clip = obj.animations?.[0];
    if (!clip) continue;
    const c = clip.clone();
    c.name = name.replace(/\.fbx$/, '');
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
    function figureMinY(kind, terrainMove) {
      figure.play(kind, terrainMove);
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
  }

  console.log(`\n${passed + failed} checks, ${failed} failures`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
