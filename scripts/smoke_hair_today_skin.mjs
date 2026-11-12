#!/usr/bin/env node
/**
 * Hair chains swing on top of today's skin (Ruling H11; `MotionGroup.anchor_blend` / `anchor_from`, HAIR CHAINS
 * in packages/scene-render/src/secondaryMotion.ts). Hand-derived.
 *
 * Usage: node scripts/smoke_hair_today_skin.mjs   (no server, no world; bundles itself with esbuild)
 *
 * FIXTURE (metres, every bind rotation identity, one skin over all bones, one vertex weighted 1 per hair joint):
 *   Hips (0,0,0) → Spine2 S (0,1.3,0) → Head H (0,1.6,0) → HairGen_c00_00 J0 (0,1.7,−0.07)
 *   → HairGen_c00_01 J1 (0,1.6,−0.07) → HairGen_c00_02 J2 (0,1.5,−0.07). The group's bones are _00 and _01; _02
 *   is a carried joint (rigid server-side: only its row is sent).
 *   POSE: Spine2 pitched +30° about +X, Head −40° about +X relative to Spine2. A body joint X moves the tissue by
 *   D_X = X now · X bind⁻¹: D_Spine2 turns p about S by 30°; D_Head turns p about H by −40°, then about S by 30°.
 *   Rotation about +X by a about pivot c: y' = c_y + dy cos a − dz sin a, z' = c_z + dy sin a + dz cos a.
 *     D_Head(J0)   = (0, 1.64613, 0.06370)
 *     D_Head(J1)   = (0, 1.54765, 0.08106)   D_Spine2(J1) = (0, 1.59481, 0.08938)   half/half (0, 1.57123, 0.08522)
 *     D_Head(J2)   = (0, 1.44917, 0.09843)   D_Spine2(J2) = (0, 1.50821, 0.03938)   half/half (0, 1.47869, 0.06890)
 *   (e.g. D_Spine2(J1): dy 0.3, dz −0.07 → y 1.3 + 0.3·0.86603 + 0.07·0.5 = 1.59481, z 0.3·0.5 − 0.07·0.86603
 *   = 0.08938.)
 *
 * [1] ZERO SWING = TODAY'S SKIN. Budgets 0 (max_deg, sag_max_deg, gravity, gain), rows _00 {Head 1},
 *     _01 {Head 0.5, Spine2 0.5}, _02 {Spine2 1}, anchor_from Head: after one update in the pose every joint is at
 *     its row's blend of the D's applied to its bind position — _00 at D_Head(J0), _01 at the half/half point,
 *     _02 (carried) at D_Spine2(J2) — within 1e-5 m; the vertex on _01 (bind J1) is skinned to the same point.
 * [2] THE SWING IS THE HEAD SHARE. Hair motion constants (max 35°, sag 10°, gain 1, zeta 0.5, 1 Hz, gravity 0), the
 *     spine at rest, the head pitching to −40° over 0.25 s, 60 fps, 1.5 s. Rows _00 {Head 1} (share 1),
 *     _01 {Spine2 1} (share 0): _01 stays at D_Spine2(J1) = J1 in every frame (|Δ| < 1e-6 m, its swing scaled by
 *     0), while _00's tip — its world applied to the bone-local offset (0, −0.1, 0) of J1 — leaves the place
 *     D_Head(J1) where the head carries it by > 5 mm in some frame (the head share swings in full).
 * [3] A ROWS-ONLY GROUP. A payload with only {hair_c00: bones [], anchor_blend {_02: {Head 0.5, Spine2 0.5}}}
 *     activates the motion (`_02` counts as a group bone) and puts the carried joint _02 at the half/half point
 *     of J2 in the pose of [1], within 1e-5 m.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'

if (!process.env.HAIR_TODAY_BUNDLED) {
  const here = fileURLToPath(import.meta.url)
  const repo = path.resolve(path.dirname(here), '..')
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild']
    .map(rel => path.join(repo, rel)).find(existsSync)
  assert.ok(bin, 'esbuild unavailable (npm install) — nothing was checked')
  const built = spawnSync(bin, [here, '--bundle', '--platform=node', '--format=esm', '--outfile=/tmp/smoke_hair_today_skin.mjs',
    '--log-level=error'], { stdio: 'inherit', env: { ...process.env, NODE_PATH: path.join(repo, 'node_modules') } })
  assert.equal(built.status, 0)
  const run = spawnSync('node', ['/tmp/smoke_hair_today_skin.mjs'], { stdio: 'inherit', env: { ...process.env, HAIR_TODAY_BUNDLED: '1' } })
  process.exit(run.status ?? 1)
}
const THREE = await import('three')
const { createSecondaryMotion } = await import('../packages/scene-render/src/secondaryMotion.ts')

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
const hairGroup = { freq_hz: 1, zeta: 0.5, gravity: 0, gravity_scale: 1, gain: 1,
  max_deg: 35, sag_max_deg: 10, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0.5, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90, rigid_tail: 0, scale_axis: 'centroid',
  straighten_deg: 0, freetext_clothing_gain: 1, hair: true, anchor_from: 'mixamorig:Head' }
const still = { max_deg: 0, sag_max_deg: 0, gravity: 0, gain: 0 }
const X = new THREE.Vector3(1, 0, 0)
const v = (y, z) => new THREE.Vector3(0, y, z)

function rig() {
  const root = new THREE.Group()
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = name; b.position.set(...at); (parent ?? root).add(b); return b
  }
  const hips = bone('mixamorig:Hips', null, [0, 0, 0])
  const spine = bone('mixamorig:Spine2', hips, [0, 1.3, 0])
  const head = bone('mixamorig:Head', spine, [0, 0.3, 0])
  const c0 = bone('HairGen_c00_00', head, [0, 0.1, -0.07])
  const c1 = bone('HairGen_c00_01', c0, [0, -0.1, 0])
  const c2 = bone('HairGen_c00_02', c1, [0, -0.1, 0])
  const geo = new THREE.BufferGeometry()
  // one vertex 0.05 below each hair joint, and one AT J1 for [1]'s skin check
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 1.65, -0.07, 0, 1.55, -0.07, 0, 1.45, -0.07, 0, 1.6, -0.07], 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([3, 0, 0, 0, 4, 0, 0, 0, 5, 0, 0, 0, 4, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([hips, spine, head, c0, c1, c2]))
  return { root, spine, head, c0, c1, c2, mesh }
}
const at = (bone) => new THREE.Vector3().setFromMatrixPosition(bone.matrixWorld)
const off = (p, y, z) => Math.hypot(p.y - y, p.z - z, p.x)
const pose = (f) => {
  f.spine.quaternion.setFromAxisAngle(X, 30 * Math.PI / 180)
  f.head.quaternion.setFromAxisAngle(X, -40 * Math.PI / 180)
  f.root.updateMatrixWorld(true)
}

console.log('--- [1] zero swing = today\'s skin ---')
{
  const f = rig()
  const group = { ...hairGroup, ...still, bones: ['HairGen_c00_00', 'HairGen_c00_01'],
    anchor_blend: { HairGen_c00_00: { 'mixamorig:Head': 1 }, HairGen_c00_01: { 'mixamorig:Head': 0.5, 'mixamorig:Spine2': 0.5 },
      HairGen_c00_02: { 'mixamorig:Spine2': 1 } } }
  const motion = createSecondaryMotion(THREE, f.root, { rev: 'fixture', groups: { hair_c00: group } })
  pose(f)
  motion.update(1 / 60)
  const p0 = at(f.c0), p1 = at(f.c1), p2 = at(f.c2)
  check('_00 at D_Head(J0) (0, 1.64613, 0.06370)', off(p0, 1.64613, 0.06370) < 1e-5, `${p0.y.toFixed(5)} ${p0.z.toFixed(5)}`)
  check('_01 at the half/half point (0, 1.57123, 0.08522)', off(p1, 1.57123, 0.08522) < 1e-5, `${p1.y.toFixed(5)} ${p1.z.toFixed(5)}`)
  check('carried _02 at D_Spine2(J2) (0, 1.50821, 0.03938)', off(p2, 1.50821, 0.03938) < 1e-5, `${p2.y.toFixed(5)} ${p2.z.toFixed(5)}`)
  f.mesh.skeleton.update()
  const skinned = f.mesh.applyBoneTransform(3, new THREE.Vector3().fromBufferAttribute(f.mesh.geometry.attributes.position, 3))
    .applyMatrix4(f.mesh.matrixWorld)
  check('the vertex at J1 is skinned to the half/half point', off(skinned, 1.57123, 0.08522) < 1e-5,
    `${skinned.y.toFixed(5)} ${skinned.z.toFixed(5)}`)
  motion.dispose()
}

console.log('--- [2] the swing is the head share ---')
{
  const f = rig()
  const group = { ...hairGroup, bones: ['HairGen_c00_00', 'HairGen_c00_01'],
    anchor_blend: { HairGen_c00_00: { 'mixamorig:Head': 1 }, HairGen_c00_01: { 'mixamorig:Spine2': 1 } } }
  const motion = createSecondaryMotion(THREE, f.root, { rev: 'fixture', groups: { hair_c00: group } })
  const dt = 1 / 60
  let still1 = 0, swing0 = 0
  for (let frame = 1; frame <= 90; frame++) {
    f.head.quaternion.setFromAxisAngle(X, -Math.min(1, frame * dt / 0.25) * 40 * Math.PI / 180)
    f.root.updateMatrixWorld(true)
    motion.update(dt)
    still1 = Math.max(still1, off(at(f.c1), 1.6, -0.07))
    const tip = new THREE.Vector3(0, -0.1, 0).applyMatrix4(f.c0.matrixWorld)
    const carried = v(1.6, -0.07).sub(v(1.6, 0)).applyQuaternion(f.head.quaternion).add(v(1.6, 0))
    swing0 = Math.max(swing0, tip.distanceTo(carried))
  }
  check('_01 (row Spine2 1, share 0) stays at J1 in every frame', still1 < 1e-6, `${(still1 * 1000).toFixed(6)} mm`)
  check('_00 (row Head 1, share 1) swings: its tip leaves the head-carried place by > 5 mm', swing0 > 0.005,
    `${(swing0 * 1000).toFixed(2)} mm`)
  motion.dispose()
}

console.log('--- [3] a rows-only group ---')
{
  const f = rig()
  const group = { ...hairGroup, ...still, bones: [],
    anchor_blend: { HairGen_c00_02: { 'mixamorig:Head': 0.5, 'mixamorig:Spine2': 0.5 } } }
  const motion = createSecondaryMotion(THREE, f.root, { rev: 'fixture', groups: { hair_c00: group } })
  pose(f)
  motion.update(1 / 60)
  const p2 = at(f.c2)
  check('carried _02 at the half/half point (0, 1.47869, 0.06890)', off(p2, 1.47869, 0.06890) < 1e-5,
    `${p2.y.toFixed(5)} ${p2.z.toFixed(5)}`)
  motion.dispose()
}

console.log(failures ? `FAILED: ${failures}` : 'ALL OK')
process.exit(failures ? 1 : 0)
