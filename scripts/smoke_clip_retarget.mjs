#!/usr/bin/env node
/**
 * Smoke check for the shared BIND-RELATIVE CLIP TRANSPLANT —
 * `packages/scene-render/src/clipRetarget.ts`, the ONE routine both renderers
 * bind a library clip with (`client3d`'s `adaptExternalClips` and the admin's
 * `Model3DViewer`). Numbers, not screenshots (§ B5a).
 *
 * Usage: node scripts/smoke_clip_retarget.mjs
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * Until 2026-08-31 both renderers copied the library's LOCAL quaternion
 * tracks 1:1. That sets every bone to the DONOR rig's orientation and so
 * throws away whatever the target rig holds in its own bind pose — the mesh
 * is skinned to that bind, so each limb is twisted around its own axis by the
 * difference of the two bone frames (measured over 20 generated characters on
 * `idle.fbx`: mean 30.4° across the arm bones, 166° at worst).
 *
 * The fix of 2026-08-31 was ONE factor from LOCAL rests, `q = c·d⁻¹·t`. Its
 * derivation held the parent "at its bind orientation" and thereby assumed
 * the two rigs' parent frames agree — they do not. Worse, a LOCAL rest is not
 * a geometric property of a bone at all: it records how a rigger split the
 * orientation across the chain, so two skeletons with the SAME world rest can
 * hold very different local ones. Measured at the consumer, mean over the six
 * arm axes against the posed reference skeleton:
 *
 *      rig                     1:1 copy   local one-factor   world two-factor
 *      figure/x-bot.fbx           0.0°           9.3°              3.0°
 *      20 generated characters    1.4°          15.9°              8.6°
 *
 * The middle column is worse than doing nothing on the figure that matches
 * the library best, and it is the only one of the three whose error depends
 * on the CLIP. Since 2026-09-03 the rule is the two-factor form below; what
 * it leaves is the character's OWN bind deviation and nothing else — over 20
 * characters × 3 clips × 4 sample times the posed deviation equals the REST
 * deviation to 0.000° and the deformation error is 0.00°.
 *
 * ---------------------------------------------------------------------------
 * THE RULE, hand-derived
 * ---------------------------------------------------------------------------
 * `R_b` is a bone's REST orientation in WORLD space (the product of the local
 * rest rotations from the root down to `b`), `W_b(t)` its animated world
 * orientation, `c_b` the clip's local value, `q_b` what the target is driven
 * with. Skinning shows `M_b = W_b(t)·R_b⁻¹`, and "the same motion on this
 * body" is `M_t,b = M_d,b`, so
 *
 *      W_t,b = W_d,b · K_b        K_b = R_d,b⁻¹ · R_t,b
 *
 * With `W_t,b = W_t,p·q_b` and the same relation at the parent
 * (`W_t,p⁻¹·W_d,p = K_p⁻¹`):
 *
 *      q_b = K_p⁻¹ · c_b · K_b
 *
 * The cases below check exactly that, on rotations chosen so every expected
 * value can be written down by hand.
 *
 * [1] ONE BONE under an unrotated root: the parent factor is the identity and
 *     the rule falls back to the single factor. R_d = Ry(30°), R_t = Ry(50°)
 *     -> K = Ry(20°).
 * [2] IDENTITY: R_t = R_d -> both factors are the identity, `restCorrections`
 *     reports the bone NOT AT ALL, and `bindRelativeValues` answers null so
 *     the caller keeps its array. That is what makes "target == reference rig"
 *     exact rather than merely close.
 * [3] THE DEFORMATION CANCELS. With R_d = Ry(30), R_t = Ry(50), c = Ry(30+A):
 *     q = c·K = Ry(30+A)·Ry(20) = Ry(50+A), so q·R_t⁻¹ = Ry(A) = c·R_d⁻¹. The
 *     target is deformed by A, exactly like the donor — and it starts from
 *     ITS OWN rest, so at A = 0 it sits at Ry(50°), not at the donor's 30°.
 * [4] RED COUNTER-PROBE, the other order. `K·c` = Ry(20)·Ry(30+A) is the same
 *     in [3] because rotations about ONE axis commute — so the probe uses two
 *     AXES: R_d = Rx(40°), R_t = Ry(50°)·R_d, c = R_d (the clip at rest).
 *     Right order: q = c·K = R_d·R_d⁻¹·R_t = R_t, the target sits at its own
 *     rest, deformation identity. Wrong order: q = K·c, deformation
 *     R_d⁻¹·Ry(50)·R_d·Ry(-50) — 40° about x̂ against 40° about Ry(50)·x̂, so
 *     cos(Ψ/2) = cos²20° + sin²20°·cos50° = 0.958215, Ψ = 33.2°. A figure at
 *     rest would be bent.
 * [5] THE CHAIN — what the local one-factor form gets wrong. Parent P and
 *     child C, donor both at the identity, target P = Ry(20°) and
 *     C = Ry(-20°). The two rigs' WORLD rest at C is therefore the SAME
 *     (Ry(20)·Ry(-20) = 1) while the LOCAL rests differ by 20°.
 *       - world rule: K_C = 1, K_P = Ry(20) -> q_C = Ry(-20)·c_C. With
 *         c_P = 1 and c_C = Rx(40°) the target's world C is
 *         Ry(20)·Ry(-20)·Rx(40) = Rx(40) = the donor's, deformation 0.
 *       - local rule: k_C = Ry(-20) applied on the RIGHT while the parent is
 *         driven to Ry(20) leaves Ry(20)·Rx(40)·Ry(-20) — 40° about x̂ against
 *         40° about Ry(20)·x̂, so cos(Ψ/2) = cos²20° + sin²20°·cos20° =
 *         0.992946 and Ψ = 13.62° of deformation out of nowhere.
 * [6] THE ROOT FRAME. Rests are compared as `R̃ = R_root⁻¹·R`, so a rig's
 *     global attitude divides out. Donor hips and spine at the identity,
 *     target hips at Ry(15°) with the spine at the identity below it: the
 *     WHOLE figure is turned 15°, `R̃` is the identity on both bones, and
 *     NOTHING is corrected — the clip plays verbatim and the figure stands
 *     the way the clip stands. Turn only the pelvis instead (hips Ry(15°),
 *     spine Ry(-15°), so the torso is upright and the pelvis is not) and the
 *     spine IS corrected, by Ry(-15°): that difference is a body feature and
 *     is kept. The deformation of BOTH bones in the first case is the same
 *     constant `G = R_d,root·R_t,root⁻¹` = Ry(-15°) — a rigid rotation of the
 *     character, which is what "stood upright as a piece" means. With the
 *     armature rotated (target root object at Rx(90°)) only the root bone is
 *     corrected, left = Rx(-90°) = A_t⁻¹ — the client's `hipsRotFix`.
 *
 *     Every rig below hangs under a `Hips` root bone for this reason: a lone
 *     bone WOULD be the root, and its own rest would divide itself out.
 * [7] bindRelativeClip touches quaternion tracks only; a position track (the
 *     hips height) passes through unchanged, and a clip with nothing to
 *     correct is returned as the SAME object.
 *     TOLERANCE: three stores every keyframe track in a Float32Array, so a
 *     transplanted value comes back rounded. Component eps 1.2e-7 makes the
 *     dot product miss 1 by ~2e-8, and `angleTo` = 2·acos(dot) amplifies that
 *     to 2·sqrt(2·2e-8) ≈ 4e-4 rad ≈ 0.023°. The check allows 0.05°. The
 *     UNCORRECTED case has no such error at all — the original array is kept
 *     rather than rewritten, which is what makes case [2] exact.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_clip_retarget_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm',
      `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root,
    })
    process.exit(run.status ?? 1)
  }

  const { restPoseOf, restCorrections, bindRelativeValues, bindRelativeClip } =
    await import('../packages/scene-render/src/clipRetarget.ts')
  const THREE = await import('three')

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const DEG = 180 / Math.PI
  const rad = (d) => (d * Math.PI) / 180
  const qAxis = (axis, deg) =>
    new THREE.Quaternion().setFromAxisAngle(axis, rad(deg))
  const RY = (deg) => qAxis(new THREE.Vector3(0, 1, 0), deg)
  const RX = (deg) => qAxis(new THREE.Vector3(1, 0, 0), deg)
  const ID = () => new THREE.Quaternion()
  /** rotation angle of a quaternion, degrees */
  const ang = (q) => 2 * Math.acos(Math.min(1, Math.abs(q.w))) * DEG
  const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps
  /** q = left · c · right, the rule under test, spelled out */
  const drive = (k, c) => c.clone().premultiply(k.left).multiply(k.right)

  const bone = (name, q) => {
    const b = new THREE.Bone()
    b.name = name
    b.quaternion.copy(q)
    return b
  }
  /** `mixamorig:Hips` (the ROOT bone, always at the identity here) carrying the
   *  chain `qs`, under a root object holding `rootQ` (the armature frame). */
  const skeleton = (qs, rootQ = ID(), hipsQ = ID()) => {
    const root = new THREE.Object3D()
    root.quaternion.copy(rootQ)
    const hips = bone('mixamorig:Hips', hipsQ)
    root.add(hips)
    let tip = hips
    for (const [name, q] of qs) {
      const b = bone(name, q)
      tip.add(b)
      tip = b
    }
    return root
  }
  /** One bone BELOW the root, so the transplant applies to it. */
  const rig = (q) => skeleton([['mixamorig:LeftFoot', q]])
  /** Shoulder `p` with child arm `c`, below the root. */
  const chain = (p, c) =>
    skeleton([['mixamorig:LeftShoulder', p], ['mixamorig:LeftArm', c]])

  console.log('[1] K = R_d⁻¹ · R_t, one bone under an unrotated root')
  const donor = restPoseOf(THREE, rig(RY(30)))
  check('restPoseOf reads the rest, normalised name', donor.world.has('leftfoot'),
    `keys ${[...donor.world.keys()].join(',')}`)
  let corr = restCorrections(THREE, donor, rig(RY(50)))
  check('R_d = Ry(30°), R_t = Ry(50°) → K = Ry(20°)',
    corr.has('leftfoot') && near(ang(corr.get('leftfoot').right), 20, 1e-4),
    `${ang(corr.get('leftfoot').right).toFixed(4)}°`)
  check('and the parent factor is the identity',
    near(ang(corr.get('leftfoot').left), 0, 1e-4),
    `${ang(corr.get('leftfoot').left).toFixed(4)}°`)

  console.log('\n[2] the identity case is EXACT, not close')
  corr = restCorrections(THREE, donor, rig(RY(30)))
  check('R_t = R_d → the bone is not reported at all', corr.size === 0,
    `${corr.size} corrections`)
  check('and bindRelativeValues answers null, so the caller keeps its array',
    bindRelativeValues(THREE, new Float32Array(8), corr.get('leftfoot')) === null)
  corr = restCorrections(THREE, donor, rig(RY(30.04)))
  check('a 0.04° difference stays under the threshold', corr.size === 0)
  corr = restCorrections(THREE, donor, rig(RY(30.2)))
  check('a 0.2° difference is corrected', corr.size === 1)

  console.log('\n[3] the deformation cancels: q·R_t⁻¹ = c·R_d⁻¹')
  const d = RY(30), t = RY(50)
  const k = restCorrections(THREE, restPoseOf(THREE, rig(d)), rig(t)).get('leftfoot')
  for (const A of [0, 17, -35]) {
    const c = RY(30 + A)
    const vals = bindRelativeValues(THREE, [c.x, c.y, c.z, c.w], k)
    const q = new THREE.Quaternion(vals[0], vals[1], vals[2], vals[3])
    const deform = q.clone().multiply(t.clone().invert())
    const donorDeform = c.clone().multiply(d.clone().invert())
    check(`A = ${A}°: q = Ry(${50 + A}°)`, near(q.angleTo(RY(50 + A)), 0, 1e-6),
      `${(q.angleTo(RY(50 + A)) * DEG).toFixed(6)}° off`)
    check(`A = ${A}°: the target deforms exactly like the donor`,
      near(deform.angleTo(donorDeform), 0, 1e-6),
      `${(deform.angleTo(donorDeform) * DEG).toFixed(6)}° off`)
  }

  console.log('\n[4] RED COUNTER-PROBE — the other multiplication order')
  const d2 = RX(40), t2 = RY(50).clone().multiply(d2)
  const k2 = restCorrections(THREE, restPoseOf(THREE, rig(d2)), rig(t2)).get('leftfoot')
  const c2 = d2.clone()                            // the clip sits at the donor rest
  const right = drive(k2, c2)                      // q = c · K
  const wrong = k2.right.clone().multiply(c2)      // q = K · c
  check('right order: a clip at the donor rest leaves the target at ITS rest',
    near(right.angleTo(t2), 0, 1e-6), `${(right.angleTo(t2) * DEG).toFixed(6)}° off`)
  const wrongDeform = wrong.clone().multiply(t2.clone().invert())
  check('wrong order bends the figure at rest instead — 33.2° by hand',
    Math.abs(ang(wrongDeform) - 33.2) < 0.05,
    `deformation ${ang(wrongDeform).toFixed(2)}° instead of 0°`)

  console.log('\n[5] THE CHAIN — the parent factor is what the local rule lacks')
  // donor: both bones at the identity. target: Ry(20°) over Ry(-20°), so the
  // child's WORLD rest agrees with the donor's while its LOCAL rest is 20° off.
  const donorChain = restPoseOf(THREE, chain(ID(), ID()))
  const targetChain = chain(RY(20), RY(-20))
  const cc = restCorrections(THREE, donorChain, targetChain)
  const kP = cc.get('leftshoulder'), kC = cc.get('leftarm')
  check('the child\'s own factor is the identity — the world rests agree',
    near(ang(kC.right), 0, 1e-4), `${ang(kC.right).toFixed(4)}°`)
  check('its LEFT factor carries the parent\'s 20° instead',
    near(ang(kC.left), 20, 1e-4), `${ang(kC.left).toFixed(4)}°`)
  const cP = ID(), cChild = RX(40)
  const qP = drive(kP, cP), qC = drive(kC, cChild)
  // world orientation of the driven child, and the donor's for comparison
  const worldC = qP.clone().multiply(qC)
  const donorWorldC = cP.clone().multiply(cChild)
  check('the driven child lands on the donor\'s world orientation',
    near(worldC.angleTo(donorWorldC), 0, 1e-6),
    `${(worldC.angleTo(donorWorldC) * DEG).toFixed(6)}° off`)
  // R_t of the child is Ry(20)·Ry(-20) = identity, so deformation == world
  check('deformation 0° — the character keeps its own bind',
    near(ang(worldC.clone().multiply(donorWorldC.clone().invert())), 0, 1e-4),
    `${ang(worldC.clone().multiply(donorWorldC.clone().invert())).toFixed(4)}°`)
  // the SUPERSEDED local rule: q = c · (d⁻¹·t) per bone, no parent factor
  const localK = (dLocal, tLocal) => dLocal.clone().invert().multiply(tLocal)
  const lqP = cP.clone().multiply(localK(ID(), RY(20)))
  const lqC = cChild.clone().multiply(localK(ID(), RY(-20)))
  const localWorld = lqP.clone().multiply(lqC)
  const localErr = ang(localWorld.clone().multiply(donorWorldC.clone().invert()))
  check('the local one-factor rule invents 13.62° here — 33.2° by hand in [4]',
    Math.abs(localErr - 13.62) < 0.05, `${localErr.toFixed(2)}°`)

  console.log('\n[6] the ROOT FRAME — a global attitude divides out')
  const spine = [['mixamorig:Spine', ID()]]
  const donorSpine = restPoseOf(THREE, skeleton(spine))
  // the WHOLE figure turned 15° at the hips: nothing is a body feature here
  const leaning = skeleton(spine, ID(), RY(15))
  const leaningCorr = restCorrections(THREE, donorSpine, leaning)
  check('a figure leaning as a WHOLE is not corrected at all —'
    + ' it stands the way the clip stands', leaningCorr.size === 0,
    `keys ${[...leaningCorr.keys()].join(',') || '(none)'}`)
  // the deformation both bones then undergo is ONE constant G = Ry(-15°)
  const gOf = (boneRest, driven) => driven.clone().multiply(boneRest.clone().invert())
  const cH = RY(70), cS = RX(25)                    // any clip values
  const defHips = gOf(RY(15), cH)                   // R_t,hips = Ry(15)
  const defSpine = gOf(RY(15), cH.clone().multiply(cS))
  const donorDefHips = gOf(ID(), cH)
  const donorDefSpine = gOf(ID(), cH.clone().multiply(cS))
  const gH = donorDefHips.clone().invert().multiply(defHips)
  const gS = donorDefSpine.clone().invert().multiply(defSpine)
  check('and both bones deform by the SAME constant G = Ry(-15°)',
    near(ang(gH), 15, 1e-4) && near(gH.angleTo(gS), 0, 1e-6),
    `hips ${ang(gH).toFixed(4)}°, spread ${(gH.angleTo(gS) * DEG).toFixed(6)}°`)
  // only the PELVIS turned, torso upright: that IS a body feature
  const kinked = restCorrections(THREE, donorSpine,
    skeleton([['mixamorig:Spine', RY(-15)]], ID(), RY(15)))
  check('a turned pelvis under an upright torso IS kept: spine right = Ry(-15°)',
    near(ang(kinked.get('spine').right), 15, 1e-4),
    `${ang(kinked.get('spine').right).toFixed(4)}°`)
  const tiltedArm = skeleton(spine, RX(90))
  const armCorr = restCorrections(THREE, donorSpine, tiltedArm)
  const kH = armCorr.get('hips')
  const armature = tiltedArm.quaternion.clone()
  check('with a rotated armature ONLY the root is corrected, left = A_t⁻¹ —'
    + ' the client\'s hipsRotFix, generalised',
    armCorr.size === 1 && near(kH.left.angleTo(armature.clone().invert()), 0, 1e-6),
    `${armCorr.size} correction(s),`
    + ` ${(kH.left.angleTo(armature.clone().invert()) * DEG).toFixed(6)}° off`)
  check('so the driven root lands on the DONOR\'s world orientation',
    near(ang(armature.clone().multiply(drive(kH, ID()))), 0, 1e-4),
    `${ang(armature.clone().multiply(drive(kH, ID()))).toFixed(4)}°`)

  console.log('\n[7] bindRelativeClip — quaternion tracks only')
  const times = [0, 1]
  const qt = new THREE.QuaternionKeyframeTrack('mixamorig:LeftFoot.quaternion',
    times, [d.x, d.y, d.z, d.w, d.x, d.y, d.z, d.w])
  const pt = new THREE.VectorKeyframeTrack('mixamorig:Hips.position',
    times, [0, 100, 0, 0, 110, 0])
  const clip = new THREE.AnimationClip('idle', 1, [qt, pt])
  const out = bindRelativeClip(THREE, clip, new Map([['leftfoot', k]]))
  const outQ = out.tracks.find((tr) => tr.name.endsWith('.quaternion'))
  const outP = out.tracks.find((tr) => tr.name.endsWith('.position'))
  const first = new THREE.Quaternion(outQ.values[0], outQ.values[1],
    outQ.values[2], outQ.values[3])
  check('the quaternion track is transplanted',
    first.angleTo(t) * DEG <= 0.05,
    `${(first.angleTo(t) * DEG).toFixed(4)}° off Ry(50°) (float32 track storage)`)
  check('the hips POSITION track passes through untouched',
    outP === pt && outP.values[1] === 100 && outP.values[4] === 110)
  check('nothing to correct → the SAME clip object comes back',
    bindRelativeClip(THREE, clip, new Map()) === clip)

  console.log(failures.length
    ? `\n${failures.length} FAILED: ${failures.join(', ')}`
    : '\nall checks passed')
  process.exit(failures.length ? 1 : 0)
}

main()
