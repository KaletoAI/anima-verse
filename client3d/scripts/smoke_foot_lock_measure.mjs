#!/usr/bin/env node
/**
 * Smoke check for the PER-RIG FOOT LOCK of the 3D client
 * (`client3d/src/scene/footLockMeasure.ts`, `relockRootPaths`): a bridge
 * clip's imported root travel is rebuilt on each model's OWN skeleton, from
 * the foot bones of a probe clone — the same rule the importer ran on the
 * reference rig (`footLock.ts`, twin of `_root_motion.py`). Numbers only
 * (§ B5a); a SYNTHETIC skeleton, no clip files, no server.
 *
 * Usage:  node client3d/scripts/smoke_foot_lock_measure.mjs
 *         (needs esbuild and three from the workspace)
 *
 * ===========================================================================
 * THE SYNTHETIC RIG (k = template units per cm: 1 for [C1]–[C4]/[C6], 0.01
 * for [C5]; every length below is × k)
 * ===========================================================================
 *   rig (Group, identity)
 *   └ mixamorigHips        local (0, 100, 0)
 *     └ Legs               local (0, 0, 0)       ← the ONE animated bone
 *       ├ mixamorigLeftUpLeg   local ( 10, 0, 0)
 *       │ └ mixamorigLeftLeg   local (0, −46, 0)
 *       │   └ mixamorigLeftFoot    local (0, −46, 0)  → world ( 10, 8, 0)
 *       │     └ mixamorigLeftToeBase local (0, −5, 12) → world ( 10, 3, 12)
 *       │       └ mixamorigLeftToe_End local (0, −3, 6) → world ( 10, 0, 18)
 *       └ the same on the right with x = −10
 * Rest heights (bind pose, over the lowest of the four points AND the two
 * toe ends, which sit at 0): LeftFoot/RightFoot 8, LeftToeBase/RightToeBase 3.
 *
 * THE CLIP (the "Legs" variant the brief allows): 11 keys, f = 0 … 10 at
 * 30 fps (times f/30, duration 1/3 s). `mixamorigHips.position` stays at its
 * rest (0, 100, 0) — the hips are in place, as `adaptExternalClips` leaves
 * them — and `Legs.position` = (0, 0, −2f): both feet slide 2 cm a frame
 * BACKWARDS, which is exactly what a planted foot does in an in-place clip
 * while the body walks forward.
 *
 * Measured per frame (cm): LeftFoot (10, 8, −2f), LeftToeBase (10, 3, 12 − 2f),
 * the right side at x = −10. Heights are constant, so every point's ground is
 * min(5th percentile = its own height, rest height) = its own height →
 * height over ground 0 → band weight 1; vertical speed 0 → speed weight 1.
 * All four points weigh 1 in every frame: FULL contact throughout.
 * footLockPath: each step the four full points move dz = −2, dx = 0, so the
 * root moves by the opposite: path = (0, 2f) cm.
 *
 * [C1] The imported path is preset WRONG on purpose: z = 1·f (template
 *      units, = cm at k = 1). After relockRootPaths:
 *        stored path z = 2f (±1e-4), x = 0, times = the hips track's f/30;
 *        report used 'rig', driftCm 0 (±1e-3) — the world foot z is
 *        −2f + 2f = 0 over the whole run;
 *        importedDriftCm 10 (±1e-3) — with the preset path the world foot z
 *        is −2f + f = −f, a run from f = 0 to 10 drifts |−10 − 0| = 10;
 *        travel = the path's end (0, 20) cm.
 *      The same clip WITHOUT a hips position track is sampled uniformly at
 *      30 fps over its duration: round(1/3 · 30) + 1 = 11 frames at f/30 —
 *      the same path (0, 2f).
 *      The log sink is called exactly once, with
 *        "foot lock per rig — bridge-a 0.0 cm (imported 10.0)".
 * [C2] The template is untouched: every bone's local position and quaternion
 *      equal (exactly) their values before any of the calls below.
 * [C3] Legs.position = (0, 30, −2f): the feet hang 30 cm over their rest
 *      heights. ground = min(own height 38 resp. 33, rest 8 resp. 3) = rest,
 *      height over ground 30 ≥ 5 → weight 0 everywhere: no frame pair reaches
 *      FULL → used 'imported', reason 'no full contact', the stored path is
 *      still the preset z = 1·f; driftCm = importedDriftCm = 0 (no planted
 *      run exists); travel (0, 10) cm.
 * [C4] The rig without mixamorigLeftToeBase (and its toe end): one contact
 *      point is missing → used 'imported', reason 'no foot bones', the preset
 *      path stays, driftCm/importedDriftCm/travel finite (0, 0, (0, 10)).
 * [C5] The whole rig and clip scaled into METRES (k = 0.01), unitsPerCm
 *      0.01: the measured tracks in cm are those of [C1] (units / 0.01), so
 *      the path is (0, 2f) cm again and is stored back in template units:
 *      z = 0.02f (±1e-6 units = ±1e-4 cm); driftCm 0, importedDriftCm 10 for
 *      the preset z = 0.01f (= f cm).
 * [C6] A clip with no root path in the same call is not touched: one report
 *      only (for the [C1] clip), and it still has no path afterwards. A call
 *      with ONLY that clip returns [] and never calls the log sink.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const FPS = 30;
const FRAMES = 11;

let failed = 0;
let passed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`); }
  else { failed += 1; console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`); }
}
const near = (label, actual, expected, eps) =>
  check(label, Number.isFinite(actual) && Math.abs(actual - expected) <= eps,
    `got ${actual}, expected ${expected} ±${eps}`);

async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src/scene');
    const entry = [
      `export { relockRootPaths } from '${src}/footLockMeasure';`,
      `export { clipRootPath, setClipRootPath } from '${src}/bridgeTravel';`,
    ].join('\n');
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'measure.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'measure.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

async function main() {
  const THREE = await import('three');
  const { relockRootPaths, clipRootPath, setClipRootPath } = await loadClient();

  /** The synthetic rig of the docstring, every length × k. */
  const makeRig = (k, { leftToe = true } = {}) => {
    const bone = (name, x, y, z, parent) => {
      const b = new THREE.Bone();
      b.name = name;
      b.position.set(x * k, y * k, z * k);
      parent.add(b);
      return b;
    };
    const rig = new THREE.Group();
    rig.name = 'rig';
    const hips = bone('mixamorigHips', 0, 100, 0, rig);
    const legs = bone('Legs', 0, 0, 0, hips);
    for (const [side, x] of [['Left', 10], ['Right', -10]]) {
      const up = bone(`mixamorig${side}UpLeg`, x, 0, 0, legs);
      const low = bone(`mixamorig${side}Leg`, 0, -46, 0, up);
      const foot = bone(`mixamorig${side}Foot`, 0, -46, 0, low);
      if (side === 'Left' && !leftToe) continue;
      const toe = bone(`mixamorig${side}ToeBase`, 0, -5, 12, foot);
      bone(`mixamorig${side}Toe_End`, 0, -3, 6, toe);
    }
    rig.updateMatrixWorld(true);
    return rig;
  };
  const times = Array.from({ length: FRAMES }, (_, f) => f / FPS);
  /** The docstring's clip: Legs slides the feet by (0, lift, −2f), × k. */
  const makeClip = (name, k, { lift = 0, hipsTrack = true } = {}) => {
    const tracks = [
      new THREE.VectorKeyframeTrack('Legs.position', times,
        times.flatMap((_, f) => [0, lift * k, -2 * f * k])),
    ];
    if (hipsTrack) {
      tracks.push(new THREE.VectorKeyframeTrack('mixamorigHips.position', times,
        times.flatMap(() => [0, 100 * k, 0])));
    }
    return new THREE.AnimationClip(name, (FRAMES - 1) / FPS, tracks);
  };
  /** The wrong imported path: z = slope·f template units. */
  const preset = (clip, slope) => {
    setClipRootPath(clip, {
      times: Float32Array.from(times),
      xz: Float32Array.from(times.flatMap((_, f) => [0, slope * f])),
    });
  };
  const pathZ = (clip) => {
    const p = clipRootPath(clip);
    return p ? Array.from({ length: p.times.length }, (_, i) => p.xz[i * 2 + 1]) : null;
  };
  const pathX = (clip) => {
    const p = clipRootPath(clip);
    return p ? Array.from({ length: p.times.length }, (_, i) => p.xz[i * 2]) : null;
  };
  const allNear = (label, got, want, eps) =>
    check(label, !!got && got.length === want.length
      && got.every((g, i) => Number.isFinite(g) && Math.abs(g - want[i]) <= eps),
    `got ${JSON.stringify(got?.map((g) => +g.toFixed(6)))}, expected ${JSON.stringify(want)}`);
  const snapshot = (rig) => {
    const out = [];
    rig.traverse((o) => { if (o.isBone) out.push([o.name, ...o.position.toArray(), ...o.quaternion.toArray()]); });
    return JSON.stringify(out);
  };
  const expect2f = times.map((_, f) => 2 * f);

  const rig = makeRig(1);
  const before = snapshot(rig);

  console.log('[C1] a planted slide of 2 cm/frame → path z = 2f, replacing a wrong preset');
  {
    const clip = makeClip('bridge-a', 1);
    preset(clip, 1);
    const lines = [];
    const reports = relockRootPaths([clip], rig, 1, (m) => lines.push(m));
    const r = reports[0];
    check('one report', reports.length === 1, `${reports.length}`);
    check("used 'rig'", r?.used === 'rig', `${r?.used} ${r?.reason ?? ''}`);
    allNear('stored path z = 2f', pathZ(clip), expect2f, 1e-4);
    allNear('stored path x = 0', pathX(clip), times.map(() => 0), 1e-4);
    allNear('stored times = the hips track keys f/30', Array.from(clipRootPath(clip)?.times ?? []),
      times, 1e-6);
    near('driftCm 0', r?.driftCm, 0, 1e-3);
    near('importedDriftCm 10 (the preset path, same run)', r?.importedDriftCm, 10, 1e-3);
    near('travel x 0 cm', r?.travel?.[0], 0, 1e-4);
    near('travel z 20 cm', r?.travel?.[1], 20, 1e-4);
    check('the log sink was called once', lines.length === 1, JSON.stringify(lines));
    check('log line', lines[0] === 'foot lock per rig — bridge-a 0.0 cm (imported 10.0)',
      JSON.stringify(lines[0]));

    const bare = makeClip('bridge-a2', 1, { hipsTrack: false });
    preset(bare, 1);
    const r2 = relockRootPaths([bare], rig, 1)[0];
    check("no hips track: used 'rig'", r2?.used === 'rig', `${r2?.used} ${r2?.reason ?? ''}`);
    allNear('no hips track: 30 fps sampling, path z = 2f', pathZ(bare), expect2f, 1e-4);
    allNear('no hips track: times f/30', Array.from(clipRootPath(bare)?.times ?? []), times, 1e-6);
  }

  console.log('[C3] feet 30 cm over the ground → no full contact, the imported path stays');
  {
    const clip = makeClip('bridge-c', 1, { lift: 30 });
    preset(clip, 1);
    const lines = [];
    const r = relockRootPaths([clip], rig, 1, (m) => lines.push(m))[0];
    check("used 'imported'", r?.used === 'imported', `${r?.used}`);
    check("reason 'no full contact'", r?.reason === 'no full contact', `${r?.reason}`);
    allNear('path still the preset z = f', pathZ(clip), times.map((_, f) => f), 1e-6);
    near('driftCm 0', r?.driftCm, 0, 1e-9);
    near('importedDriftCm 0', r?.importedDriftCm, 0, 1e-9);
    near('travel z 10 cm (the preset end)', r?.travel?.[1], 10, 1e-4);
    check('log line names the fallback',
      lines.length === 1 && lines[0] === 'foot lock per rig — bridge-c imported (no full contact)',
      JSON.stringify(lines));
  }

  console.log('[C4] a rig without LeftToeBase → no foot bones, the imported path stays');
  {
    const noToe = makeRig(1, { leftToe: false });
    const clip = makeClip('bridge-d', 1);
    preset(clip, 1);
    const r = relockRootPaths([clip], noToe, 1)[0];
    check("used 'imported'", r?.used === 'imported', `${r?.used}`);
    check("reason 'no foot bones'", r?.reason === 'no foot bones', `${r?.reason}`);
    allNear('path still the preset z = f', pathZ(clip), times.map((_, f) => f), 1e-6);
    check('no NaN in the report',
      [r?.driftCm, r?.importedDriftCm, ...(r?.travel ?? [NaN, NaN])].every(Number.isFinite),
      JSON.stringify(r));
  }

  console.log('[C5] the rig in metres, unitsPerCm 0.01 → path z = 0.02f template units');
  {
    const mRig = makeRig(0.01);
    const clip = makeClip('bridge-e', 0.01);
    preset(clip, 0.01);
    const r = relockRootPaths([clip], mRig, 0.01)[0];
    check("used 'rig'", r?.used === 'rig', `${r?.used} ${r?.reason ?? ''}`);
    allNear('stored path z = 0.02f', pathZ(clip), times.map((_, f) => 0.02 * f), 1e-6);
    near('driftCm 0', r?.driftCm, 0, 1e-3);
    near('importedDriftCm 10', r?.importedDriftCm, 10, 1e-3);
    near('travel z 20 cm', r?.travel?.[1], 20, 1e-3);
  }

  console.log('[C6] a clip without a root path is not touched');
  {
    const withPath = makeClip('bridge-f', 1);
    preset(withPath, 1);
    const plain = makeClip('idle-like', 1);
    const reports = relockRootPaths([plain, withPath], rig, 1);
    check('one report, for the clip with a path',
      reports.length === 1 && reports[0].clip === 'bridge-f', JSON.stringify(reports.map((x) => x.clip)));
    check('the plain clip still has no path', clipRootPath(plain) === undefined, `${clipRootPath(plain)}`);
    const lines = [];
    const none = relockRootPaths([makeClip('idle-only', 1)], rig, 1, (m) => lines.push(m));
    check('only plain clips → [] and no log line', none.length === 0 && lines.length === 0,
      `${none.length} reports, ${lines.length} lines`);
  }

  console.log('[C2] the template is untouched');
  check('bone positions and quaternions equal the state before', snapshot(rig) === before);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((err) => {
  console.error(`FAIL ${err?.message ?? err}`);
  process.exit(1);
});
