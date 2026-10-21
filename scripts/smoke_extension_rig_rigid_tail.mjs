#!/usr/bin/env node
/** Hand-derived rigid_tail check on a two-link chain Hips -> A -> B.
 * A sits 1 above Hips, B 1 above A; A's weighted vertex is at height 1.5, B's at 2.5.
 * State length=1.5, girth=1.3, gain=gravity=0 keeps rest rotations, so:
 *   A scales along its axis to B (local Y) by 1.5 and across by 1.3, which carries
 *   B's head to 1 + 1.5 = 2.5 in BOTH modes;
 *   rigid_tail=1: B keeps unit axes (no own extent, no inherited scale);
 *   rigid_tail=0: B is a driven leaf scaled along its centroid (Y) by 1.5, across by 1.3.
 * With doubled gravity (gravity_scale=2; the bind pose already carries 1 g) on a horizontal
 * chain (B 1 along +X of A), A sags while the rigid B points exactly along A's own X axis.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import assert from 'node:assert/strict'

if (!process.env.RIGID_TAIL_BUNDLED) {
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild'].find(existsSync)
  assert.ok(bin, 'esbuild unavailable')
  const output = '/tmp/smoke_extension_rigid_tail.mjs'
  const built = spawnSync(bin, [fileURLToPath(import.meta.url), '--bundle', '--platform=node', '--format=esm', `--outfile=${output}`], { stdio: 'inherit' })
  assert.equal(built.status, 0)
  const run = spawnSync('node', [output], { stdio: 'inherit', env: { ...process.env, RIGID_TAIL_BUNDLED: '1' } })
  process.exit(run.status ?? 1)
}
const THREE = await import('three')
const { createSecondaryMotion } = await import('../packages/scene-render/src/secondaryMotion.ts')
const defaults = { freq_hz: 2, zeta: .3, gravity: 0, gravity_scale: 1, gain: 0,
  max_deg: 0, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1 }

function rig(bOffset, vertices) {
  const root = new THREE.Group(), hips = new THREE.Bone(), a = new THREE.Bone(), b = new THREE.Bone()
  hips.name = 'Hips'; a.name = 'A'; b.name = 'B'
  root.add(hips); hips.add(a); a.add(b)
  a.position.set(0, 1, 0); b.position.set(...bOffset)
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(vertices.flat(), 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([1, 0, 0, 0, 2, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([hips, a, b]))
  return { root, a, b }
}
const axisLength = (m, v) => new THREE.Vector3(...v).applyMatrix4(m).sub(new THREE.Vector3().applyMatrix4(m)).length()

for (const tail of [1, 0]) {
  const { root, b } = rig([0, 1, 0], [[0, 1.5, 0], [0, 2.5, 0]])
  const motion = createSecondaryMotion(THREE, root, { rev: 'fixture', groups: {
    g: { ...defaults, bones: ['A', 'B'], length: 1.5, girth: 1.3, rigid_tail: tail } } })
  motion.update(1 / 60)
  b.updateWorldMatrix(true, false)
  const head = new THREE.Vector3().applyMatrix4(b.matrixWorld)
  assert.ok(head.distanceTo(new THREE.Vector3(0, 2.5, 0)) < 1e-8, `tail ${tail}: B head ${head.toArray()}`)
  const along = axisLength(b.matrixWorld, [0, 1, 0]), across = axisLength(b.matrixWorld, [1, 0, 0])
  if (tail) assert.ok(Math.abs(along - 1) < 1e-8 && Math.abs(across - 1) < 1e-8, `rigid B scaled ${along} ${across}`)
  else assert.ok(Math.abs(along - 1.5) < 1e-8 && Math.abs(across - 1.3) < 1e-8, `driven B ${along} ${across}`)
  motion.dispose()
}

{
  const { root, a, b } = rig([1, 0, 0], [[.5, 1, 0], [1.5, 1, 0]])
  const motion = createSecondaryMotion(THREE, root, { rev: 'fixture', groups: {
    g: { ...defaults, bones: ['A', 'B'], gravity: .5, gravity_scale: 2, sag_max_deg: 30, rigid_tail: 1 } } })
  motion.update(1 / 60)
  b.updateWorldMatrix(true, false)
  const origin = new THREE.Vector3().applyMatrix4(a.matrixWorld)
  const aX = new THREE.Vector3(1, 0, 0).applyMatrix4(a.matrixWorld).sub(origin).normalize()
  const bOrigin = new THREE.Vector3().applyMatrix4(b.matrixWorld)
  const bX = new THREE.Vector3(1, 0, 0).applyMatrix4(b.matrixWorld).sub(bOrigin).normalize()
  assert.ok(aX.y < -1e-3, `A must sag under gravity: ${aX.toArray()}`)
  assert.ok(aX.distanceTo(bX) < 1e-8, `rigid B adds own sag: ${aX.toArray()} vs ${bX.toArray()}`)
  motion.dispose()
  b.updateWorldMatrix(true, false)
  assert.ok(new THREE.Vector3().applyMatrix4(b.matrixWorld).distanceTo(new THREE.Vector3(1, 1, 0)) < 1e-8, 'dispose restores B')
}
console.log('PASS rigid_tail carries the tip unscaled at the extended parent end, with no sag of its own')
