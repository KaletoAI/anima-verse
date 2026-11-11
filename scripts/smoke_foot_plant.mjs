#!/usr/bin/env node
/**
 * Smoke check for the SHOD FOOT PLANT — `packages/scene-render/src/footPlant.ts`
 * (`plantFootPose`, `levelTurn`, `fadeRuns`, `plantSampleTimes`) and the moved
 * `twoBoneIk.ts` / `footLock.ts` it builds on.
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_foot_plant.mjs
 *
 * Every expected number is derived BY HAND (§ B5a). A rotation by θ about
 * +x (right hand) takes (y, z) to (y·cosθ − z·sinθ, y·sinθ + z·cosθ).
 *
 * THE RIG (metres, bind identity rotations): root group → `mixamorigHips`
 * at (0, 0.98, 0) → `mixamorigLeftUpLeg` at local (0, 0, 0) → `mixamorigLeftLeg`
 * at local (0, −0.45, 0.15) → `mixamorigLeftFoot` at local (0, −0.45, −0.15),
 * so the ankle stands at (0, 0.08, 0) — the two-bone chain of
 * `smoke_clip_ground_sole.mjs` with a leg above it: l1 = l2 =
 * √(0.45² + 0.15²) = 0.4743416, straight reach 0.9486833, hip→ankle 0.90 —
 * → `mixamorigLeftToeBase` at local (0, 0, 0), ON the ankle, so the bare
 * ball joint never moves under a Foot turn and the stance decision below is
 * the hips' alone. A body SkinnedMesh, every vertex 100 % Foot: A (0.05, 0,
 * 0.05), B (−0.05, 0, −0.05) — the bind soles on y = 0 — and (0, 0.30, 0).
 * A shoe garment node `garment_footwear_i_left` (userData.garment {kind
 * footwear, item_id i, fsig abc}) with its own SkinnedMesh, 100 % Foot:
 * (0, −0.02, −0.05), (0, −0.02, 0.10), (0, 0.05, 0.10).
 * fp = {version 1, source {item_id i, fsig abc}, bones {LeftFoot: axis
 *       (1, 0, 0), deg 0 — the fit's axis, no extension}, root_lift_m 0.052,
 *       contacts {left: [heel (0, −0.02, −0.05) on Foot, ball (0, −0.02,
 *       0.10) on ToeBase, toe (0, −0.015, 0.14) on ToeBase], right: []}}.
 * Relative to the ankle (= the ToeBase joint): heel (0, −0.10, −0.05), ball
 * (0, −0.10, 0.10), toe (0, −0.095, 0.14). The insole slope α of the stand
 * pose is the ball→toe pitch: atan2(0.005, 0.04) = 7.125016°.
 *
 * THE CLIP: 31 keys at f/30 s (duration 1 s). `mixamorigHips.position` is
 * (0, 0.98, 0) for f ≤ 15 and (0, 1.08, 0) for f ≥ 16 — the leg lifted
 * 10 cm: the swing. `mixamorigLeftFoot.quaternion` is R(+x, θ_f) with
 * θ_f = −10° + 25°·f/15 for f ≤ 15 (heel strike … heel off) and
 * θ_f = 15° − 15°·(f − 15)/15 for f ≥ 15. θ > 0 is heel-up: heel y =
 * 0.08 − 0.10·cosθ + 0.05·sinθ, ball y = 0.08 − 0.10·cosθ − 0.10·sinθ.
 *
 * STANCE (footLock.contactWeights on the BARE ankle and ball joints, cm):
 * both sit at 8 cm for f ≤ 15 and 18 cm for f ≥ 16; rest 8, ground = min(5th
 * percentile = 8, rest) = 8 → height band 1 for f ≤ 15, 0 above (10 cm > 5).
 * Speed (central difference): f = 15 reads (18 − 8)/(2/30) = 150 cm/s → 0;
 * f = 14 reads 0 → 1. So w = 1 for f = 0 … 14, 0 from f = 15; the run
 * [0, 14] decays after its end over F = round(0.15 · 30) = 5 frames:
 * w'(15 … 19) = 5/6, 4/6, 3/6, 2/6, 1/6, and w' = 0 from f = 20 (`fadeRuns`).
 * The level weight is min(ankle, ball, w') = 1 for f ≤ 14, 0 after.
 *
 * [1] levelTurn: axis +x, d = (0, 0.15·sinθ, 0.15·cosθ) (pitched θ up along
 *     +z) → +θ (θ = 20°, −10°): (R·d).y = 0.15·sin(θ − δ); the plant's own d
 *     = heel − ball points BACK, (0, 0.15·sinθ, −0.15·cosθ) → −θ; a level d →
 *     0; a vertical axis cannot level anything → 0.
 * [2] fadeRuns at 30 fps (F = 5): [1,1,1,0×7] → [1,1,1, 5/6, 4/6, 3/6, 2/6,
 *     1/6, 0, 0]; a run ending on the last frame [0,0,1,1] is unchanged;
 *     [0.6, 0×6] → 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0; the decay never lowers a
 *     frame's own weight: [1,0,1,0,0,0,0,0] → [1, 5/6, 1, 5/6, 4/6, 3/6, 2/6, 1/6].
 * [3] plantSampleTimes: the hips position keys (31) when present, else
 *     round(1 s · 30) + 1 = 31 uniform times.
 * [4] no-ops: a record of another fsig, an already planted clip and a rig
 *     without the leg bones (the sole smoke's Foot-only rig) return the SAME
 *     object; a clip whose hips stay at 1.08 (no stance anywhere) returns a
 *     new clip marked footPlanted with every value identical.
 * [5] IN A PLANTED FRAME (f = 0, 6, 12, 14; θ = −10°, 0°, 10°, 13.33°), rootY
 *     0.052 → floor at 0 − 0.052: the level turn is −θ (weight 1), so heel
 *     and ball stand at 0.08 − 0.10 = −0.02; the lowest is 0.032 over the
 *     floor → the ankle is lowered by 1 · 0.032 to 0.048 → heel = ball =
 *     −0.052, the toe (forepart in line, α) at 0.048 − 0.095 = −0.047. The
 *     knee by the two-bone IK (pole = the knee, bending plane y–z): hip→target
 *     d' = 0.98 − 0.048 = 0.932, l1·cosA = d'/2 = 0.466 → knee (0, 0.514,
 *     √(0.225 − 0.466²) = 0.0885664).
 * [6] AFTER LIFT-OFF, f = 15 (θ = 15°, w' = 5/6, level weight 0): the Foot
 *     keeps θ → heel −0.0036516; the forepart in line would pitch α − 15°
 *     below α, so it is held up to α (identity) and blended by w' → R(+x,
 *     2.5°): ball 0.08 − 0.10·cos2.5° − 0.10·sin2.5° = −0.0242668, toe 0.08 −
 *     0.095·cos2.5° − 0.14·sin2.5° = −0.0210163; the lowest (ball) floats
 *     0.0277332 → lowered by 5/6 of it: v = −0.0231110, ankle 0.0568890, heel
 *     −0.0267627, ball −0.0473778, toe −0.0441273; knee: d' = 0.9231110 →
 *     (0, 0.5184445, √(0.225 − 0.4615555²) = 0.1093915).
 *     f = 16 (θ = 14°, w' = 4/6, hips at 1.08): ball under R(14°/3) =
 *     0.18 − 0.10·cos4.667° − 0.10·sin4.667° = 0.0721956 (the lowest), v =
 *     4/6 · (−0.052 − 0.0721956) = −0.0827971 — MORE than the leg has:
 *     hip→ankle is 0.90 and the straight leg 0.9486833, so the IK clamps and
 *     the ankle goes to the straight leg, 1.08 − 0.9486833 = 0.1313167, the
 *     ball down by that 0.0486833 to 0.0235123, the knee on the line at
 *     (0, 1.08 − 0.4743416 = 0.6056584, 0). (The same clamp is what limits
 *     the real walk's lift-off frame: the trailing leg is straight there.)
 * [7] SWING, f = 20 … 30 (w' = 0): the Foot track equals the input (q · R)
 *     value for value, UpLeg / Leg / ToeBase keys are identity, the heel
 *     stands where the unplanted clip puts it (f = 20: θ = 10°, hips 1.08:
 *     0.18 − 0.10·cos10° + 0.05·sin10° = 0.0902015).
 * [8] A PIERCE IS LIFTED IN FULL: rootY 0 (floor 0). In-run f = 6: level,
 *     heel = ball = −0.02 → raised by the whole 0.02 → heel = ball = 0,
 *     ankle 0.10, knee: d' = 0.88 → (0, 0.54, √(0.225 − 0.44²) = 0.1772005).
 *     Post-run f = 15 (w' = 5/6): the ball at −0.0242668 is under the floor →
 *     raised by ALL of it, not 5/6: ball 0, ankle 0.1042668, heel 0.0206151,
 *     toe 0.0032505.
 * [9] the probe is handed back in its bind pose (every bone's quaternion and
 *     position as before), and the result carries footPlanted 'abc' beside
 *     the footPosed mark; the input clips are untouched.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_foot_plant_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm', `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root,
    })
    process.exit(run.status ?? 1)
  }

  const P = await import('../packages/scene-render/src/footPlant.ts')
  const { applyFootPose, footContactsNow } = await import('../packages/scene-render/src/footPose.ts')
  const { normBoneName } = await import('../packages/scene-render/src/clipRetarget.ts')
  const THREE = await import('three')
  const { plantFootPose, levelTurn, fadeRuns, plantSampleTimes, PLANT_FADE_S } = P

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const EPS = 1e-6
  const near = (a, b, eps = EPS) => Math.abs(a - b) <= eps
  const rad = (deg) => (deg * Math.PI) / 180

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
  }

  const skinned = (positions, boneIndex, nBones) => {
    const n = positions.length / 3
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(Array.from({ length: n * 4 }, (_, i) => (i % 4 === 0 ? boneIndex : 0)), 4))
    geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(Array.from({ length: n * 4 }, (_, i) => (i % 4 === 0 ? 1 : 0)), 4))
    void nBones
    return new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  }
  /** the rig of the docstring; `legs` false = the sole smoke's Foot-only rig */
  const rig = (legs = true) => {
    const root = new THREE.Group()
    const bone = (name, x, y, z) => { const b = new THREE.Bone(); b.name = name; b.position.set(x, y, z); return b }
    const foot = bone('mixamorigLeftFoot', 0, 0.08, 0)
    const toe = bone('mixamorigLeftToeBase', 0, 0, 0)
    foot.add(toe)
    let chain = [foot, toe]
    if (legs) {
      const hips = bone('mixamorigHips', 0, 0.98, 0)
      const up = bone('mixamorigLeftUpLeg', 0, 0, 0)
      const leg = bone('mixamorigLeftLeg', 0, -0.45, 0.15)
      foot.position.set(0, -0.45, -0.15)
      hips.add(up); up.add(leg); leg.add(foot)
      root.add(hips)
      chain = [hips, up, leg, foot, toe]
    } else {
      root.add(foot)
    }
    const footIndex = chain.indexOf(foot)
    const body = skinned([0.05, 0, 0.05, -0.05, 0, -0.05, 0, 0.30, 0], footIndex, chain.length)
    root.add(body)
    const shoe = new THREE.Group(); shoe.name = 'garment_footwear_i_left'
    shoe.userData.garment = { kind: 'footwear', item_id: 'i', fsig: 'abc', side: 'left' }
    const shoeMesh = skinned([0, -0.02, -0.05, 0, -0.02, 0.10, 0, 0.05, 0.10], footIndex, chain.length)
    shoe.add(shoeMesh)
    root.add(shoe)
    root.updateMatrixWorld(true)
    const skeleton = new THREE.Skeleton(chain)
    body.bind(skeleton)
    shoeMesh.bind(skeleton)
    return root
  }
  const qx = (deg) => { const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), rad(deg)); return [q.x, q.y, q.z, q.w] }
  const theta = (f) => (f <= 15 ? -10 + (25 * f) / 15 : 15 - (15 * (f - 15)) / 15)
  const TIMES = Array.from({ length: 31 }, (_, f) => f / 30)
  const clip = (hipsY = (f) => (f <= 15 ? 0.98 : 1.08)) => new THREE.AnimationClip('sweep', 1, [
    new THREE.VectorKeyframeTrack('mixamorigHips.position', TIMES, TIMES.flatMap((_, f) => [0, hipsY(f), 0])),
    new THREE.QuaternionKeyframeTrack('mixamorigLeftFoot.quaternion', TIMES, TIMES.flatMap((_, f) => qx(theta(f)))),
  ])
  const bones = (root) => { const out = {}; root.traverse((o) => { if (o.isBone) out[normBoneName(o.name)] = o }); return out }
  /** play `c` on a fresh rig at key f and read heel/ball/toe y, ankle y, knee position */
  const poseAt = (c, f) => {
    const r = rig()
    const mixer = new THREE.AnimationMixer(r)
    const a = mixer.clipAction(c); a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true; a.play()
    a.paused = false; mixer.setTime(TIMES[f]); r.updateMatrixWorld(true)
    const b = bones(r)
    const cts = footContactsNow(THREE, r, fp)
    return { heel: cts.left[0].y, ball: cts.left[1].y, toe: cts.left[2].y,
      ankle: b.leftfoot.getWorldPosition(new THREE.Vector3()).y, knee: b.leftleg.getWorldPosition(new THREE.Vector3()) }
  }
  const trackOf = (c, name) => c.tracks.find((t) => t.name === name)

  console.log('--- [1] levelTurn ---')
  const d = (deg) => [0, 0.15 * Math.sin(rad(deg)), 0.15 * Math.cos(rad(deg))]
  check('axis +x, d pitched 20° along +z → +20°', near(levelTurn([1, 0, 0], d(20)), rad(20), 1e-9), String(levelTurn([1, 0, 0], d(20))))
  check('axis +x, d pitched −10° → −10°', near(levelTurn([1, 0, 0], d(-10)), -rad(10), 1e-9))
  const back = (deg) => [0, 0.15 * Math.sin(rad(deg)), -0.15 * Math.cos(rad(deg))]
  check('heel − ball (pointing back) at 20° → −20°, at −10° → +10°',
    near(levelTurn([1, 0, 0], back(20)), -rad(20), 1e-9) && near(levelTurn([1, 0, 0], back(-10)), rad(10), 1e-9))
  check('a level d → 0', near(levelTurn([1, 0, 0], [0, 0, 0.15]), 0, 1e-12))
  check('a vertical axis → 0 (cannot level)', levelTurn([0, 1, 0], d(20)) === 0)

  console.log('--- [2] fadeRuns ---')
  check('PLANT_FADE_S = 0.15', PLANT_FADE_S === 0.15)
  const f2 = fadeRuns([1, 1, 1, 0, 0, 0, 0, 0, 0, 0], 30)
  check('[1,1,1,0…] → 1,1,1, 5/6 … 1/6, 0, 0', [1, 1, 1, 5 / 6, 4 / 6, 3 / 6, 2 / 6, 1 / 6, 0, 0].every((x, i) => near(f2[i], x, 1e-12)), f2.map((x) => x.toFixed(3)).join(' '))
  check('a run on the last frame is unchanged', fadeRuns([0, 0, 1, 1], 30).join() === '0,0,1,1')
  const f2b = fadeRuns([0.6, 0, 0, 0, 0, 0, 0], 30)
  check('[0.6, 0…] decays 0.5 … 0.1', [0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0].every((x, i) => near(f2b[i], x, 1e-12)))
  const f2c = fadeRuns([1, 0, 1, 0, 0, 0, 0, 0], 30)
  check('the decay never lowers a frame\'s own weight', [1, 5 / 6, 1, 5 / 6, 4 / 6, 3 / 6, 2 / 6, 1 / 6].every((x, i) => near(f2c[i], x, 1e-12)))

  console.log('--- [3] plantSampleTimes ---')
  check('hips position keys → 31 times', plantSampleTimes(clip()).length === 31 && near(plantSampleTimes(clip())[30], 1))
  const noHips = new THREE.AnimationClip('x', 1, [new THREE.QuaternionKeyframeTrack('mixamorigLeftFoot.quaternion', [0, 1], [...qx(0), ...qx(5)])])
  check('no hips track → 31 uniform times', plantSampleTimes(noHips).length === 31 && near(plantSampleTimes(noHips)[15], 0.5))

  console.log('--- [4] no-ops ---')
  const rest = null
  const posed = applyFootPose(THREE, clip(), fp, rest)
  check('applyFootPose marks the clip (deg 0: values unchanged)', posed.userData.footPosed === 'abc'
    && trackOf(posed, 'mixamorigLeftFoot.quaternion').values.every((x, i) => x === trackOf(clip(), 'mixamorigLeftFoot.quaternion').values[i]))
  check('another fsig → the same object', plantFootPose(THREE, posed, clip(), rig(), { ...fp, source: { ...fp.source, fsig: 'zzz' } }) === posed)
  const marked = new THREE.AnimationClip('m', 1, posed.tracks); marked.userData = { footPosed: 'abc', footPlanted: 'abc' }
  check('an already planted clip → the same object', plantFootPose(THREE, marked, clip(), rig(), fp) === marked)
  check('a rig without leg bones → the same object', plantFootPose(THREE, posed, clip(), rig(false), fp, { rootY: 0.052 }) === posed)
  const airborne = clip(() => 1.08)
  const airPosed = applyFootPose(THREE, airborne, fp, rest)
  const airPlanted = plantFootPose(THREE, airPosed, airborne, rig(), fp, { rootY: 0.052 })
  check('no stance anywhere → a new clip, marked, every value identical', airPlanted !== airPosed && airPlanted.userData.footPlanted === 'abc'
    && airPlanted.tracks.length === airPosed.tracks.length
    && airPlanted.tracks.every((t, i) => t.values.every((x, j) => x === airPosed.tracks[i].values[j])))

  console.log('--- [5] a planted frame: level, on the floor, the knee by the IK ---')
  const probe = rig()
  const bindSnapshot = []
  probe.traverse((o) => { if (o.isBone) bindSnapshot.push([o, o.quaternion.clone(), o.position.clone()]) })
  const planted = plantFootPose(THREE, posed, clip(), probe, fp, { rootY: 0.052, unitsPerCm: 0.01 })
  check('a new clip, footPlanted abc, footPosed kept', planted !== posed && planted.userData.footPlanted === 'abc' && planted.userData.footPosed === 'abc')
  for (const f of [0, 6, 12, 14]) {
    const p = poseAt(planted, f)
    check(`f=${f} (θ ${theta(f).toFixed(2)}°): heel = ball = −0.052, toe −0.047, ankle 0.048`,
      near(p.heel, -0.052) && near(p.ball, -0.052) && near(p.toe, -0.047) && near(p.ankle, 0.048),
      `${p.heel.toFixed(7)} ${p.ball.toFixed(7)} ${p.toe.toFixed(7)} ${p.ankle.toFixed(7)}`)
    check(`f=${f}: knee (0, 0.514, 0.0885664)`, near(p.knee.x, 0) && near(p.knee.y, 0.514) && near(p.knee.z, 0.0885664), `${p.knee.y.toFixed(7)} ${p.knee.z.toFixed(7)}`)
  }

  console.log('--- [6] after lift-off: the decayed weight, the forepart held ---')
  {
    const p = poseAt(planted, 15)
    check('f=15: ankle 0.0568890, heel −0.0267627, ball −0.0473778, toe −0.0441273',
      near(p.ankle, 0.0568890) && near(p.heel, -0.0267627) && near(p.ball, -0.0473778) && near(p.toe, -0.0441273),
      `${p.ankle.toFixed(7)} ${p.heel.toFixed(7)} ${p.ball.toFixed(7)} ${p.toe.toFixed(7)}`)
    check('f=15: knee (0, 0.5184445, 0.1093915)', near(p.knee.y, 0.5184445) && near(p.knee.z, 0.1093915), `${p.knee.y.toFixed(7)} ${p.knee.z.toFixed(7)}`)
    const q = poseAt(planted, 16)
    check('f=16: the leg at full reach — ankle 0.1313167, ball 0.0235123, knee (0, 0.6056584, 0)',
      near(q.ankle, 0.1313167) && near(q.ball, 0.0235123) && near(q.knee.y, 0.6056584) && near(q.knee.z, 0),
      `${q.ankle.toFixed(7)} ${q.ball.toFixed(7)} ${q.knee.y.toFixed(7)} ${q.knee.z.toFixed(7)}`)
  }

  console.log('--- [7] swing frames keep q · R ---')
  {
    const inFoot = trackOf(posed, 'mixamorigLeftFoot.quaternion').values
    const outFoot = trackOf(planted, 'mixamorigLeftFoot.quaternion').values
    let same = true
    for (let f = 20; f <= 30; f++) for (let k = 0; k < 4; k++) if (Math.abs(outFoot[f * 4 + k] - inFoot[f * 4 + k]) > 1e-7) same = false
    check('f=20…30: the Foot track equals the input', same)
    const identityAt = (name) => { const t = trackOf(planted, name); let ok = !!t && t.times.length === 31
      for (let f = 20; f <= 30 && ok; f++) ok = near(t.values[f * 4], 0, 1e-7) && near(t.values[f * 4 + 1], 0, 1e-7) && near(t.values[f * 4 + 2], 0, 1e-7) && near(Math.abs(t.values[f * 4 + 3]), 1, 1e-7)
      return ok }
    check('f=20…30: UpLeg / Leg / ToeBase keys identity (31 keys each)',
      identityAt('mixamorigLeftUpLeg.quaternion') && identityAt('mixamorigLeftLeg.quaternion') && identityAt('mixamorigLeftToeBase.quaternion'))
    const p = poseAt(planted, 20)
    check('f=20: the heel where the unplanted clip puts it (0.0902015)', near(p.heel, 0.0902015), p.heel.toFixed(7))
  }

  console.log('--- [8] a pierce is lifted in full ---')
  {
    const pierced = plantFootPose(THREE, posed, clip(), rig(), fp, { rootY: 0, unitsPerCm: 0.01 })
    const p = poseAt(pierced, 6)
    check('rootY 0, f=6: heel = ball = 0, ankle 0.10', near(p.heel, 0) && near(p.ball, 0) && near(p.ankle, 0.10), `${p.heel.toFixed(7)} ${p.ball.toFixed(7)} ${p.ankle.toFixed(7)}`)
    check('f=6: knee (0, 0.54, 0.1772005)', near(p.knee.y, 0.54) && near(p.knee.z, 0.1772005), `${p.knee.y.toFixed(7)} ${p.knee.z.toFixed(7)}`)
    const q = poseAt(pierced, 15)
    check('f=15 (w′ 5/6): the whole pierce lifted — ball 0, ankle 0.1042668, heel 0.0206151, toe 0.0032505',
      near(q.ball, 0) && near(q.ankle, 0.1042668) && near(q.heel, 0.0206151) && near(q.toe, 0.0032505),
      `${q.ball.toFixed(7)} ${q.ankle.toFixed(7)} ${q.heel.toFixed(7)} ${q.toe.toFixed(7)}`)
  }

  console.log('--- [9] the probe and the inputs are left as found ---')
  check('every probe bone back in its bind pose', bindSnapshot.every(([o, q, p]) => o.quaternion.equals(q) && o.position.equals(p)))
  check('the input clips are untouched', !clip().userData.footPlanted && posed.userData.footPlanted === undefined
    && trackOf(posed, 'mixamorigLeftFoot.quaternion').values.every((x, i) => x === trackOf(clip(), 'mixamorigLeftFoot.quaternion').values[i]))

  if (failures.length) {
    console.log(`\nFAIL: ${failures.length} check(s) failed`)
    process.exit(1)
  }
  console.log('\nOK: shod foot plant — level, floor by the leg, forepart held, lift-off decay, pierce lifted in full')
}

main().catch((err) => { console.error(err); process.exit(1) })
