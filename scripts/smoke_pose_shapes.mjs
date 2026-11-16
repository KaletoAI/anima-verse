#!/usr/bin/env node
/**
 * Ruling A141: the pose shapes of a draped template garment (`packages/scene-render/src/poseShapes.ts`; the same
 * rule as `blend` in `app/blender/scripts/garment_template_build.py`). Every expected number is derived BY HAND
 * below (§ B5a).
 *
 * Usage: node scripts/smoke_pose_shapes.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * Samples (σ 0.5): rest (anchor) with all four segments (0,−1,0); sit (target "sit") with the thighs (0,0,1) and
 * the shins (0,−1,0).
 * [1] features = rest: d_rest = 0; d_sit² = 2·(π/2)² = 4.9348 → g_sit = exp(−4.9348 / (2·0.25)) = exp(−9.8696)
 *     = 5.1723e−5 → sit = 5.1723e−5 / (1 + 5.1723e−5) = 5.1720e−5.
 * [2] features = sit: the mirror case → sit = 1 / (1 + 5.1723e−5) = 0.99994828.
 * [3] thighs at 45° forward (0, −√½, √½), shins (0,−1,0): d_rest² = d_sit² = 2·(π/4)² → sit = 0.5 exactly.
 * [4] validPoseShapes: the payload passes; a sample with three directions fails; σ 0 fails.
 * [5] bindPoseShapes on a built rig: hips (0,1,0); thighs from (±0.1,0.95,0) to (±0.1,0.5,0); shins to
 *     (±0.1,0.05,0); one skinned garment with a morph target "sit" and the payload in userData.garment.
 *     a) bind pose → sit 5.1720e−5 (= [1]);
 *     b) both UpLegs rotated −90° about X: a thigh (0,−1,0) turns to (0, −cos θ, −sin θ) = (0, 0, 1); the Legs +90°
 *        about X: the shin turns by the sum 0 → (0,−1,0) → the sit sample → 0.99994828 (= [2]);
 *     c) b) with the hips leaned 30° about X and the figure root turned 90° about Y: the hips' rotation since bind is
 *        taken out and the root cancels → the same 0.99994828;
 *     d) the morph influence written is that number.
 * [6] bindPoseShapes without a pose-shaped garment → null.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-pose-shapes-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: "export * from '@anima/scene-render';", resolveDir: join(ROOT, 'client3d'), loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'sr.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'sr.mjs')
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

const SR = await loadSR()
const THREE = await import(join(ROOT, 'node_modules/three/build/three.module.js'))
const near = (a, b, eps, msg) => assert.ok(Math.abs(a - b) <= eps, `${msg}: ${a} vs ${b}`)

const down = [0, -1, 0]
const samples = [
  { pose: 'rest', target: null, dirs: [down, down, down, down] },
  { pose: 'sit', target: 'sit', dirs: [[0, 0, 1], [0, 0, 1], down, down] },
]
const SIT_AT_REST = 5.1723e-5 / (1 + 5.1723e-5)
const SIT_AT_SIT = 1 / (1 + 5.1723e-5)
near(SR.poseShapeInfluences([down, down, down, down], samples, 0.5).sit, SIT_AT_REST, 1e-8, '[1] rest')
near(SR.poseShapeInfluences([[0, 0, 1], [0, 0, 1], down, down], samples, 0.5).sit, SIT_AT_SIT, 1e-8, '[2] sit')
const h = Math.SQRT1_2
near(SR.poseShapeInfluences([[0, -h, h], [0, -h, h], down, down], samples, 0.5).sit, 0.5, 1e-12, '[3] half')

const payload = {
  version: 1, sigma: 0.5, targets: ['sit'], samples,
  segments: [['LeftUpLeg', 'LeftLeg'], ['RightUpLeg', 'RightLeg'], ['LeftLeg', 'LeftFoot'], ['RightLeg', 'RightFoot']],
}
assert.equal(SR.validPoseShapes(payload), true)                                                  // [4]
assert.equal(SR.validPoseShapes({ ...payload, samples: [{ pose: 'x', target: null, dirs: [down, down, down] }] }), false)
assert.equal(SR.validPoseShapes({ ...payload, sigma: 0 }), false)

function rig(withShapes) {                                                                       // [5]
  const root = new THREE.Group()
  const inst = new THREE.Group()
  root.add(inst)
  const bone = (name, x, y, z, parent) => {
    const b = new THREE.Bone(); b.name = name; b.position.set(x, y, z); (parent ?? inst).add(b); return b
  }
  const hips = bone('mixamorigHips', 0, 1, 0)
  const bones = [hips]
  for (const [side, x] of [['Left', 0.1], ['Right', -0.1]]) {
    const up = bone(`mixamorig${side}UpLeg`, x, -0.05, 0, hips)
    const leg = bone(`mixamorig${side}Leg`, 0, -0.45, 0, up)
    const foot = bone(`mixamorig${side}Foot`, 0, -0.45, 0, leg)
    bones.push(up, leg, foot)
  }
  inst.updateMatrixWorld(true)
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 1, 0, 0.1, 0.9, 0, -0.1, 0.9, 0], 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
  geo.morphAttributes.position = [new THREE.Float32BufferAttribute([0, 0, 0, 0, 0, 0.1, 0, 0, 0.1], 3)]
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  mesh.updateMorphTargets()
  mesh.morphTargetDictionary = { sit: 0 }
  if (withShapes) mesh.userData.garment = { kind: 'clothing', pose_shapes: payload }
  inst.add(mesh)
  mesh.bind(new THREE.Skeleton(bones))
  return { root, inst, mesh, byName: n => bones.find(b => b.name === `mixamorig${n}`) }
}
const r = rig(true)
const ps = SR.bindPoseShapes(THREE, r.inst)
assert.ok(ps, '[5] bound')
ps.update()
near(ps.last.influences.sit, SIT_AT_REST, 1e-6, '[5a] bind pose')
for (const s of ['Left', 'Right']) {
  r.byName(`${s}UpLeg`).rotateX(-Math.PI / 2)
  r.byName(`${s}Leg`).rotateX(Math.PI / 2)
}
ps.update()
near(ps.last.influences.sit, SIT_AT_SIT, 1e-6, '[5b] sit')
r.byName('Hips').rotateX(Math.PI / 6)
r.root.rotateY(Math.PI / 2)
ps.update()
near(ps.last.influences.sit, SIT_AT_SIT, 1e-6, '[5c] hips leaned, root turned')
near(r.mesh.morphTargetInfluences[0], SIT_AT_SIT, 1e-6, '[5d] written')
assert.equal(SR.bindPoseShapes(THREE, rig(false).inst), null)                                    // [6]
console.log('smoke_pose_shapes: ALL OK')
