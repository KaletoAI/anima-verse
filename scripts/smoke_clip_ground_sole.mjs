#!/usr/bin/env node
/**
 * Smoke check for the SHARED CLIP GROUND — `packages/scene-render/src/clipGround.ts`:
 * the bare rule (`groundOffsetOf`, never a raise), the shod rule
 * (`soleGroundOffsetOf`, signed, measured on the foot pose's sole contacts
 * over the frames the sole stands flat) and the sampler `measureClipGround`.
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_clip_ground_sole.mjs
 *
 * Every expected number is derived BY HAND (§ B5a). A rotation by θ about
 * +x (right hand) takes (y, z) to (y·cosθ − z·sinθ, y·sinθ + z·cosθ).
 *
 * THE RIG: root group → bone `mixamorigLeftFoot` at (0, 0.08, 0), bind
 * identity → child `mixamorigLeftToeBase` at local (0, −0.06, 0.13). A body
 * SkinnedMesh bound at the identity, every vertex 100 % Foot: A (0.05, 0,
 * 0.05), B (−0.05, 0, −0.05) — the bind soles on y = 0 — and (0, 0.30, 0).
 * A shoe garment node `garment_footwear_i_left` (userData.garment {kind
 * footwear, item_id i, fsig abc}) with its own SkinnedMesh on the same
 * skeleton, 100 % Foot: (0, −0.02, −0.05), (0, −0.02, 0.10), (0, 0.05, 0.10)
 * — in the bind pose the shoe hangs 2 cm UNDER the bare soles, as a real
 * shoe does before the extension is applied.
 * fp = {version 1, source {item_id i, fsig abc}, bones {}, root_lift_m 0.052,
 *       contacts {left: [heel (0, −0.02, −0.05) on Foot, ball (0, −0.02,
 *       0.10) on Foot, toe (0, −0.015, 0.14) on ToeBase], right: []}}
 * — heel and ball are the shoe mesh's own lowest vertices.
 *
 * Relative to the ankle the heel contact is (0, −0.10, −0.05), the ball
 * (0, −0.10, 0.10), body A (0.05, −0.08, 0.05), body B (−0.05, −0.08, −0.05).
 * Under a Foot turn θ about +x their heights are
 *   heel  0.08 − 0.10·cosθ + 0.05·sinθ      ball  0.08 − 0.10·cosθ − 0.10·sinθ
 *   A     0.08 − 0.08·cosθ + 0.05·sinθ      B     0.08 − 0.08·cosθ − 0.05·sinθ
 * and heel − ball = 0.15·sinθ, so the sole counts as LEVEL (|heel − ball| ≤
 * SOLE_LEVEL_M = 0.01) while |θ| ≤ 3.82°.
 *
 * [1] the pure rules: groundOffsetOf as in client3d/scripts/smoke_clip_ground.mjs
 *     ((0.30, 0) → 0.30; (0, 0) → 0; (−0.05, 0) → 0; (0.30, 0.10) → 0.20;
 *     (0.05, 0.30) → 0; NaN/Infinity → 0); soleGroundOffsetOf is the signed
 *     difference: (−0.02, 0) → −0.02 (a raise), (0.03, 0.01) → 0.02,
 *     (NaN, 0) → 0, (0.3, NaN) → 0, (Infinity, 0) → 0.
 * [2] the anchor: `figureBox(probe).min.y` = 0 (garments excluded) while
 *     `Box3.setFromObject` reads −0.02 (the shoe mesh in bind).
 * [3] bare rule, one-key identity Foot clip: every skinned mesh is sampled,
 *     the shoe mesh included → lowest −0.02 → groundOffsetOf(−0.02, 0) = 0.
 *     With a Foot POSITION key (0, 0.13, 0) (the whole foot 5 cm higher):
 *     lowest = shoe −0.02 + 0.05 = 0.03 → offset 0.03 (the float is lowered).
 * [4] shod rule (fp matches), identity clip (level), rootY 0.052: the sole
 *     stands at −0.02 + 0.052 = 0.032 → soleGroundOffsetOf = 0.032 (lower by
 *     32 mm — the toy's lift overshoots). The 5 cm raised clip with rootY 0
 *     → 0.03; with rootY 0.052 → 0.082.
 * [5] shod rule on a SWEEP: Foot keys identity at t = 0 and R(+x, −20°) at
 *     t = 1 (the heel goes down, like a heel strike); slerp makes θ linear
 *     in t, and the sampler reads 25 frames f = 0 … 24 at t = f/24, θ_f =
 *     −20°·f/24. Level while |0.15·sinθ| ≤ 0.01: f ≤ 4 (θ = −3.333°:
 *     0.15·0.0581448 = 0.0087217 ✓; f = 5, θ = −4.1667°: 0.0108987 ✗). The
 *     stance frames are f = 0 … 4 and the lowest sole point over them is the
 *     heel at f = 4: 0.08 − 0.10·0.9983082 − 0.05·0.0581448 = −0.0227381
 *     (body A there is −0.0027719, B +0.0030426 — higher). rootY 0 →
 *     groundOffset = −0.0227381, a RAISE of 22.7 mm; rootY 0.03 → 0.0072619.
 *     The heel strike at f = 24 (θ = −20°: heel −0.0310703) is NOT the ground.
 * [6] shod rule with NO level frame: a one-key R(+x, −20°) clip → the
 *     fallback, all frames: lowest = heel −0.0310703 → offset −0.0310703.
 * [7] a foot pose of another fsig ('zzz') does not match → bare rule on the
 *     sweep: lowest over all frames = the shoe mesh's heel vertex at f = 24,
 *     −0.0310703 → groundOffsetOf → 0.
 * [8] a probe without a skinned mesh → nothing stored (clipGroundOffset 0);
 *     two clips in one call get their own offsets ([4]'s 0.032 and [5]'s
 *     −0.0227381 with rootY 0.052 → 0.0292619); clipGroundOffset reads
 *     0 off a clip never measured and off a non-numeric value.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_clip_ground_sole_bundled.mjs'
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

  const G = await import('../packages/scene-render/src/clipGround.ts')
  const { figureBox } = await import('../packages/scene-render/src/figure.ts')
  const THREE = await import('three')
  const { groundOffsetOf, soleGroundOffsetOf, clipGroundOffset, measureClipGround, SOLE_LEVEL_M } = G

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const EPS = 1e-6
  const near = (a, b, eps = EPS) => Math.abs(a - b) <= eps

  const fp = {
    version: 1,
    source: { item_id: 'i', fsig: 'abc', glb_sha256: 'x' },
    bones: {},
    root_lift_m: 0.052,
    contacts: {
      left: [
        { bone: 'mixamorig:LeftFoot', pos: [0, -0.02, -0.05], role: 'heel' },
        { bone: 'mixamorig:LeftFoot', pos: [0, -0.02, 0.10], role: 'ball' },
        { bone: 'mixamorig:LeftToeBase', pos: [0, -0.015, 0.14], role: 'toe' },
      ],
      right: [],
    },
  }

  /** the rig of the docstring; `withShoe` false = body only */
  const rig = (withShoe = true) => {
    const root = new THREE.Group()
    const foot = new THREE.Bone(); foot.name = 'mixamorigLeftFoot'; foot.position.set(0, 0.08, 0)
    const toe = new THREE.Bone(); toe.name = 'mixamorigLeftToeBase'; toe.position.set(0, -0.06, 0.13)
    foot.add(toe)
    root.add(foot)
    const skinned = (positions) => {
      const n = positions.length / 3
      const geo = new THREE.BufferGeometry()
      geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
      geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Array(n * 4).fill(0), 4))
      geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(Array.from({ length: n * 4 }, (_, i) => (i % 4 === 0 ? 1 : 0)), 4))
      return new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
    }
    const body = skinned([0.05, 0, 0.05, -0.05, 0, -0.05, 0, 0.30, 0])
    root.add(body)
    let shoeMesh = null
    if (withShoe) {
      const shoe = new THREE.Group(); shoe.name = 'garment_footwear_i_left'
      shoe.userData.garment = { kind: 'footwear', item_id: 'i', fsig: 'abc', side: 'left' }
      shoeMesh = skinned([0, -0.02, -0.05, 0, -0.02, 0.10, 0, 0.05, 0.10])
      shoe.add(shoeMesh)
      root.add(shoe)
    }
    root.updateMatrixWorld(true)
    const skeleton = new THREE.Skeleton([foot, toe])
    body.bind(skeleton)
    if (shoeMesh) shoeMesh.bind(skeleton)
    return root
  }
  const ID = [0, 0, 0, 1]
  const qx = (deg) => { const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), deg * Math.PI / 180); return [q.x, q.y, q.z, q.w] }
  const footQ = (times, values) => new THREE.QuaternionKeyframeTrack('mixamorigLeftFoot.quaternion', times, values)
  const still = () => new THREE.AnimationClip('still', 1, [footQ([0], ID)])
  const raised = () => new THREE.AnimationClip('raised', 1, [footQ([0], ID),
    new THREE.VectorKeyframeTrack('mixamorigLeftFoot.position', [0], [0, 0.13, 0])])
  const sweep = () => new THREE.AnimationClip('sweep', 1, [footQ([0, 1], [...ID, ...qx(-20)])])
  const tiptoe = () => new THREE.AnimationClip('heel-down', 1, [footQ([0], qx(-20))])

  console.log('--- [1] the pure rules ---')
  check('groundOffsetOf(0.30, 0) = 0.30', near(groundOffsetOf(0.30, 0), 0.30, 1e-12))
  check('groundOffsetOf(0, 0) = 0', groundOffsetOf(0, 0) === 0)
  check('groundOffsetOf(−0.05, 0) = 0 (never a raise)', groundOffsetOf(-0.05, 0) === 0)
  check('groundOffsetOf(0.30, 0.10) = 0.20', near(groundOffsetOf(0.30, 0.10), 0.20, 1e-12))
  check('groundOffsetOf(0.05, 0.30) = 0', groundOffsetOf(0.05, 0.30) === 0)
  check('groundOffsetOf(NaN, 0) / (0.3, NaN) / (Infinity, 0) = 0',
    groundOffsetOf(NaN, 0) === 0 && groundOffsetOf(0.3, NaN) === 0 && groundOffsetOf(Infinity, 0) === 0)
  check('soleGroundOffsetOf(−0.02, 0) = −0.02 (a raise)', near(soleGroundOffsetOf(-0.02, 0), -0.02, 1e-12))
  check('soleGroundOffsetOf(0.03, 0.01) = 0.02', near(soleGroundOffsetOf(0.03, 0.01), 0.02, 1e-12))
  check('soleGroundOffsetOf(NaN, 0) / (0.3, NaN) / (Infinity, 0) = 0',
    soleGroundOffsetOf(NaN, 0) === 0 && soleGroundOffsetOf(0.3, NaN) === 0 && soleGroundOffsetOf(Infinity, 0) === 0)
  check('SOLE_LEVEL_M = 0.01', SOLE_LEVEL_M === 0.01)

  console.log('--- [2] the anchor excludes the garment ---')
  const probe2 = rig()
  check('figureBox min.y = 0', near(figureBox(THREE, probe2).min.y, 0, 1e-9), String(figureBox(THREE, probe2).min.y))
  check('Box3.setFromObject min.y = −0.02 (the shoe in bind)',
    near(new THREE.Box3().setFromObject(probe2).min.y, -0.02, 1e-9))

  console.log('--- [3] the bare rule ---')
  const c3 = still()
  measureClipGround(THREE, [c3], rig())
  check('identity clip: the shoe mesh is sampled, −0.02 → never a raise → 0', clipGroundOffset(c3) === 0, String(clipGroundOffset(c3)))
  const c3b = raised()
  measureClipGround(THREE, [c3b], rig())
  check('foot 5 cm higher: lowest 0.03 → offset 0.03', near(clipGroundOffset(c3b), 0.03), String(clipGroundOffset(c3b)))

  console.log('--- [4] the shod rule, level ---')
  const c4 = still()
  measureClipGround(THREE, [c4], rig(), { footPose: fp, rootY: 0.052 })
  check('identity clip, rootY 0.052 → 0.032', near(clipGroundOffset(c4), 0.032), String(clipGroundOffset(c4)))
  const c4b = raised()
  measureClipGround(THREE, [c4b], rig(), { footPose: fp })
  check('foot 5 cm higher, rootY 0 → 0.03', near(clipGroundOffset(c4b), 0.03), String(clipGroundOffset(c4b)))
  const c4c = raised()
  measureClipGround(THREE, [c4c], rig(), { footPose: fp, rootY: 0.052 })
  check('… rootY 0.052 → 0.082', near(clipGroundOffset(c4c), 0.082), String(clipGroundOffset(c4c)))

  console.log('--- [5] the shod rule on a sweep: stance = the level frames ---')
  const c5 = sweep()
  measureClipGround(THREE, [c5], rig(), { footPose: fp })
  check('sweep, rootY 0 → −0.0227381 (the heel at f = 4, not the heel strike)',
    near(clipGroundOffset(c5), -0.0227381), String(clipGroundOffset(c5)))
  const c5b = sweep()
  measureClipGround(THREE, [c5b], rig(), { footPose: fp, rootY: 0.03 })
  check('sweep, rootY 0.03 → 0.0072619', near(clipGroundOffset(c5b), 0.0072619), String(clipGroundOffset(c5b)))

  console.log('--- [6] no level frame → all frames ---')
  const c6 = tiptoe()
  measureClipGround(THREE, [c6], rig(), { footPose: fp })
  check('heel-down clip → −0.0310703', near(clipGroundOffset(c6), -0.0310703), String(clipGroundOffset(c6)))

  console.log('--- [7] a foot pose that does not match → the bare rule ---')
  const c7 = sweep()
  measureClipGround(THREE, [c7], rig(), { footPose: { ...fp, source: { ...fp.source, fsig: 'zzz' } } })
  check('sweep under the bare rule → 0', clipGroundOffset(c7) === 0, String(clipGroundOffset(c7)))

  console.log('--- [8] edges ---')
  const c8 = still()
  measureClipGround(THREE, [c8], new THREE.Group(), { footPose: fp })
  check('no skinned mesh → nothing stored', c8.userData.groundOffset === undefined && clipGroundOffset(c8) === 0)
  const c8a = still(); const c8b = sweep()
  measureClipGround(THREE, [c8a, c8b], rig(), { footPose: fp, rootY: 0.052 })
  check('two clips: 0.032 and 0.0292619', near(clipGroundOffset(c8a), 0.032) && near(clipGroundOffset(c8b), 0.0292619),
    `${clipGroundOffset(c8a)} ${clipGroundOffset(c8b)}`)
  const c8c = still(); c8c.userData.groundOffset = 'x'
  check('non-numeric → 0', clipGroundOffset(c8c) === 0)
  check('never measured → 0', clipGroundOffset(still()) === 0)

  if (failures.length) {
    console.log(`\nFAIL: ${failures.length} check(s) failed`)
    process.exit(1)
  }
  console.log('\nOK: clip ground — bare rule, shod rule on the sole, stance by level frames')
}

main().catch((err) => { console.error(err); process.exit(1) })
