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
 * throws away whatever the target rig holds in its own bind pose. Measured at
 * the consumer on `idle.fbx`, as the DEFORMATION the skin undergoes
 * (`W_bone(t)·W_bone(bind)⁻¹`, YXZ yaw of the left foot):
 *
 *      rig (own toe-out per side)      1:1        bind-relative
 *      reference.fbx  (0°)            −0.6°          −0.6°
 *      Thalion        (2.6°)          +2.8°          −0.4°
 *      Kahiro        (16.6°)         −10.4°          −0.6°
 *      Gorvoth       (18.4°)         −11.1°          −1.0°
 *
 * The 1:1 spread of 13.9° IS the reported bug — a character whose T-pose
 * stands with its feet splayed had that splay taken away by every clip, which
 * reads as the feet turning inwards. Bind-relative brings all four rigs to
 * within 0.6° of each other, and the number they agree on is the reference
 * rig's own, i.e. the actor's motion.
 *
 * ---------------------------------------------------------------------------
 * THE RULE, hand-derived
 * ---------------------------------------------------------------------------
 * Local quaternions: `d` donor rest, `c` clip value, `t` target rest, `q` the
 * value to drive the target with. Skinning shows `M = W(t)·W(bind)⁻¹`; with
 * the parent at `W_p`
 *
 *      M_d = W_p·c·d⁻¹·W_p⁻¹        M_t = W_p·q·t⁻¹·W_p⁻¹
 *
 * and `M_t = M_d` gives `q·t⁻¹ = c·d⁻¹`, i.e.
 *
 *      q = c · d⁻¹ · t = c · k      k = d⁻¹ · t   (constant per bone)
 *
 * The cases below check exactly that, on rotations chosen so every expected
 * value can be written down by hand.
 *
 * [1] k is d⁻¹·t. d = Ry(30°), t = Ry(50°)  ->  k = Ry(20°).
 * [2] IDENTITY: t = d  ->  k is the identity, `restCorrections` reports the
 *     bone NOT AT ALL, and `bindRelativeValues` answers null so the caller
 *     keeps its array. That is what makes "target == reference rig" exact
 *     rather than merely close.
 * [3] THE DEFORMATION CANCELS. With d = Ry(30°), t = Ry(50°), c = Ry(30°+A):
 *     q = c·k = Ry(30+A)·Ry(20) = Ry(50+A), so q·t⁻¹ = Ry(A) = c·d⁻¹. The
 *     target is deformed by A, exactly like the donor — and it starts from
 *     ITS OWN rest, so at A = 0 it sits at Ry(50°), not at the donor's 30°.
 * [4] RED COUNTER-PROBE, the other order. `k·c` = Ry(20)·Ry(30+A) is the same
 *     here because rotations about ONE axis commute — so the probe uses two
 *     AXES: d = Rx(40°), t = Ry(50°)·d, c = d (the rest frame of the clip).
 *     Right order: q = c·k = d·d⁻¹·t = t, the target sits at its own rest,
 *     deformation identity. Wrong order: q = k·c = d⁻¹·t·d, whose deformation
 *     q·t⁻¹ = d⁻¹·t·d·t⁻¹ is NOT the identity — measured below, 33.2°. A
 *     figure at rest would be bent.
 * [5] bindRelativeClip touches quaternion tracks only; a position track (the
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
  /** rotation angle of a quaternion, degrees */
  const ang = (q) => 2 * Math.acos(Math.min(1, Math.abs(q.w))) * DEG
  const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps

  /** A one-bone skeleton whose rest local quaternion is `q`. */
  const rig = (q) => {
    const bone = new THREE.Bone()
    bone.name = 'mixamorig:LeftFoot'
    bone.quaternion.copy(q)
    const root = new THREE.Object3D()
    root.add(bone)
    return root
  }

  console.log('[1] k = d⁻¹ · t')
  const donor = restPoseOf(THREE, rig(RY(30)))
  check('restPoseOf reads the rest, normalised name', donor.has('leftfoot'),
    `keys ${[...donor.keys()].join(',')}`)
  let corr = restCorrections(THREE, donor, rig(RY(50)))
  check('d = Ry(30°), t = Ry(50°) → k = Ry(20°)',
    corr.has('leftfoot') && near(ang(corr.get('leftfoot')), 20, 1e-4),
    `${ang(corr.get('leftfoot')).toFixed(4)}°`)

  console.log('\n[2] the identity case is EXACT, not close')
  corr = restCorrections(THREE, donor, rig(RY(30)))
  check('t = d → the bone is not reported at all', corr.size === 0,
    `${corr.size} corrections`)
  check('and bindRelativeValues answers null, so the caller keeps its array',
    bindRelativeValues(THREE, new Float32Array(8), corr.get('leftfoot')) === null)
  corr = restCorrections(THREE, donor, rig(RY(30.04)))
  check('a 0.04° difference stays under the threshold', corr.size === 0)
  corr = restCorrections(THREE, donor, rig(RY(30.2)))
  check('a 0.2° difference is corrected', corr.size === 1)

  console.log('\n[3] the deformation cancels: q·t⁻¹ = c·d⁻¹')
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
  const c2 = d2.clone()                       // the clip sits at the donor rest
  const right = c2.clone().multiply(k2)       // q = c · k
  const wrong = k2.clone().multiply(c2)       // q = k · c
  check('right order: a clip at the donor rest leaves the target at ITS rest',
    near(right.angleTo(t2), 0, 1e-6), `${(right.angleTo(t2) * DEG).toFixed(6)}° off`)
  const wrongDeform = wrong.clone().multiply(t2.clone().invert())
  check('wrong order bends the figure at rest instead',
    ang(wrongDeform) > 10,
    `deformation ${ang(wrongDeform).toFixed(1)}° instead of 0°`)

  console.log('\n[5] bindRelativeClip — quaternion tracks only')
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
