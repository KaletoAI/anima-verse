#!/usr/bin/env node
/**
 * The client keeps glTF MASK hair cards and the Hairstyles preview applies the world cutoff — strand-hair plan
 * 2026-11-13, Task 3 (spec § 6.1): `createGarmentCollision` (packages/scene-render/src/garmentCollision.ts) and
 * `applyAlphaCutoff` (packages/scene-render/src/materials.ts). Hand-derived.
 *
 * Usage: node scripts/smoke_hair_alpha_client.mjs   (no server, no world; bundles itself with esbuild)
 *
 * FIXTURE (three, no renderer): a figure group with the bones Hips (origin) → Spine (0, 1, 0); a skinned body
 * and a skinned hair mesh `garment_hair_y` (userData.garment.kind "hair"), two vertices each, bound to that
 * skeleton. The hair's MeshStandardMaterial carries what GLTFLoader makes of a glTF MASK material at cutoff 0.12:
 * `alphaTest` 0.12 and a `map` (a 1x1 DataTexture). Collision payload v4: one torso capsule Hips → Spine, r 0.1
 * (hair takes the torso region, `HAIR_REGIONS`).
 *
 * [1] createGarmentCollision: the hair mesh's material is replaced by a patched CLONE (not the template) that
 *     keeps `alphaTest` 0.12 and the SAME map object (Material.copy copies both by reference/value); its
 *     `customDepthMaterial` and `customDistanceMaterial` carry `alphaTest` 0.12 and that map (the shadow cuts the
 *     same strands). dispose() restores the template material and the mesh's own (undefined) depth materials.
 * [2] applyAlphaCutoff on a root with a MASK material (alphaTest 0.12, as loaded) and an OPAQUE one (alphaTest 0):
 *     cutoff 0.18 → the MASK material reads 0.18, the OPAQUE one stays 0, returns 1 (one material changed);
 *     `userData.gltfAlphaTest` keeps 0.12 (the glTF value). A second call with 0.2 → 0.2, returns 1, the recorded
 *     value still 0.12. The same 0.2 again → returns 0 (nothing to change). A cutoff of 0 or NaN → returns 0,
 *     nothing changes (no renderer turns a MASK card opaque).
 *     With a garment push on the figure of [1]: applyAlphaCutoff(figure, 0.18) reaches the patched clone AND its
 *     two depth materials → 3 changed, each reads 0.18; the body (alphaTest 0) is untouched.
 * [3] Fails on the old code (BASE e1ad6a344, `git show` of materials.ts / index.ts): `applyAlphaCutoff` is not
 *     exported there; BASE's garmentCollision.ts creates the depth materials without copying `alphaTest` / `map`
 *     (the source text assigns no `.alphaTest =`). Note: three 0.185's shadow pass copies map/alphaTest onto a
 *     custom depth material at render time (WebGLShadowMap getDepthMaterial), so BASE's SHADOWS were already cut;
 *     the creation-time copy makes the depth materials correct before that pass and visible to applyAlphaCutoff.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'

const BASE = 'e1ad6a344'
const here = fileURLToPath(import.meta.url)
const repo = path.resolve(path.dirname(here), '..')
if (!process.env.HAIR_ALPHA_BUNDLED) {
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild']
    .map(rel => path.join(repo, rel)).find(existsSync)
  assert.ok(bin, 'esbuild unavailable (npm install) — nothing was checked')
  const out = '/tmp/smoke_hair_alpha_client.mjs'
  const built = spawnSync(bin, [here, '--bundle', '--platform=node', '--format=esm', `--outfile=${out}`,
    '--log-level=error'], { stdio: 'inherit', env: { ...process.env, NODE_PATH: path.join(repo, 'node_modules') } })
  assert.equal(built.status, 0)
  const run = spawnSync('node', [out], { stdio: 'inherit',
    env: { ...process.env, HAIR_ALPHA_BUNDLED: '1', HAIR_ALPHA_REPO: repo } })
  process.exit(run.status ?? 1)
}
const THREE = await import('three')
const { createGarmentCollision } = await import('../packages/scene-render/src/garmentCollision.ts')
const { applyAlphaCutoff } = await import('../packages/scene-render/src/materials.ts')

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}

function figure() {
  const fig = new THREE.Group()
  const hips = new THREE.Bone(); hips.name = 'mixamorig:Hips'
  const spine = new THREE.Bone(); spine.name = 'mixamorig:Spine'
  spine.position.set(0, 1, 0)
  hips.add(spine)
  fig.add(hips)
  const geo = () => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute([0.05, 0.5, 0, 0, 1, 0], 3))
    g.setAttribute('uv', new THREE.Float32BufferAttribute([0.1, 0.5, 0.1, 1], 2))
    g.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 0, 0, 0, 1, 0, 0, 0], 4))
    g.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0], 4))
    return g
  }
  const body = new THREE.SkinnedMesh(geo(), new THREE.MeshStandardMaterial())
  fig.add(body)
  const map = new THREE.DataTexture(new Uint8Array([255, 255, 255, 128]), 1, 1)
  const hairMat = new THREE.MeshStandardMaterial({ map, alphaTest: 0.12, side: THREE.DoubleSide })
  const hair = new THREE.SkinnedMesh(geo(), hairMat)
  hair.name = 'garment_hair_y'
  hair.userData.garment = { kind: 'hair', item_id: 'y', fsig: 'z' }
  fig.add(hair)
  fig.updateMatrixWorld(true)
  const skeleton = new THREE.Skeleton([hips, spine])
  body.bind(skeleton)
  hair.bind(skeleton)
  return { fig, body, hair, hairMat, map }
}
const payload = { version: 4, capsules: [
  { id: 'torso', a: 'mixamorig:Hips', b: 'mixamorig:Spine', r: 0.1, region: 'torso' }] }

console.log('--- [1] createGarmentCollision keeps MASK ---')
{
  const f = figure()
  const gc = createGarmentCollision(THREE, f.fig, payload)
  check('a push on the hair', !!gc && gc.entries.some(e => e.mesh === f.hair))
  const clone = f.hair.material
  check('the material is a patched clone', clone !== f.hairMat)
  check('clone keeps alphaTest 0.12', clone.alphaTest === 0.12, String(clone.alphaTest))
  check('clone keeps the same map object', clone.map === f.map)
  const depth = f.hair.customDepthMaterial
  const dist = f.hair.customDistanceMaterial
  check('customDepthMaterial alphaTest 0.12', depth?.alphaTest === 0.12, String(depth?.alphaTest))
  check('customDepthMaterial map = the card map', depth?.map === f.map)
  check('customDistanceMaterial alphaTest 0.12 + the map', dist?.alphaTest === 0.12 && dist?.map === f.map,
    String(dist?.alphaTest))
  console.log('--- [2] applyAlphaCutoff through the push ---')
  const n = applyAlphaCutoff(f.fig, 0.18)
  check('3 changed (clone + depth + distance)', n === 3, String(n))
  check('clone / depth / distance read 0.18', clone.alphaTest === 0.18 && depth.alphaTest === 0.18
    && dist.alphaTest === 0.18)
  check('the body stays 0', f.body.material.alphaTest === 0)
  gc.dispose()
  check('dispose restores the template material', f.hair.material === f.hairMat)
  check('dispose restores the own depth materials', f.hair.customDepthMaterial === undefined
    && f.hair.customDistanceMaterial === undefined)
}

console.log('--- [2] applyAlphaCutoff ---')
{
  const root = new THREE.Group()
  const mask = new THREE.MeshStandardMaterial({ alphaTest: 0.12 })
  const opaque = new THREE.MeshStandardMaterial()
  root.add(new THREE.Mesh(new THREE.BufferGeometry(), mask))
  root.add(new THREE.Mesh(new THREE.BufferGeometry(), opaque))
  let n = applyAlphaCutoff(root, 0.18)
  check('0.18: MASK -> 0.18, OPAQUE stays 0, returns 1', mask.alphaTest === 0.18 && opaque.alphaTest === 0 && n === 1,
    `${mask.alphaTest} ${opaque.alphaTest} ${n}`)
  check('recorded glTF value 0.12', mask.userData.gltfAlphaTest === 0.12)
  n = applyAlphaCutoff(root, 0.2)
  check('0.2: -> 0.2, returns 1, recorded value stays 0.12', mask.alphaTest === 0.2 && n === 1
    && mask.userData.gltfAlphaTest === 0.12 && opaque.alphaTest === 0, `${mask.alphaTest} ${n}`)
  check('0.2 again: returns 0', applyAlphaCutoff(root, 0.2) === 0)
  check('0 / NaN: returns 0, nothing changes', applyAlphaCutoff(root, 0) === 0 && applyAlphaCutoff(root, NaN) === 0
    && mask.alphaTest === 0.2)
}

console.log(`--- [3] fails on the old code (${BASE}) ---`)
{
  const show = (rel) => spawnSync('git', ['-C', process.env.HAIR_ALPHA_REPO, 'show', `${BASE}:${rel}`],
    { encoding: 'utf8' })
  const mats = show('packages/scene-render/src/materials.ts')
  const index = show('packages/scene-render/src/index.ts')
  const gcOld = show('packages/scene-render/src/garmentCollision.ts')
  assert.equal(mats.status, 0, `git show ${BASE} failed`)
  check('BASE exports no applyAlphaCutoff', !/applyAlphaCutoff/.test(mats.stdout) && !/applyAlphaCutoff/.test(index.stdout))
  check('BASE garment push assigns no alphaTest to its depth materials', !/\.alphaTest\s*=/.test(gcOld.stdout))
}

console.log(failures ? `FAIL (${failures})` : 'ALL OK')
process.exit(failures ? 1 : 0)
