#!/usr/bin/env node
/**
 * Ruling A116: a channel moves LIKE THE SKIN AROUND ITS OPENING (`packages/scene-render/src/channels.ts`
 * `bindChannels`, module docstring "THE BINDING"). Before, O and the bottom rode the named joint rigidly; an opening
 * skinned mostly to the thighs left the channel ~11 cm and 70–90° off the drawn opening once the hips flexed.
 * Every expected number is derived BY HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_channel_region_skin.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE (metres, bind rotations identity, bindMatrix identity). Bones: Hips at J = (0, 0.9, 0) (root), Leg a
 *   child of Hips at its origin (also J). One body skinned mesh:
 *   - RING: 8 vertices on a circle of radius 0.01 about O = (0, 0.8, 0.05) in the x/z-plane, each 0.5 Hips + 0.5 Leg;
 *   - BOTTOM: 8 vertices on a circle of radius 0.005 about Bt = (0, 0.95, 0.03), each 1.0 Hips.
 *   Channel `pkg:chan` on Hips: a_pos O, b_pos Bt, r 0.035 (cone 30°, funnel 0.05).
 *   POSE: Leg turned by θ = 90° about +x at J (R_x: (y, z) → (y cos θ − z sin θ, y sin θ + z cos θ)), Hips still.
 * HAND-DERIVED:
 *   [1] BIND (no pose): O_now = O, bottom = Bt (exact, ±1e-9): u = (0, 0.15, −0.02)/0.151327, D 0.151327.
 *   [2] THE OPENING'S WEIGHTS: within CHANNEL_REGION_M 0.035 of O lie only the 8 ring vertices (the bottom ring is
 *       ≥ 0.151327 − 0.005 away) → 0.5 Hips + 0.5 Leg. O − J = (0, −0.1, 0.05) → R_x(90°) → (0, −0.05, −0.1), so
 *       R(O) = (0, 0.85, −0.1) and O_now = ½O + ½R(O) = (0, 0.825, −0.025) (±1e-9) — which is ALSO the centroid of
 *       the 8 skinned ring vertices (linear blend, same weights, centroid O) — the opening as drawn, 0 mm apart.
 *       The joint rule would have left O at (0, 0.8, 0.05): 79.057 mm away (√(0.025² + 0.075²)).
 *   [3] THE BOTTOM'S WEIGHTS: the K = 32 nearest vertices of the SAME mesh, uncapped = all 16 → 8·0.5 + 8·1.0 = 0.75
 *       Hips, 0.25 Leg. Bt − J = (0, 0.05, 0.03) → (0, −0.03, 0.05), R(Bt) = (0, 0.87, 0.05);
 *       bottom = 0.75 Bt + 0.25 R(Bt) = (0, 0.93, 0.035) (±1e-9). u = (0, 0.105, 0.06)/0.120934, D 0.120934.
 *   [4] FALLBACK: the same channel with every vertex moved 1 m away along +x (none within 0.035 of O): the joint
 *       rule — O_now = O, bottom = Bt in the posed frame (Hips did not move), ±1e-9.
 *   [5] MESH CHOICE: a SECOND body mesh (the hull) with 3 vertices within 0.035 of O, all 1.0 Hips, beside the ring
 *       mesh (8 there): the ring mesh wins → [2]'s O_now unchanged; with the hull holding 9 such vertices it wins
 *       → O_now = O (±1e-9).
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-channel-region-'))
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

const THREE = await import('three')
const SR = await loadSR()
assert.equal(SR.CHANNEL_REGION_M, 0.035)
assert.equal(SR.CHANNEL_REGION_K, 32)
const EPS = 1e-9
const near = (got, want, what) => {
  for (let i = 0; i < 3; i++) assert.ok(Math.abs(got[i] - want[i]) <= EPS, `${what}: ${got} vs ${want}`)
}
const O = [0, 0.8, 0.05], BT = [0, 0.95, 0.03]

function ring(c, r, n = 8) {
  return Array.from({ length: n }, (_, i) => [c[0] + r * Math.cos((2 * Math.PI * i) / n), c[1], c[2] + r * Math.sin((2 * Math.PI * i) / n)])
}

/** A skinned mesh on the shared skeleton: verts [[x,y,z]], weights [[wHips, wLeg]]. */
function mesh(skeleton, verts, weights) {
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(verts.flat(), 3))
  g.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(verts.flatMap(() => [0, 1, 0, 0]), 4))
  g.setAttribute('skinWeight', new THREE.Float32BufferAttribute(weights.flatMap(([h, l]) => [h, l, 0, 0]), 4))
  const m = new THREE.SkinnedMesh(g, new THREE.MeshBasicMaterial())
  m.bind(skeleton, new THREE.Matrix4())
  return m
}

function figure({ shift = 0, hull = 0 } = {}) {
  const root = new THREE.Group()
  const hips = new THREE.Bone(); hips.name = 'mixamorig:Hips'; hips.position.set(0, 0.9, 0)
  const leg = new THREE.Bone(); leg.name = 'mixamorig:LeftUpLeg'
  hips.add(leg); root.add(hips); root.updateMatrixWorld(true)
  const skeleton = new THREE.Skeleton([hips, leg])
  const verts = [...ring(O, 0.01), ...ring(BT, 0.005)].map(([x, y, z]) => [x + shift, y, z])
  const body = mesh(skeleton, verts, [...Array(8).fill([0.5, 0.5]), ...Array(8).fill([1, 0])])
  root.add(body)
  if (hull) root.add(mesh(skeleton, ring([O[0], O[1], O[2]], 0.02, hull), Array(hull).fill([1, 0])))
  root.updateMatrixWorld(true)
  return { root, leg, body }
}

const payload = {
  version: SR.COLLISION_VERSION, capsules: [],
  channels: [{ id: 'pkg:chan', kind: 'channel', a: 'mixamorig:Hips', b: 'mixamorig:Hips', a_pos: O, b_pos: BT, r: 0.035,
    cone_deg: 30, funnel: 0.05, accepts: ['appendage_chain'], min_length: 1, compress_min: 0.8, suppress: [],
    frame: { side: [1, 0, 0], up: [0, 1, 0], front: [0, 0, 1] }, placement: 'rig', applied: null }],
}
const pose = (fig) => { fig.leg.rotation.x = Math.PI / 2; fig.root.updateMatrixWorld(true) }
const bottom = (c) => c.o.map((x, i) => x + c.u[i] * c.depth)

// [1] bind
{
  const fig = figure(); const b = SR.bindChannels(THREE, fig.root, payload)
  const c = b.channels[0]
  near(c.o, O, '[1] O at bind')
  near(bottom(c), BT, '[1] bottom at bind')
  assert.ok(Math.abs(c.depth - Math.hypot(0.15, 0.02)) <= EPS, `[1] D ${c.depth}`)
  console.log(`[1] bind: O ${c.o.map((x) => x.toFixed(6))} D ${c.depth.toFixed(6)} ✓`)
}
// [2] + [3] posed
{
  const fig = figure(); const b = SR.bindChannels(THREE, fig.root, payload)
  pose(fig); b.update()
  const c = b.channels[0]
  near(c.o, [0, 0.825, -0.025], '[2] O_now')
  const t = new THREE.Vector3(), cen = new THREE.Vector3()
  for (let i = 0; i < 8; i++) cen.add(fig.body.getVertexPosition(i, t))
  cen.multiplyScalar(1 / 8)
  const dRing = Math.hypot(c.o[0] - cen.x, c.o[1] - cen.y, c.o[2] - cen.z)
  assert.ok(dRing <= 1e-6, `[2] O vs skinned ring centroid ${dRing}`) // Float32 vertices: 1e-6
  const old = Math.hypot(0.825 - 0.8, -0.025 - 0.05)
  assert.ok(Math.abs(old - 0.0790569) < 1e-6)
  near(bottom(c), [0, 0.93, 0.035], '[3] bottom')
  near(c.u, [0, 0.105 / Math.hypot(0.105, 0.06), 0.06 / Math.hypot(0.105, 0.06)], '[3] u')
  console.log(`[2] O_now ${c.o.map((x) => x.toFixed(6))}, skinned ring centroid ${(dRing * 1000).toFixed(6)} mm away`
    + ` (joint rule: ${(old * 1000).toFixed(3)} mm) ✓`)
  console.log(`[3] bottom ${bottom(c).map((x) => x.toFixed(6))} D ${c.depth.toFixed(6)} ✓`)
}
// [4] fallback
{
  const fig = figure({ shift: 1 }); const b = SR.bindChannels(THREE, fig.root, payload)
  pose(fig); b.update()
  near(b.channels[0].o, O, '[4] O joint rule'); near(bottom(b.channels[0]), BT, '[4] bottom joint rule')
  console.log('[4] no vertex in reach: the joint rule ✓')
}
// [5] mesh choice
{
  let fig = figure({ hull: 3 }); let b = SR.bindChannels(THREE, fig.root, payload); pose(fig); b.update()
  near(b.channels[0].o, [0, 0.825, -0.025], '[5] ring mesh wins over a 3-vertex hull')
  fig = figure({ hull: 9 }); b = SR.bindChannels(THREE, fig.root, payload); pose(fig); b.update()
  near(b.channels[0].o, O, '[5] a 9-vertex hull wins')
  console.log('[5] the mesh with the most vertices at the opening gives the weights ✓')
}
console.log('smoke_channel_region_skin: all checks passed')
