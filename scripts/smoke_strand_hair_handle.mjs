#!/usr/bin/env node
/**
 * The strand hair on a figure (`packages/scene-render/src/hairSim.ts` `createStrandHair`), the figure budget
 * (`hairSimMath.ts` `pickStrandFigures`), the hair groups dropped while a figure runs per strand
 * (`secondaryMotion.ts` `withoutHairGroups`) and the hair mesh left out of the garment push
 * (`garmentCollision.ts` `GarmentCollision.excludeMesh`) — strand-hair plan 2026-11-13 Task 8, spec § 6.2.2 /
 * § 6.2.4, Ruling H-R7. Hand-derived.
 *
 * Usage: node scripts/smoke_strand_hair_handle.mjs   (no server, no world; bundles itself with esbuild, three in node)
 *
 * PICKER (STRAND_LIMITS = 2 figures, cutoff 8 m, leave 9 m, budget 8 ms; nearest first, the nearest in range always
 * admitted, the next only while the sum ≤ 8 and the count ≤ 2, the first that does not fit ends the list):
 *   [P1] A 2 m 5 ms, B 4 m 5 ms, C 6 m 3 ms, none running → {A}: A in; A + B = 10 > 8 → stop (C, cheaper, is
 *        behind B and never reached).
 *   [P2] A 2 m 3 ms, B 4 m 4 ms, C 5 m 1 ms → {A, B}: 3 + 4 = 7 ≤ 8; C would make 3 > 2 figures → stop.
 *   [P3] A 8.5 m running → {A} (8.5 ≤ leave 9); A 8.5 m not running → {} (8.5 > cutoff 8).
 *   [P4] A 1 m 12 ms → {A} (the nearest is always admitted, over budget or not).
 *
 * FIXTURE (metres; every bone rotation identity, so bind space = world at the bind pose and a bone's
 * bind→world matrix is a pure translation by how far the figure moved):
 *   skeleton Hips (0, 0, 0) → Spine2 (0, 1.30, 0) → Neck (0, 1.45, 0) → Head (0, 1.55, 0), bone indices 0..3;
 *   a BODY skinned mesh (3 vertices on Hips) — what `bindCollision` binds the capsules to;
 *   a garment group `garment_hair_fixture` (extras `{garment: {kind: "hair"}}`) holding the HAIR skinned mesh on
 *   the same skeleton: 2 cards of 17 rows × 2 vertices + 4 cap vertices = 72 vertices. Card k (k = 0, 1) hangs
 *   straight down at x_k = ∓0.03, z = −0.10: row i at y 1.60 − 0.02·i, its two vertices at x_k ± 0.004, normal
 *   (0, 0, −1), `_STRAND_CARD` k + 1, `_STRAND_U` i. The cap: 4 vertices at y 1.695, x/z ±0.02, normal (0, 1, 0),
 *   card 0. SKIN as the fit wrote it: card vertices half Neck / half Head (indices (2, 3, 0, 0), weights
 *   (0.5, 0.5, 0, 0)); cap vertices Head (3, 0, 0, 0) / (1, 0, 0, 0).
 *   RECORD: cards 2, rows 17, rest = the row centres (x_k, 1.60 − 0.02·i, −0.10), pins 2 per card, free_arc
 *   0 on rows 0–1 then 0.02·(i − 1), free_frac (i − 1)/15, follow {bones [mixamorig:Head], w 1}, ear_y 1.50, an
 *   SDF of 2×2×2 voxels at +127 mm (+0.127 m — nothing touches the head), face_box / eye_box in front of the face
 *   (z0 0.05 > −0.10: no row is ever inside), the spike defaults as params. Capsules (version 4): `head` (region
 *   head, Neck → Head, r 0.2) and `torso` (region torso, Spine2 → Neck, r 0.12).
 * [1] createStrandHair → a handle; it drives the hair mesh; its colliders are ['torso'] — the head capsule left out
 *     (Ruling H-R7: the head SDF covers the head); disabled until `setEnabled(true)`.
 * [2] setEnabled(true): mesh.geometry !== the template geometry; every card vertex's skin is (3, 0, 0, 0) /
 *     (1, 0, 0, 0) (Head alone); the 4 cap vertices keep (3, 0, 0, 0) / (1, 0, 0, 0) as the template has them, and
 *     the template's own card skin is still (2, 3, 0, 0) / (0.5, 0.5, 0, 0). The switch is invisible at rest: the
 *     rebuilt positions equal the template's within 1e-6 m (every frame is the identity at the bind pose).
 * [3] setEnabled(false): mesh.geometry IS the template geometry object again, its skinIndex / skinWeight the very
 *     attribute objects it had; dispose() afterwards: the owned clone was disposed exactly once (spy count 1), the
 *     template never (spy count 0).
 * [4] StrandMismatch: the record cut to ONE card (cards 1, arrays of 1·17 rows) while `_STRAND_CARD` reaches 2 →
 *     createStrandHair returns null and the mesh keeps its geometry (Review Focus 2: never scramble vertices).
 * [5] A 1 m head jump in one update (the figure moved 0.3 m/s along +z for 30 frames, then +1 m along x): after
 *     that update every simulated row equals its target exactly (reset; float32), and the targets are the rest
 *     rows moved by the figure's offset (x + 1, z + 0.15) within 1e-6. Then `frozen: true` with the figure moved
 *     again by 0.05 m: the position buffer is unchanged, bit for bit.
 * [6] withoutHairGroups({rev 'r1', groups {hair_c00: {hair: true}, tail: {}}}) → group keys ['tail'], rev 'r1:strands';
 *     the same input gives the same object (a per-frame call allocates nothing); undefined stays undefined.
 * [7] createGarmentCollision over the fixture: the hair mesh wears a patched clone; excludeMesh(hair, true) →
 *     hair.material IS the original (unpatched) object again; excludeMesh(hair, false) → the same patched clone as
 *     before (identity), its depth material the patched one.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'

if (!process.env.STRAND_HANDLE_BUNDLED) {
  const here = fileURLToPath(import.meta.url)
  const repo = path.resolve(path.dirname(here), '..')
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild']
    .map(rel => path.join(repo, rel)).find(existsSync)
  assert.ok(bin, 'esbuild unavailable (npm install) — nothing was checked')
  const out = `/tmp/smoke_strand_hair_handle.${process.pid}.mjs`
  const built = spawnSync(bin, [here, '--bundle', '--platform=node', '--format=esm', `--outfile=${out}`,
    '--log-level=error'], { stdio: 'inherit', env: { ...process.env, NODE_PATH: path.join(repo, 'node_modules') } })
  assert.equal(built.status, 0)
  const run = spawnSync('node', [out], { stdio: 'inherit', env: { ...process.env, STRAND_HANDLE_BUNDLED: '1' } })
  spawnSync('rm', ['-f', out])
  process.exit(run.status ?? 1)
}

const THREE = await import('three')
const { createStrandHair } = await import('../packages/scene-render/src/hairSim.ts')
const { pickStrandFigures, STRAND_LIMITS, STRAND_ROWS } = await import('../packages/scene-render/src/hairSimMath.ts')
const { withoutHairGroups } = await import('../packages/scene-render/src/secondaryMotion.ts')
const { createGarmentCollision } = await import('../packages/scene-render/src/garmentCollision.ts')

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
const setOf = s => [...s].sort().join(',')

// --- the picker ---------------------------------------------------------------------------------------------------
{
  const c = (name, distance, costMs, running = false) => ({ name, distance, costMs, running })
  check('[P0] STRAND_LIMITS = 2 figures, 8 m, leave 9 m, 8 ms',
    STRAND_LIMITS.maxFigures === 2 && STRAND_LIMITS.cutoffM === 8 && STRAND_LIMITS.leaveM === 9 && STRAND_LIMITS.budgetMs === 8)
  const p1 = pickStrandFigures([c('C', 6, 3), c('A', 2, 5), c('B', 4, 5)])
  check('[P1] 5 + 5 > 8: {A}, the cheaper C behind B never reached', setOf(p1) === 'A', setOf(p1))
  const p2 = pickStrandFigures([c('A', 2, 3), c('B', 4, 4), c('C', 5, 1)])
  check('[P2] 3 + 4 ≤ 8, count 2 = max: {A, B}', setOf(p2) === 'A,B', setOf(p2))
  check('[P3] 8.5 m running stays (leave 9 m)', setOf(pickStrandFigures([c('A', 8.5, 3, true)])) === 'A')
  check('[P3] 8.5 m not running is not admitted (cutoff 8 m)', pickStrandFigures([c('A', 8.5, 3)]).size === 0)
  check('[P4] the nearest is always admitted (12 ms)', setOf(pickStrandFigures([c('A', 1, 12)])) === 'A')
}

// --- the fixture --------------------------------------------------------------------------------------------------
const R = STRAND_ROWS
const XK = [-0.03, 0.03]
const PARAMS = { damping: 0.04, stiffness: 1.0, bend: 0.15, iterations: 6, root_deg: 10, root_frac: 0.2,
  fly_soft: true, fly_arc: 0.30, tether: true, tether_r0: 0.015, tether_r1: 0.06, tether_head: 0.012,
  head_clr: 0.03, face_box: true }
const CAPSULES = [
  { id: 'head', a: 'mixamorig:Neck', b: 'mixamorig:Head', r: 0.2, region: 'head' },
  { id: 'torso', a: 'mixamorig:Spine2', b: 'mixamorig:Neck', r: 0.12, region: 'torso' },
]

function record(cards = 2) {
  const rest = [], pins = [], freeArc = [], freeFrac = [], w = []
  for (let k = 0; k < cards; k++) {
    pins.push(2)
    for (let i = 0; i < R; i++) {
      rest.push(XK[k], 1.60 - 0.02 * i, -0.10)
      freeArc.push(i < 2 ? 0 : 0.02 * (i - 1))
      freeFrac.push(i < 2 ? 0 : (i - 1) / 15)
      w.push(1)
    }
  }
  return { version: 1, item_id: 'hair_fixture', fsig: '0123456789ab', mode: 'hairdeck', fit_sha256: '0',
    frame: 'head_bind', head_bone: 'mixamorig:Head', rows: R, cards, rest, pins, free_arc: freeArc,
    free_frac: freeFrac, follow: { bones: ['mixamorig:Head'], w }, ear_y: 1.50,
    face_box: [-0.06, 0.06, 1.48, 1.66, 0.05], eye_box: [-0.04, 0.04, 1.55, 1.64, 0.05],
    sdf: { dims: [2, 2, 2], lo: [-0.2, 1.3, -0.2], vox: 0.4, order: 'x_fastest', unit: 'mm_int8',
      data: Buffer.from(new Int8Array(8).fill(127).buffer).toString('base64') },
    capsules: { version: 4, capsules: CAPSULES, scales: {} }, params: PARAMS,
    vertex_attributes: { card: '_STRAND_CARD', u: '_STRAND_U' } }
}

function figure() {
  const fig = new THREE.Group()
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = name; b.position.set(...at); (parent ?? fig).add(b); return b
  }
  const hips = bone('mixamorig:Hips', null, [0, 0, 0])
  const spine = bone('mixamorig:Spine2', hips, [0, 1.30, 0])
  const neck = bone('mixamorig:Neck', spine, [0, 0.15, 0])
  const head = bone('mixamorig:Head', neck, [0, 0.10, 0])
  fig.updateMatrixWorld(true)
  const skeleton = new THREE.Skeleton([hips, spine, neck, head])
  const skinned = (geo, name) => {
    const m = new THREE.SkinnedMesh(geo, new THREE.MeshStandardMaterial()); m.name = name; return m
  }
  const bodyGeo = new THREE.BufferGeometry()
  bodyGeo.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 0.1, 0, 0, 0, 0.1, 0], 3))
  bodyGeo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Array(12).fill(0), 4))
  bodyGeo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
  const body = skinned(bodyGeo, 'body')
  const pos = [], nrm = [], card = [], u = [], si = [], sw = []
  for (let k = 0; k < 2; k++) {
    for (let i = 0; i < R; i++) {
      for (const s of [-1, 1]) {
        pos.push(XK[k] + s * 0.004, 1.60 - 0.02 * i, -0.10); nrm.push(0, 0, -1)
        card.push(k + 1); u.push(i); si.push(2, 3, 0, 0); sw.push(0.5, 0.5, 0, 0)
      }
    }
  }
  for (const [x, z] of [[-0.02, -0.02], [0.02, -0.02], [0.02, 0.02], [-0.02, 0.02]]) {
    pos.push(x, 1.695, z); nrm.push(0, 1, 0); card.push(0); u.push(0); si.push(3, 0, 0, 0); sw.push(1, 0, 0, 0)
  }
  const hairGeo = new THREE.BufferGeometry()
  hairGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  hairGeo.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3))
  hairGeo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(si, 4))
  hairGeo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(sw, 4))
  hairGeo.setAttribute('_strand_card', new THREE.Uint16BufferAttribute(card, 1))
  hairGeo.setAttribute('_strand_u', new THREE.Float32BufferAttribute(u, 1))
  const hair = skinned(hairGeo, 'hair')
  const garment = new THREE.Group()
  garment.name = 'garment_hair_fixture'
  garment.userData.garment = { kind: 'hair' }
  garment.add(hair)
  fig.add(body, garment)
  fig.updateMatrixWorld(true)
  body.bind(skeleton, body.matrixWorld)
  hair.bind(skeleton, hair.matrixWorld)
  return { fig, hair, template: hairGeo }
}

const skinOf = (geo, v) => {
  const si = geo.getAttribute('skinIndex'), sw = geo.getAttribute('skinWeight')
  return [si.getX(v), si.getY(v), si.getZ(v), si.getW(v), sw.getX(v), sw.getY(v), sw.getZ(v), sw.getW(v)].join(',')
}
const NCARD = 2 * R * 2

// [1] .. [3]
{
  const { fig, hair, template } = figure()
  const templateSkin = [template.getAttribute('skinIndex'), template.getAttribute('skinWeight')]
  const h = createStrandHair(THREE, fig, record())
  check('[1] createStrandHair returns a handle', h !== null)
  check('[1] it drives the hair mesh, disabled until switched on', h?.mesh === hair && h?.enabled === false
    && hair.geometry === template)
  check('[1] colliders: the head capsule left out (Ruling H-R7)', JSON.stringify(h?.capsuleIds) === '["torso"]',
    JSON.stringify(h?.capsuleIds))
  h.setEnabled(true)
  const owned = hair.geometry
  check('[2] setEnabled(true): an owned geometry, not the template', h.enabled && owned !== template)
  let cardsHead = true, capKept = true
  for (let v = 0; v < NCARD; v++) if (skinOf(owned, v) !== '3,0,0,0,1,0,0,0') cardsHead = false
  for (let v = NCARD; v < NCARD + 4; v++) if (skinOf(owned, v) !== skinOf(template, v)) capKept = false
  check('[2] every card vertex skinned to the Head alone (3,0,0,0 / 1,0,0,0)', cardsHead)
  check('[2] cap vertices unchanged', capKept && skinOf(owned, NCARD) === '3,0,0,0,1,0,0,0')
  check('[2] the template skin untouched (2,3,0,0 / 0.5,0.5,0,0)', skinOf(template, 0) === '2,3,0,0,0.5,0.5,0,0')
  const p = owned.getAttribute('position').array, p0 = template.getAttribute('position').array
  let d = 0
  for (let i = 0; i < p.length; i++) d = Math.max(d, Math.abs(p[i] - p0[i]))
  check('[2] invisible at rest: rebuilt positions == template within 1e-6 m', d <= 1e-6, `max ${d.toExponential(2)}`)
  let ownedDisposed = 0, templateDisposed = 0
  const od = owned.dispose.bind(owned), td = template.dispose.bind(template)
  owned.dispose = () => { ownedDisposed++; od() }
  template.dispose = () => { templateDisposed++; td() }
  h.setEnabled(false)
  check('[3] setEnabled(false): the template geometry object is back', hair.geometry === template && !h.enabled)
  check('[3] its skin attributes are the very objects it had', template.getAttribute('skinIndex') === templateSkin[0]
    && template.getAttribute('skinWeight') === templateSkin[1])
  h.dispose()
  check('[3] dispose(): the owned clone disposed exactly once, the template never',
    ownedDisposed === 1 && templateDisposed === 0, `owned ${ownedDisposed}, template ${templateDisposed}`)
}

// [4] StrandMismatch → null
{
  const { fig, hair, template } = figure()
  const h = createStrandHair(THREE, fig, record(1))
  check('[4] a 1-card record for _STRAND_CARD up to 2 → null, the mesh untouched', h === null && hair.geometry === template)
}

// [5] head jump → reset; frozen holds
{
  const { fig, hair } = figure()
  const h = createStrandHair(THREE, fig, record())
  h.setEnabled(true)
  for (let f = 0; f < 30; f++) {
    fig.position.z += 0.3 / 60
    fig.updateMatrixWorld(true)
    h.update(1 / 60)
  }
  let lag = 0
  for (let q = 0; q < h.sim.X.length; q++) lag = Math.max(lag, Math.abs(h.sim.X[q] - h.targets[q]))
  fig.position.x += 1
  fig.updateMatrixWorld(true)
  h.update(1 / 60)
  let off = 0, moved = 0
  const rest = record().rest
  for (let q = 0; q < h.sim.X.length; q++) off = Math.max(off, Math.abs(h.sim.X[q] - h.targets[q]))
  for (let p = 0; p < rest.length; p += 3) {
    moved = Math.max(moved, Math.abs(h.targets[p] - (rest[p] + 1)), Math.abs(h.targets[p + 1] - rest[p + 1]),
      Math.abs(h.targets[p + 2] - (rest[p + 2] + 0.15)))
  }
  check('[5] the walk left the free rows behind their targets (the case is real)', lag > 1e-4, `lag ${lag.toFixed(5)} m`)
  check('[5] a 1 m head jump resets: every row == its target', off === 0, `max ${off}`)
  check('[5] targets = rest + (1, 0, 0.15) within 1e-6', moved <= 1e-6, `max ${moved.toExponential(2)}`)
  const before = Float32Array.from(hair.geometry.getAttribute('position').array)
  fig.position.z += 0.05
  fig.updateMatrixWorld(true)
  h.update(1 / 60, { frozen: true })
  const after = hair.geometry.getAttribute('position').array
  check('[5] frozen: the position buffer unchanged, bit for bit', before.every((v, i) => Object.is(v, after[i])))
  h.dispose()
}

// [6] withoutHairGroups
{
  const payload = { rev: 'r1', groups: { hair_c00: { hair: true }, tail: {} } }
  const out = withoutHairGroups(payload)
  check('[6] hair groups dropped: keys [tail]', JSON.stringify(Object.keys(out.groups)) === '["tail"]')
  check('[6] rev r1:strands', out.rev === 'r1:strands' && out.rev.endsWith(':strands'))
  check('[6] the same input gives the same object; undefined stays undefined',
    withoutHairGroups(payload) === out && withoutHairGroups(undefined) === undefined)
}

// [7] excludeMesh
{
  const { fig, hair } = figure()
  const original = hair.material
  const gc = createGarmentCollision(THREE, fig, { version: 4, capsules: CAPSULES })
  const patched = hair.material, patchedDepth = hair.customDepthMaterial
  check('[7] the hair wears a patched clone', !!gc && patched !== original)
  gc.excludeMesh(hair, true)
  check('[7] excludeMesh(true): the original (unpatched) material is back', hair.material === original
    && hair.customDepthMaterial === undefined)
  gc.excludeMesh(hair, false)
  check('[7] excludeMesh(false): patched again, the same clone', hair.material === patched
    && hair.customDepthMaterial === patchedDepth)
  gc.dispose()
}

console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed')
process.exit(failures ? 1 : 0)
