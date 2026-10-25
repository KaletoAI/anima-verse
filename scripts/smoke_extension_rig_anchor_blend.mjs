#!/usr/bin/env node
/** Hand-derived anchor blend check on Root -> S1 -> S2 -> B, all bind rotations identity.
 * S2 sits 1 above S1, B 1 in front of S2 (+Z), so B's bind head is (0,1,1).
 * gravity=gain=0: no force acts, B stays at its rest frame.
 * S2 turns +20 deg about X (S1 still): its delta moves B's head about (0,1,0):
 *   (0,0,1) -> (0,-sin20,cos20), head (0, 1-sin20, cos20) = (0,.65798,.93969).
 * Without a blend B follows its parent S2: that head and a 20 deg turn.
 * With anchor_blend {S1:.5, S2:.5}: head = .5*(0,1,1) + .5*(0,.65798,.93969)
 *   = (0,.82899,.96985); rotation = normalised (identity + q20)/2 = q10 exactly,
 *   so B's local +Z points along (0,-sin10,cos10).
 * At bind every delta is identity: the head stays (0,1,1). Moving Root by
 * (5,0,0) moves both deltas alike, hence the head by exactly (5,0,0).
 * Names may carry the Mixamo prefix and unknown names are ignored.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import assert from 'node:assert/strict'

if (!process.env.ANCHOR_BLEND_BUNDLED) {
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild'].find(existsSync)
  assert.ok(bin, 'esbuild unavailable')
  const output = '/tmp/smoke_extension_anchor_blend.mjs'
  const built = spawnSync(bin, [fileURLToPath(import.meta.url), '--bundle', '--platform=node', '--format=esm', `--outfile=${output}`], { stdio: 'inherit' })
  assert.equal(built.status, 0)
  const run = spawnSync('node', [output], { stdio: 'inherit', env: { ...process.env, ANCHOR_BLEND_BUNDLED: '1' } })
  process.exit(run.status ?? 1)
}
const THREE = await import('three')
const { createSecondaryMotion } = await import('../packages/scene-render/src/secondaryMotion.ts')
const defaults = { freq_hz: 2, zeta: .3, gravity: 0, gravity_scale: 1, gain: 0,
  max_deg: 0, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1 }

function rig(blend) {
  const root = new THREE.Group(), s1 = new THREE.Bone(), s2 = new THREE.Bone(), b = new THREE.Bone()
  s1.name = 'mixamorigSpine1'; s2.name = 'mixamorigSpine2'; b.name = 'B'
  root.add(s1); s1.add(s2); s2.add(b)
  s2.position.set(0, 1, 0); b.position.set(0, 0, 1)
  if (blend) b.userData.anchor_blend = blend
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 1, 1.5], 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([2, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([s1, s2, b]))
  const motion = createSecondaryMotion(THREE, root, { rev: 'fixture', groups: { g: { ...defaults, bones: ['B'] } } })
  return { root, s2, b, motion }
}
const head = (b) => { b.updateWorldMatrix(true, false); return new THREE.Vector3().applyMatrix4(b.matrixWorld) }
const front = (b) => new THREE.Vector3(0, 0, 1).applyMatrix4(b.matrixWorld).sub(head(b)).normalize()
const near = (v, x, label) => assert.ok(v.distanceTo(new THREE.Vector3(...x)) < 1e-5, `${label}: ${v.toArray()} vs ${x}`)
const s20 = Math.sin(20 * Math.PI / 180), c20 = Math.cos(20 * Math.PI / 180)
const s10 = Math.sin(10 * Math.PI / 180), c10 = Math.cos(10 * Math.PI / 180)

{
  const { root, s2, b, motion } = rig(null)
  s2.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), 20 * Math.PI / 180)
  motion.update(1 / 60)
  near(head(b), [0, 1 - s20, c20], 'parent only: head')
  near(front(b), [0, -s20, c20], 'parent only: turn')
  motion.dispose()
}
{
  const { root, s2, b, motion } = rig({ 'mixamorig:Spine1': .5, 'mixamorig:Spine2': .5, 'mixamorig:Missing': .3 })
  motion.update(1 / 60)
  near(head(b), [0, 1, 1], 'blend at bind')
  s2.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), 20 * Math.PI / 180)
  motion.update(1 / 60)
  near(head(b), [0, (2 - s20) / 2, (1 + c20) / 2], 'blend: head')
  near(front(b), [0, -s10, c10], 'blend: turn')
  root.position.set(5, 0, 0)
  motion.update(1 / 60)
  near(head(b), [5, (2 - s20) / 2, (1 + c20) / 2], 'blend: moved root')
  motion.dispose()
}
console.log('PASS anchor_blend: bind unchanged, head and turn at the share-weighted blend, root motion carried')
