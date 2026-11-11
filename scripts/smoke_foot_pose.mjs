#!/usr/bin/env node
/**
 * Smoke check for the FOOT POSE — `packages/scene-render/src/footPose.ts`:
 * the clip extension (`applyFootPose`), the still pose (`applyFootPoseToPose`),
 * the root lift by height group (`footPoseLiftM`), the shoe match
 * (`footPoseMatches`) and the sole contacts by the collision endpoint rule
 * (`footContactsNow`).
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_foot_pose.mjs
 *
 * Every expected number is derived BY HAND (§ B5a). A rotation by θ about
 * +x (right hand) takes (y, z) to (y·cosθ − z·sinθ, y·sinθ + z·cosθ);
 * cos 28° = 0.8829476, sin 28° = 0.4694716. Quaternions are (x, y, z, w);
 * R(+x, θ) = (sin θ/2, 0, 0, cos θ/2), so R(+x, 28°) = (0.2419219, 0, 0, 0.9702957).
 *
 * The chain: root group → bone `mixamorigLeftFoot` at (0, 0.08, 0), bind
 * identity → child `mixamorigLeftToeBase` at local (0, −0.06, 0.13); a body
 * SkinnedMesh on [Foot, ToeBase] bound at the identity. The foot pose names
 * the bone as the GLB joint `mixamorig:LeftFoot` (three's loader drops the
 * colon from node names — `normBoneName` makes both `leftfoot`):
 *   fp = {version 1, source {item_id 'i', fsig 'abc', glb_sha256 'x'},
 *         bones {'mixamorig:LeftFoot': {axis [1,0,0], deg 28}},
 *         root_lift_m 0.052,
 *         contacts {left: [ball (0,0.02,0.15) on LeftToeBase,
 *                          heel (0,0,−0.05) on LeftFoot], right: []}}.
 *
 * [1] applyFootPose on a one-key clip (Foot identity) + mixer frame 0: the
 *     ToeBase (the ball joint) turns 28° about the ankle (0, 0.08, 0):
 *       rel (0, −0.06, 0.13) → y = 0.08 − 0.06·cos28° − 0.13·sin28°,
 *                              z = −0.06·sin28° + 0.13·cos28°
 *       = (0, −0.034008, 0.086615) (±1e-6).
 *     The input clip is untouched (its key stays identity); the result is
 *     marked `userData.footPosed = 'abc'`.
 * [2] Idempotent: applyFootPose on the marked result returns that same clip
 *     (===, values unchanged); applyFootPose on the original again gives the
 *     same key values.
 * [3] Every key: a two-key Foot track, key 0 identity, key 1 R(+y, 90°)
 *     = (0, 0.7071068, 0, 0.7071068) → key 1' = R(+y,90°)·R(+x,28°):
 *       w = 0.7071068·0.9702957 = 0.6861034,
 *       v = 0.7071068·(0.2419219,0,0) + 0.9702957·(0,0.7071068,0)
 *           + (0,0.7071068,0)×(0.2419219,0,0)
 *         = (0.1710655, 0.6861034, −0.1710655).
 * [4] A bone without a track gets a CONSTANT one: fp names
 *     `mixamorig:LeftToeBase` {axis [1,0,0], deg −10}, the clip has only the
 *     Foot track → a one-key ToeBase quaternion track appears, value
 *     R(+x, −10°) = (−0.0871557, 0, 0, 0.9961947) (rest identity, no rest
 *     given). With the target's rest pose given (ToeBase rest local
 *     R(+z, 90°) = (0, 0, 0.7071068, 0.7071068)) the value is rest·R:
 *       w = 0.7071068·0.9961947 = 0.7044160,
 *       v = 0.7071068·(−0.0871557,0,0) + 0.9961947·(0,0,0.7071068)
 *           + (0,0,0.7071068)×(−0.0871557,0,0)
 *         = (−0.0616284, −0.0616284, 0.7044160).
 * [5] footPoseLiftM: 'ground' → 0.052, 'seat'/'lie' → 0, undefined → 0.052
 *     (unknown = ground, `clipHeightGroup`); figure height 0.85 m →
 *     0.052·0.85/1.70 = 0.026; version 2 → 0; null → 0.
 * [6] footPoseMatches: a node {garment {kind 'footwear', fsig 'abc',
 *     item_id 'i'}} under root → true for fsig 'abc'; false for 'abd', for
 *     item_id 'j', for kind 'hair', for a bare root, for null.
 * [7] footContactsNow after the 28° pose (endpoint rule: a bind point fixed
 *     to its joint turns with it about the ankle):
 *       ball (0, 0.02, 0.15): rel (0, −0.06, 0.15) →
 *         (0, 0.08 − 0.06·cos28° − 0.15·sin28°, −0.06·sin28° + 0.15·cos28°)
 *         = (0, −0.0433976, 0.1042738);
 *       heel (0, 0, −0.05) on Foot: rel (0, −0.08, −0.05) →
 *         (0, 0.08 − 0.08·cos28° + 0.05·sin28°, −0.08·sin28° − 0.05·cos28°)
 *         = (0, 0.0328378, −0.0817051);
 *     right: none. Root moved to (1, 0, 0) → every x + 1 (the bind matrices
 *     stay, the mesh's world frame moves). A contact on a bone the figure
 *     lacks is left out. `out` is reused (same Vector3 objects).
 *     null fp → both sides empty.
 * [8] applyFootPoseToPose on a fresh chain: the ToeBase world position is
 *     [1]'s (0, −0.034008, 0.086615); a second call changes nothing; the root
 *     is marked `userData.footPosed = 'abc'`; null fp → no mark, no change.
 * [9] null fp: applyFootPose returns its input (===).
 * [10] transplantedRestPose (clipRetarget.ts) — the rest the clips see on
 *     the chain, with donor = the chain's own rest and ONE correction,
 *     leftfoot {left identity, right R(+x, −6°)}: the Foot plays
 *     `left · c_d · right` = R(+x, −6°) = (−0.0523360, 0, 0, 0.9986295)
 *     (c_d = the donor's rest local = identity), the ToeBase (donor has it,
 *     no correction) keeps its local identity under it → world R(+x, −6°)
 *     as well, parent(toe) = world(foot); positions: foot (0, 0.08, 0),
 *     toe = foot + R(−6°)·(0, −0.06, 0.13) = (0, 0.08 − 0.06·cos6° +
 *     0.13·sin6°, 0.06·sin6° + 0.13·cos6°) = (0, 0.0339174, 0.1355596).
 *     A bone the donor LACKS keeps its own rest local: a `mixamorigLeftToe_End`
 *     under the ToeBase with local R(+z, 90°) → world R(+x,−6°)·R(+z,90°) =
 *     (−0.0370071, 0.0370071, 0.7061377, 0.7061377). Empty corrections →
 *     world == the chain's rest for every bone.
 * [11] applyFootPose with rest + clipRest (module docstring: the extension is
 *     relative to the BIND foot, the clip to the transplanted rest). fpToe
 *     (Foot 28°, ToeBase −10°) on the one-key Foot clip, clipRest = [10]'s:
 *     the Foot is the top named bone → its WORLD delta D = W_bind⁻¹·W_clip
 *     = R(+x, −6°) → turn D⁻¹·R = R(+x, 34°) = (0.2923717, 0, 0, 0.9563048);
 *     mixer frame 0 puts the ball at rel (0, −0.06, 0.13) turned 34°:
 *     (0, 0.08 − 0.06·cos34° − 0.13·sin34°, −0.06·sin34° + 0.13·cos34°) =
 *     (0, −0.0424373, 0.0742233). The ToeBase has a named ancestor → its
 *     LOCAL delta, identity here (no track: it keeps its bind local; with an
 *     identity track: clipLocal = parent⁻¹·world = identity too) → the
 *     constant track stays R(+x, −10°) = (−0.0871557, 0, 0, 0.9961947).
 *     A correction that also turns the ToeBase locally, lefttoebase {left
 *     identity, right R(+x, +4°)}: clipLocal(toe) = R(4°) → turn
 *     R(−4°)·R(−10°) = R(+x, −14°) = (−0.1218693, 0, 0, 0.9925462), the Foot
 *     unchanged at 34°. rest alone (no clipRest) → R(28°) as in [1]; a
 *     clipRest lacking the bone → R(28°).
 * [12] seatFootLift (Task 22, P3b) on a seated leg: root → UpLeg (0, 0.45, 0)
 *     → Leg local (0, 0, 0.45) → Foot local (0, −0.45, 0), i.e. hip H
 *     (0, 0.45, 0), knee K (0, 0.45, 0.45), ankle A (0, 0, 0.45); a body
 *     SkinnedMesh bound at the identity; the record's left heel contact
 *     (0, −0.04, 0.45) on LeftFoot = 0.04 below the ankle; floor y = 0.
 *     d = floor − lowest contact = 0.04 ≥ 0.015 → raise r = d = 0.04 →
 *     ankle target T (0, 0.04, 0.45); |H−T| = √(0.45² + 0.41²) = 0.608769;
 *     knee interior angle acos((2·0.45² − 0.370600)/(2·0.45²)) = 85.128°;
 *     the knee stays in the plane of H→T and the old knee (the pole), on
 *     its side: hip angle cos α = 0.608769/0.9 = 0.676410, t = (0, −0.41,
 *     0.45)/0.608769, u = the pole's part ⊥ t = (0, 0.739170, 0.673451) →
 *     K' = H + 0.45·(cos α·t + sin α·u) = (0, 0.489996, 0.448219) (±1e-6);
 *     the ankle lands on T (±1e-6); the hip (UpLeg position) is unchanged;
 *     the Foot keeps its WORLD quaternion (given a local R(+y, 20°) before —
 *     about the vertical, so the heel stays 0.04 below the ankle: the same
 *     world quaternion after, ±1e-9), so the heel contact follows
 *     the ankle up by 0.04 and the lowest contact is ON the floor (±1e-6);
 *     the return is {left 0.04, right 0}. The raise curve `seatRaise`:
 *     r(0) = 0.015²/0.06 = 0.00375, r(−0.02) = 0, r(−0.015) = 0,
 *     r(0.015) = 0.015 (C¹ at both ends), r(0.03) = 0.03. A contact 0.10
 *     ABOVE the floor (floor y = −0.14, a crossed leg): d = −0.10 → r = 0,
 *     the knee does not move, {0, 0}. null fp → {0, 0}, nothing moves.
 * [N1] A NEGATIVE turn and a NEGATIVE lift pass through unchanged (boots plan
 *     Task 1, spec 2026-11-11 § 13.2: a flat shoe dorsiflexes a foot whose
 *     bind pose stands heel-up and the root goes DOWN). The chain of [1] with
 *     fp bones {LeftFoot {axis [1,0,0], deg −10}}, root_lift_m −0.0136:
 *       applyFootPose + mixer frame 0 → ball rel (0, −0.06, 0.13) turned −10°:
 *       y = 0.08 − 0.06·cos10° + 0.13·sin10° = 0.08 − 0.0590885 + 0.0225738
 *         = 0.0434853,
 *       z = −0.06·sin(−10°) + 0.13·cos10° = 0.0104189 + 0.1280250 = 0.1384439
 *       → (0, 0.043486, 0.138444) (±1e-6); applyFootPoseToPose the same;
 *     footPoseLiftM(fp, 'ground') = −0.0136 (signed, no clamp), 'seat' → 0.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_foot_pose_bundled.mjs'
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

  const F = await import('../packages/scene-render/src/footPose.ts')
  const { restPoseOf, transplantedRestPose } = await import('../packages/scene-render/src/clipRetarget.ts')
  const THREE = await import('three')
  const { applyFootPose, applyFootPoseToPose, footPoseLiftM, footPoseMatches, footContactsNow, seatFootLift, seatRaise } = F

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const EPS = 1e-6
  const near = (a, b, eps = EPS) => Math.abs(a - b) <= eps
  const nearV = (v, e, eps = EPS) => near(v[0], e[0], eps) && near(v[1], e[1], eps) && near(v[2], e[2], eps)
  const fmt = (v) => `(${Array.from(v).map((x) => x.toFixed(7)).join(', ')})`

  const fp = {
    version: 1,
    source: { item_id: 'i', fsig: 'abc', glb_sha256: 'x' },
    bones: { 'mixamorig:LeftFoot': { axis: [1, 0, 0], deg: 28 } },
    root_lift_m: 0.052,
    contacts: {
      left: [
        { bone: 'mixamorig:LeftToeBase', pos: [0, 0.02, 0.15], role: 'ball' },
        { bone: 'mixamorig:LeftFoot', pos: [0, 0, -0.05], role: 'heel' },
        { bone: 'mixamorig:LeftGhost', pos: [0, 0, 0], role: 'toe' },
      ],
      right: [],
    },
  }

  /** root → Foot (0, 0.08, 0) → ToeBase (0, −0.06, 0.13); a body SkinnedMesh bound at the identity. */
  const chain = () => {
    const root = new THREE.Group()
    const foot = new THREE.Bone(); foot.name = 'mixamorigLeftFoot'; foot.position.set(0, 0.08, 0)
    const toe = new THREE.Bone(); toe.name = 'mixamorigLeftToeBase'; toe.position.set(0, -0.06, 0.13)
    foot.add(toe)
    root.add(foot)
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 0, 0.1, 0, 0, 0, 0.1], 3))
    geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0], 4))
    geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
    const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
    root.add(mesh)
    root.updateMatrixWorld(true)
    mesh.bind(new THREE.Skeleton([foot, toe]))
    return { root, foot, toe, mesh }
  }
  const worldOf = (o) => { const v = new THREE.Vector3(); o.getWorldPosition(v); return [v.x, v.y, v.z] }
  const BALL = [0, -0.034008, 0.086615]
  const play = (fig, clip) => {
    const mixer = new THREE.AnimationMixer(fig.root)
    mixer.clipAction(clip).play()
    mixer.update(0)
    fig.root.updateMatrixWorld(true)
    return mixer
  }
  const ID = [0, 0, 0, 1]

  console.log('--- [1] applyFootPose on a one-key clip, mixer frame 0 ---')
  const clip = new THREE.AnimationClip('stand', 1, [
    new THREE.QuaternionKeyframeTrack('mixamorigLeftFoot.quaternion', [0], ID),
  ])
  const posed = applyFootPose(THREE, clip, fp)
  const fig1 = chain()
  play(fig1, posed)
  const ball1 = worldOf(fig1.toe)
  check('ball world = (0, −0.034008, 0.086615)', nearV(ball1, BALL), fmt(ball1))
  check('input clip untouched', Array.from(clip.tracks[0].values).join() === ID.join())
  check('result marked footPosed = abc', posed.userData?.footPosed === 'abc', String(posed.userData?.footPosed))
  check('result is a new clip', posed !== clip)
  const k1 = posed.tracks.find((t) => t.name === 'mixamorigLeftFoot.quaternion').values
  check('foot key = R(+x, 28°)', nearV([k1[0], k1[1], k1[2]], [0.2419219, 0, 0]) && near(k1[3], 0.9702957), fmt(k1))

  console.log('--- [2] idempotent ---')
  const again = applyFootPose(THREE, posed, fp)
  check('marked clip returned unchanged (===)', again === posed)
  check('its values unchanged', Array.from(again.tracks[0].values).every((v, i) => v === k1[i]))
  const twice = applyFootPose(THREE, clip, fp)
  const fig2 = chain()
  play(fig2, twice)
  check('original again → same ball', nearV(worldOf(fig2.toe), ball1, 1e-12), fmt(worldOf(fig2.toe)))

  console.log('--- [3] every key is post-multiplied ---')
  const two = new THREE.AnimationClip('two', 1, [
    new THREE.QuaternionKeyframeTrack('mixamorigLeftFoot.quaternion', [0, 1],
      [0, 0, 0, 1, 0, Math.SQRT1_2, 0, Math.SQRT1_2]),
  ])
  const t2 = applyFootPose(THREE, two, fp).tracks[0].values
  check('key 0 = R(+x,28°)', nearV([t2[0], t2[1], t2[2]], [0.2419219, 0, 0]) && near(t2[3], 0.9702957),
    fmt(t2.slice(0, 4)))
  check('key 1 = R(+y,90°)·R(+x,28°) = (0.1710655, 0.6861034, −0.1710655, 0.6861034)',
    // the keys are stored as Float32 (input SQRT1_2 included): 2e-6 instead of 1e-6
    nearV([t2[4], t2[5], t2[6]], [0.1710655, 0.6861034, -0.1710655], 2e-6) && near(t2[7], 0.6861034, 2e-6),
    fmt(t2.slice(4, 8)))

  console.log('--- [4] a bone without a track gets a constant one ---')
  const fpToe = { ...fp, bones: { ...fp.bones, 'mixamorig:LeftToeBase': { axis: [1, 0, 0], deg: -10 } } }
  const withToe = applyFootPose(THREE, clip, fpToe)
  const toeTrack = withToe.tracks.find((t) => t.name.endsWith('.quaternion') && /toebase/i.test(t.name))
  check('a ToeBase quaternion track was added', !!toeTrack, toeTrack?.name ?? 'none')
  if (toeTrack) {
    const v = toeTrack.values
    check('one key', toeTrack.times.length === 1 && v.length === 4)
    check('value R(+x, −10°) = (−0.0871557, 0, 0, 0.9961947)',
      nearV([v[0], v[1], v[2]], [-0.0871557, 0, 0]) && near(v[3], 0.9961947), fmt(v))
  }
  // a target whose ToeBase rest local rotation is R(+z, 90°)
  const restRoot = new THREE.Group()
  const rf = new THREE.Bone(); rf.name = 'mixamorigLeftFoot'
  const rt = new THREE.Bone(); rt.name = 'mixamorigLeftToeBase'
  rt.quaternion.set(0, 0, Math.SQRT1_2, Math.SQRT1_2)
  rf.add(rt); restRoot.add(rf)
  const rest = restPoseOf(THREE, restRoot)
  const withRest = applyFootPose(THREE, clip, fpToe, rest)
  const toeRest = withRest.tracks.find((t) => /toebase/i.test(t.name))
  check('with rest: value rest·R = (−0.0616284, −0.0616284, 0.7044160, 0.7044160)',
    !!toeRest && nearV([toeRest.values[0], toeRest.values[1], toeRest.values[2]], [-0.0616284, -0.0616284, 0.7044160])
      && near(toeRest.values[3], 0.7044160), toeRest ? fmt(toeRest.values) : 'none')
  check('foot track still the only one besides it', withToe.tracks.length === 2, String(withToe.tracks.length))

  console.log('--- [5] footPoseLiftM ---')
  check("ground → 0.052", near(footPoseLiftM(fp, 'ground'), 0.052, 1e-12), String(footPoseLiftM(fp, 'ground')))
  check("seat → 0", footPoseLiftM(fp, 'seat') === 0)
  check("lie → 0", footPoseLiftM(fp, 'lie') === 0)
  check("undefined → 0.052", near(footPoseLiftM(fp, undefined), 0.052, 1e-12))
  check("figure 0.85 m → 0.026", near(footPoseLiftM(fp, 'ground', 0.85), 0.026, 1e-12),
    String(footPoseLiftM(fp, 'ground', 0.85)))
  check("version 2 → 0", footPoseLiftM({ ...fp, version: 2 }, 'ground') === 0)
  check("null → 0", footPoseLiftM(null, 'ground') === 0)

  console.log('--- [6] footPoseMatches ---')
  const shod = new THREE.Group()
  const shoe = new THREE.Group()
  shoe.userData.garment = { kind: 'footwear', fsig: 'abc', item_id: 'i' }
  const holder = new THREE.Group(); holder.add(shoe); shod.add(holder)
  check("fsig 'abc' → true", footPoseMatches(shod, fp) === true)
  check("fsig 'abd' → false", footPoseMatches(shod, { ...fp, source: { ...fp.source, fsig: 'abd' } }) === false)
  check("item_id 'j' → false", footPoseMatches(shod, { ...fp, source: { ...fp.source, item_id: 'j' } }) === false)
  const hairRoot = new THREE.Group(); const hair = new THREE.Group()
  hair.userData.garment = { kind: 'hair', fsig: 'abc', item_id: 'i' }; hairRoot.add(hair)
  check("kind 'hair' → false", footPoseMatches(hairRoot, fp) === false)
  check('bare root → false', footPoseMatches(new THREE.Group(), fp) === false)
  check('null fp → false', footPoseMatches(shod, null) === false)

  console.log('--- [7] footContactsNow ---')
  const c1 = footContactsNow(THREE, fig1.root, fp)
  check('left: two points (the ghost bone left out)', c1.left.length === 2, String(c1.left.length))
  check('right: none', c1.right.length === 0)
  const ball7 = c1.left[0] ? [c1.left[0].x, c1.left[0].y, c1.left[0].z] : [NaN, NaN, NaN]
  const heel7 = c1.left[1] ? [c1.left[1].x, c1.left[1].y, c1.left[1].z] : [NaN, NaN, NaN]
  check('ball contact = (0, −0.0433976, 0.1042738)', nearV(ball7, [0, -0.0433976, 0.1042738]), fmt(ball7))
  check('heel contact = (0, 0.0328378, −0.0817051)', nearV(heel7, [0, 0.0328378, -0.0817051]), fmt(heel7))
  fig1.root.position.set(1, 0, 0)
  fig1.root.updateMatrixWorld(true)
  const firstVec = c1.left[0]
  const c2 = footContactsNow(THREE, fig1.root, fp, c1)
  check('out reused', c2 === c1 && c2.left[0] === firstVec)
  check('root at x = 1 → ball (1, −0.0433976, 0.1042738)',
    nearV([c2.left[0].x, c2.left[0].y, c2.left[0].z], [1, -0.0433976, 0.1042738]), fmt(c2.left[0].toArray()))
  check('root at x = 1 → heel (1, 0.0328378, −0.0817051)',
    nearV([c2.left[1].x, c2.left[1].y, c2.left[1].z], [1, 0.0328378, -0.0817051]), fmt(c2.left[1].toArray()))
  const cNull = footContactsNow(THREE, fig1.root, null)
  check('null fp → both sides empty', cNull.left.length === 0 && cNull.right.length === 0)

  console.log('--- [8] applyFootPoseToPose ---')
  const fig3 = chain()
  applyFootPoseToPose(THREE, fig3.root, fp)
  fig3.root.updateMatrixWorld(true)
  const ball8 = worldOf(fig3.toe)
  check('ball world = (0, −0.034008, 0.086615)', nearV(ball8, BALL), fmt(ball8))
  check('root marked footPosed = abc', fig3.root.userData.footPosed === 'abc')
  applyFootPoseToPose(THREE, fig3.root, fp)
  fig3.root.updateMatrixWorld(true)
  check('second call changes nothing', nearV(worldOf(fig3.toe), ball8, 0), fmt(worldOf(fig3.toe)))
  const fig4 = chain()
  applyFootPoseToPose(THREE, fig4.root, null)
  fig4.root.updateMatrixWorld(true)
  check('null fp → no mark', fig4.root.userData.footPosed === undefined)
  check('null fp → ball at rest (0, 0.02, 0.13)', nearV(worldOf(fig4.toe), [0, 0.02, 0.13], 1e-12))

  console.log('--- [9] null fp ---')
  check('applyFootPose(null) returns its input', applyFootPose(THREE, clip, null) === clip)
  check('applyFootPose(undefined) returns its input', applyFootPose(THREE, clip, undefined) === clip)

  console.log('--- [10] transplantedRestPose ---')
  const figR = chain()
  const donorR = restPoseOf(THREE, figR.root)
  const selfR = restPoseOf(THREE, figR.root)
  const qx = (deg) => new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), deg * Math.PI / 180)
  const corr = new Map([['leftfoot', { left: new THREE.Quaternion(), right: qx(-6) }]])
  const clipRest = transplantedRestPose(THREE, donorR, selfR, corr)
  const q4 = (q) => [q.x, q.y, q.z, q.w]
  const nearQ = (q, e, eps = EPS) => q4(q).every((v, i) => near(v, e[i], eps))
  const RX6 = [-0.0523360, 0, 0, 0.9986295]
  check('world(leftfoot) = R(+x, −6°)', nearQ(clipRest.world.get('leftfoot'), RX6), fmt(q4(clipRest.world.get('leftfoot'))))
  check('world(lefttoebase) = R(+x, −6°) (local identity under the foot)',
    nearQ(clipRest.world.get('lefttoebase'), RX6), fmt(q4(clipRest.world.get('lefttoebase'))))
  check('parent(lefttoebase) = world(leftfoot)', nearQ(clipRest.parent.get('lefttoebase'), RX6))
  check('parentBone copied', clipRest.parentBone.get('lefttoebase') === 'leftfoot' && clipRest.parentBone.get('leftfoot') === null)
  check('position(leftfoot) = (0, 0.08, 0)', nearV(clipRest.position.get('leftfoot').toArray(), [0, 0.08, 0], 1e-12))
  check('position(lefttoebase) = (0, 0.0339174, 0.1355596)',
    nearV(clipRest.position.get('lefttoebase').toArray(), [0, 0.0339174, 0.1355596]), fmt(clipRest.position.get('lefttoebase').toArray()))
  const figE = chain()
  const end = new THREE.Bone(); end.name = 'mixamorigLeftToe_End'; end.position.set(0, 0, 0.05)
  end.quaternion.set(0, 0, Math.SQRT1_2, Math.SQRT1_2); figE.toe.add(end); figE.root.updateMatrixWorld(true)
  const clipRestE = transplantedRestPose(THREE, donorR, restPoseOf(THREE, figE.root), corr)
  check('a bone the donor lacks keeps its rest local: world(toe_end) = R(+x,−6°)·R(+z,90°)',
    nearQ(clipRestE.world.get('lefttoe_end'), [-0.0370071, 0.0370071, 0.7061377, 0.7061377]), fmt(q4(clipRestE.world.get('lefttoe_end'))))
  const clipRest0 = transplantedRestPose(THREE, donorR, selfR, new Map())
  check('empty corrections → world == rest', [...selfR.world.keys()].every((k) => nearQ(clipRest0.world.get(k), q4(selfR.world.get(k)), 1e-12)))

  console.log('--- [11] applyFootPose with rest + clipRest ---')
  const under = applyFootPose(THREE, clip, fpToe, selfR, clipRest)
  const kf = under.tracks.find((t) => /leftfoot\.quaternion$/i.test(t.name)).values
  check('foot key = D⁻¹·R = R(+x, 34°) = (0.2923717, 0, 0, 0.9563048)',
    nearV([kf[0], kf[1], kf[2]], [0.2923717, 0, 0]) && near(kf[3], 0.9563048), fmt(kf))
  const kt = under.tracks.find((t) => /toebase\.quaternion$/i.test(t.name)).values
  check('toe constant track unchanged R(+x, −10°)', nearV([kt[0], kt[1], kt[2]], [-0.0871557, 0, 0]) && near(kt[3], 0.9961947), fmt(kt))
  const fig11 = chain()
  play(fig11, under)
  check('ball world = (0, −0.0424373, 0.0742233)', nearV(worldOf(fig11.toe), [0, -0.0424373, 0.0742233]), fmt(worldOf(fig11.toe)))
  const clipT = new THREE.AnimationClip('t', 1, [
    new THREE.QuaternionKeyframeTrack('mixamorigLeftFoot.quaternion', [0], ID),
    new THREE.QuaternionKeyframeTrack('mixamorigLeftToeBase.quaternion', [0], ID),
  ])
  const underT = applyFootPose(THREE, clipT, fpToe, selfR, clipRest)
  const ktT = underT.tracks.find((t) => /toebase\.quaternion$/i.test(t.name)).values
  check('toe WITH an identity track: local delta identity → R(+x, −10°)',
    nearV([ktT[0], ktT[1], ktT[2]], [-0.0871557, 0, 0]) && near(ktT[3], 0.9961947), fmt(ktT))
  const corr2 = new Map([...corr, ['lefttoebase', { left: new THREE.Quaternion(), right: qx(4) }]])
  const under2 = applyFootPose(THREE, clipT, fpToe, selfR, transplantedRestPose(THREE, donorR, selfR, corr2))
  const kf2 = under2.tracks.find((t) => /leftfoot\.quaternion$/i.test(t.name)).values
  const kt2 = under2.tracks.find((t) => /toebase\.quaternion$/i.test(t.name)).values
  check('toe corrected by +4° locally → R(−4°)·R(−10°) = R(+x, −14°) = (−0.1218693, 0, 0, 0.9925462)',
    nearV([kt2[0], kt2[1], kt2[2]], [-0.1218693, 0, 0]) && near(kt2[3], 0.9925462), fmt(kt2))
  check('… and the foot still 34°', nearV([kf2[0], kf2[1], kf2[2]], [0.2923717, 0, 0]) && near(kf2[3], 0.9563048), fmt(kf2))
  const restOnly = applyFootPose(THREE, clip, fpToe, selfR).tracks.find((t) => /leftfoot\.quaternion$/i.test(t.name)).values
  check('rest alone → R(28°)', nearV([restOnly[0], restOnly[1], restOnly[2]], [0.2419219, 0, 0]) && near(restOnly[3], 0.9702957))
  const lacking = transplantedRestPose(THREE, donorR, selfR, corr); lacking.world.delete('leftfoot')
  const lack = applyFootPose(THREE, clip, fpToe, selfR, lacking).tracks.find((t) => /leftfoot\.quaternion$/i.test(t.name)).values
  check('clipRest lacking the bone → R(28°)', nearV([lack[0], lack[1], lack[2]], [0.2419219, 0, 0]) && near(lack[3], 0.9702957))

  console.log('--- [12] seatFootLift on a seated leg ---')
  const leg = (footDeg = 0) => {
    const root = new THREE.Group()
    const up = new THREE.Bone(); up.name = 'mixamorigLeftUpLeg'; up.position.set(0, 0.45, 0)
    const lo = new THREE.Bone(); lo.name = 'mixamorigLeftLeg'; lo.position.set(0, 0, 0.45)
    const ft = new THREE.Bone(); ft.name = 'mixamorigLeftFoot'; ft.position.set(0, -0.45, 0)
    up.add(lo); lo.add(ft); root.add(up)
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 0, 0.1, 0, 0, 0, 0.1], 3))
    geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0], 4))
    geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
    const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
    root.add(mesh)
    root.updateMatrixWorld(true)
    mesh.bind(new THREE.Skeleton([up, lo, ft]))
    if (footDeg) { ft.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), footDeg * Math.PI / 180); root.updateMatrixWorld(true) }
    return { root, up, lo, ft }
  }
  const fpSeat = { version: 1, source: { item_id: 'i', fsig: 'abc', glb_sha256: 'x' }, bones: {}, root_lift_m: 0.052,
    contacts: { left: [{ bone: 'mixamorig:LeftFoot', pos: [0, -0.04, 0.45], role: 'heel' }], right: [] } }
  const worldQ = (o) => { const q = new THREE.Quaternion(); o.getWorldQuaternion(q); return q4(q) }
  const seat = leg(20)
  const footQ0 = worldQ(seat.ft)
  const raised = seatFootLift(THREE, seat.root, fpSeat, 0)
  seat.root.updateMatrixWorld(true)
  check('returns {left 0.04, right 0}', near(raised.left, 0.04, 1e-9) && raised.right === 0, JSON.stringify(raised))
  check('knee → (0, 0.489996, 0.448219)', nearV(worldOf(seat.lo), [0, 0.489996, 0.448219]), fmt(worldOf(seat.lo)))
  check('ankle → (0, 0.04, 0.45)', nearV(worldOf(seat.ft), [0, 0.04, 0.45]), fmt(worldOf(seat.ft)))
  check('hip unchanged (0, 0.45, 0)', nearV(worldOf(seat.up), [0, 0.45, 0], 1e-12))
  check('Foot keeps its world quaternion (±1e-9)', nearQ(new THREE.Quaternion(...worldQ(seat.ft)), footQ0, 1e-9), fmt(worldQ(seat.ft)))
  const after = footContactsNow(THREE, seat.root, fpSeat)
  check('lowest contact ON the floor (heel follows the ankle up by 0.04)', near(after.left[0].y, 0, 1e-6), after.left[0].y.toFixed(7))
  check('seatRaise: r(0) = 0.00375, r(−0.02) = 0, r(−0.015) = 0, r(0.015) = 0.015, r(0.03) = 0.03',
    near(seatRaise(0), 0.00375, 1e-12) && seatRaise(-0.02) === 0 && seatRaise(-0.015) === 0 && near(seatRaise(0.015), 0.015, 1e-12) && near(seatRaise(0.03), 0.03, 1e-12))
  const crossed = leg()
  const r2 = seatFootLift(THREE, crossed.root, fpSeat, -0.14)
  crossed.root.updateMatrixWorld(true)
  check('a contact 0.10 above the floor → {0, 0}, knee unchanged', r2.left === 0 && r2.right === 0 && nearV(worldOf(crossed.lo), [0, 0.45, 0.45], 1e-12), fmt(worldOf(crossed.lo)))
  const bare = leg()
  const r3 = seatFootLift(THREE, bare.root, null, 0)
  bare.root.updateMatrixWorld(true)
  check('null fp → {0, 0}, nothing moves', r3.left === 0 && r3.right === 0 && nearV(worldOf(bare.lo), [0, 0.45, 0.45], 1e-12))

  console.log('--- [N1] a negative turn and a negative lift ---')
  const fpNeg = { ...fp, bones: { 'mixamorig:LeftFoot': { axis: [1, 0, 0], deg: -10 } }, root_lift_m: -0.0136 }
  const figN = chain()
  play(figN, applyFootPose(THREE, clip, fpNeg))
  const ballN = worldOf(figN.toe)
  check('−10° → ball world = (0, 0.043486, 0.138444)', nearV(ballN, [0, 0.043486, 0.138444]), fmt(ballN))
  const figN2 = chain()
  applyFootPoseToPose(THREE, figN2.root, fpNeg)
  figN2.root.updateMatrixWorld(true)
  check('still pose the same', nearV(worldOf(figN2.toe), [0, 0.043486, 0.138444]), fmt(worldOf(figN2.toe)))
  check("ground → −0.0136 (signed)", near(footPoseLiftM(fpNeg, 'ground'), -0.0136, 1e-12), String(footPoseLiftM(fpNeg, 'ground')))
  check("seat → 0", footPoseLiftM(fpNeg, 'seat') === 0)

  if (failures.length) {
    console.log(`\nFAIL: ${failures.length} check(s) failed`)
    process.exit(1)
  }
  console.log('\nOK: foot pose — extension, still pose, lift, match, contacts, transplanted rest, seat lift')
}

main().catch((err) => { console.error(err); process.exit(1) })
