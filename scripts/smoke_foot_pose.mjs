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
  const { restPoseOf } = await import('../packages/scene-render/src/clipRetarget.ts')
  const THREE = await import('three')
  const { applyFootPose, applyFootPoseToPose, footPoseLiftM, footPoseMatches, footContactsNow } = F

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

  if (failures.length) {
    console.log(`\nFAIL: ${failures.length} check(s) failed`)
    process.exit(1)
  }
  console.log('\nOK: foot pose — extension, still pose, lift, match, contacts')
}

main().catch((err) => { console.error(err); process.exit(1) })
