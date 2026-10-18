#!/usr/bin/env node
/** Hand-derived: the leaf's weighted centroid points along local X. With
 * length=1.6 and girth=1.4, bone mode maps unit Y to 1.6 and unit X to 1.4;
 * centroid mode swaps those lengths. gain=gravity=0 keeps rest rotations.
 * Parent length=1.2 checks ancestor scale isolation; reversing group order
 * must leave the complete child world matrix unchanged.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import assert from 'node:assert/strict'

if (!process.env.PAIR_TIP_BUNDLED) {
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild'].find(existsSync)
  assert.ok(bin, 'esbuild unavailable')
  const output = '/tmp/smoke_extension_pair_tip.mjs'
  const built = spawnSync(bin, [fileURLToPath(import.meta.url), '--bundle', '--platform=node', '--format=esm', `--outfile=${output}`], { stdio: 'inherit' })
  assert.equal(built.status, 0)
  const run = spawnSync('node', [output], { stdio: 'inherit', env: { ...process.env, PAIR_TIP_BUNDLED: '1' } })
  process.exit(run.status ?? 1)
}
const THREE = await import('three')
const { createSecondaryMotion } = await import('../packages/scene-render/src/secondaryMotion.ts')
function evaluate(childFirst, scale_axis = 'bone') {
  const root = new THREE.Group(), base = new THREE.Bone(), parent = new THREE.Bone(), child = new THREE.Bone()
  base.name = 'Hips'; parent.name = 'Pair'; child.name = 'Tip'
  root.add(base); base.add(parent); parent.add(child)
  parent.position.set(0, 1, 0); child.position.set(0, 1, 0)
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 1.5, 0, .5, 2, 0], 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([1, 0, 0, 0, 2, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([base, parent, child]))
  const defaults = { freq_hz: 2.2, zeta: .15, gravity: 0, gravity_scale: 1, gain: 0,
    max_deg: 0, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
    flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
    squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
    straighten_deg: 0, freetext_clothing_gain: 1 }
  const groups = { parent: { ...defaults, bones: ['Pair'], length: 1.2 }, child: { ...defaults, bones: ['Tip'], length: 1.6, girth: 1.4, scale_axis } }
  const payload = { rev: 'fixture', groups: childFirst ? { child: groups.child, parent: groups.parent } : groups }
  const motion = createSecondaryMotion(THREE, root, payload)
  motion.update(1 / 60)
  child.updateWorldMatrix(true, false)
  const origin = new THREE.Vector3().applyMatrix4(child.matrixWorld)
  const axis = new THREE.Vector3(0, 1, 0).applyMatrix4(child.matrixWorld).sub(origin)
  assert.ok(Math.abs(axis.length() - (scale_axis === 'bone' ? 1.6 : 1.4)) < 1e-8, `axis length ${axis.length()}`)
  const radial = new THREE.Vector3(1, 0, 0).applyMatrix4(child.matrixWorld).sub(origin)
  assert.ok(Math.abs(radial.length() - (scale_axis === 'bone' ? 1.4 : 1.6)) < 1e-8)
  const matrix = child.matrixWorld.toArray()
  motion.dispose()
  return matrix
}
const normal = evaluate(false), reversed = evaluate(true)
assert.ok(normal.every((value, index) => Math.abs(value - reversed[index]) < 1e-8))
evaluate(false, 'centroid')
console.log('PASS bone and centroid scale axes, girth, payload-independent ancestor ordering')
