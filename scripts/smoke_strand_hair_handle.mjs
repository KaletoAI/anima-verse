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
 *   (z0 0.05 > −0.10: no row is ever inside), the spike defaults as params. Capsules (the current
 *   `COLLISION_VERSION`): `head` (region head, Neck → Head, r 0.2) and `torso` (region torso, Spine2 → Neck, r 0.12).
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
 * [8] Ruling H-R10, the game's yaw snap (`faceTowards(dir, snap = true)`): the figure stands 30 frames, then turns
 *     90° about +Y in ONE frame (the head on the axis: no jump reset). The targets move > 0.1 m (the cards hang
 *     0.10 m behind the axis); `RootInertia` feels (2.5839 / 60) / 60 = 0.000718 rad of it and carries the rest, so
 *     after that update every row is within 1 mm of its target (without the carry a free row moved only d = 4 % of
 *     its target's 0.1 m in that step and the card flew out behind the turn).
 * [9] A figure bound away from where it was loaded (strand-hair Task 10: the 3D client places figures anywhere, the
 *     Hairstyles preview centres its model). The fixture is built at the origin (its skins bound there), then the
 *     figure stands at (2, 0, −3) before `createStrandHair`. three's default `attached` bind mode keeps
 *     `bindMatrixInverse` at inverse(matrixWorld) NOW, so the bind-pose capsule ends must come from inverse(
 *     `bindMatrix`) (here the identity): the torso capsule's bind ends stay (0, 1.30, 0) → (0, 1.45, 0) — not
 *     (−2, 1.30, 3) / (−4, 1.30, 6) as through the attached inverse once or twice. The rows of y 1.30 … 1.44 lie
 *     hypot(0.03, 0.10) = 0.1044 m from the torso axis, inside its 0.12 m: the bind rule shrinks the radius to that
 *     rest distance, so at rest nothing is pushed — 60 updates leave every row on its target within 1e-5 m (float32
 *     at 3 m). With the shifted ends the rule saw those rows far outside, kept r = 0.12 and pushed them out by
 *     ≈ 15.6 mm. The garment push has the same bind rule: `entries[0].local[torso].bind` of the placed figure
 *     equals the one at the origin within 1e-9.
 * [10] Ruling H-R11, 20 fps swings like 60 fps. The sim steps at a fixed 60 Hz; a 20 fps frame takes three steps,
 *     each at the pose of its own time between the last frame's and this one's (follow matrices and head slerped,
 *     capsule ends linear). MOTION, per 20 fps frame k (t from (k − 1)/20 to k/20 s): the figure turns about +Y at
 *     ω_k rad/s and walks along world +z at v_k m/s, both constant within the frame — ω_k = v_k = 0.02·k for
 *     k ≤ 30, 0.02·(60 − k) for 30 < k ≤ 60, 0 for k 61..100 (a turning walk up to 0.6 rad/s · 0.6 m/s, then 2 s
 *     of Stop); yaw and z are the integrals, piecewise linear in t with their kinks on the 20 fps frame ends. The
 *     60 fps run takes the same functions at j/60.
 *     WHY THEY AGREE: within a frame the figure's root is T(0, 0, z(t)) · Ry(yaw(t)), linear z and yaw — the slerp of
 *     the two frame-end matrices at s = 1/3, 2/3 IS the 60 fps frame's matrix (constant angular rate about a fixed
 *     axis, linear translation), so all three steps see the 60 fps run's targets, head and capsules. `RootInertia`
 *     carries the identity in both runs: its felt velocity reaches the real one when a change stays within
 *     accel · dt (2.4674/60 = 0.0411 m/s at 60 fps) and angAccel · dt (2.5839/60 = 0.0431 rad/s); here a frame
 *     changes v by 0.02 plus the turn of its direction in the root's frame, |v|·ω·dt ≤ 0.6 · 0.6 / 60 = 0.006 m/s,
 *     and ω by 0.02 — inside at 60 fps, and at 20 fps (three times the room, the same changes plus 0.018). So the two
 *     runs make the same arithmetic up to rounding: at every 20 fps frame end every row of the 20 fps run is within
 *     1 mm of the 60 fps run's at that time. ROUNDING: float32 rows, and the sim's thresholds (tether radius, angle
 *     limit, length clamp) turn a rounding difference into a different branch — measured on this fixture, the 60 fps
 *     walk of [11] started 1 m further along z (the same arithmetic, other roundings) ends 0.41 mm off the original
 *     after 2 s; 1 mm leaves room for that, not for a swing (b60293bd2: 13.9 mm here, 37.7 mm in [11]). The case is
 *     real: the free tips leave their targets > 5 mm in the walk. Fails on b60293bd2 (the frame-end pose held for
 *     all three steps).
 * [11] Ruling H-R11, a 10 fps frame (6/60 s) takes 4 steps over its last 4/60 s, the head's motion before them
 *     carried rigidly. The figure walks along +z at a constant 1 m/s from its first frame (reset on a 1 s frame),
 *     no turn. Per 10 fps frame: the head's first 2/60 s (0.0333 m) carry X, Xp and the last step's targets by the
 *     same translation — nothing relative to the targets changes (the step is Verlet in the target's frame, the
 *     colliders ride the head) — then 4 steps whose targets move 1/60 m each, exactly as 4 steps at 60 fps. So the
 *     10 fps run is the 60 fps run with a third of its time cut out: after 30 frames (3 s, 120 steps) every row's
 *     offset from its target X − T equals the 60 fps run's after 120 frames (2 s, 120 steps) within 1 mm (the
 *     rounding of [10]: rows at z ≈ 3 m against 2 m). The start
 *     swings (rows at rest, targets already moving): > 1 mm left after 2 s at 60 fps, so the case is real. Fails
 *     on b60293bd2: the frame's whole 0.1 m of target motion went into its first step and none into the other
 *     three, a kick every frame.
 * [12] A frame of 0.3 s (> STRAND_RESET_DELTA_S 0.25, a stalled tab) still resets: after it every row equals its
 *     target exactly.
 * [13] Review Focus 1 of CX1 (collision v5): a stored record keeps the capsule list its fit froze, under the version of
 *     that day — a record whose `capsules.version` is 4 still binds its colliders after the bump: capsuleIds ==
 *     ['torso'], the same list as [1] (the strand's own frozen copy is bound under `COLLISION_VERSION`, never under
 *     the record's version, which the version check of `bindCollision` would refuse). Fails on aaf2fc349 with only
 *     `COLLISION_VERSION` set to 5 (the colliders silently dropped: capsuleIds []).
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
const { COLLISION_VERSION } = await import('../packages/scene-render/src/collision.ts')

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

function record(cards = 2, capsuleVersion = COLLISION_VERSION) {
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
    capsules: { version: capsuleVersion, capsules: CAPSULES, scales: {} }, params: PARAMS,
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

// [8] a 90° yaw snap is carried
{
  const { fig } = figure()
  const h = createStrandHair(THREE, fig, record())
  h.setEnabled(true)
  for (let f = 0; f < 30; f++) { fig.updateMatrixWorld(true); h.update(1 / 60) }
  const before = Float32Array.from(h.targets)
  fig.rotation.y = Math.PI / 2
  fig.updateMatrixWorld(true)
  h.update(1 / 60)
  let moved = 0, err = 0
  for (let q = 0; q < h.sim.X.length; q += 3) {
    moved = Math.max(moved, Math.hypot(h.targets[q] - before[q], h.targets[q + 1] - before[q + 1], h.targets[q + 2] - before[q + 2]))
    err = Math.max(err, Math.hypot(h.sim.X[q] - h.targets[q], h.sim.X[q + 1] - h.targets[q + 1], h.sim.X[q + 2] - h.targets[q + 2]))
  }
  check('[8] the snap moved the targets > 0.1 m (the case is real)', moved > 0.1, `${moved.toFixed(4)} m`)
  check('[8] after the snap every row within 1 mm of its target (carried)', err <= 0.001, `${(err * 1000).toFixed(3)} mm`)
  h.dispose()
}

// [9] a figure bound away from where it was loaded
{
  const { fig } = figure()
  fig.position.set(2, 0, -3)
  fig.updateMatrixWorld(true)
  const h = createStrandHair(THREE, fig, record())
  h.setEnabled(true)
  for (let f = 0; f < 60; f++) { fig.updateMatrixWorld(true); h.update(1 / 60) }
  let err = 0
  for (let q = 0; q < h.sim.X.length; q += 3) {
    err = Math.max(err, Math.hypot(h.sim.X[q] - h.targets[q], h.sim.X[q + 1] - h.targets[q + 1], h.sim.X[q + 2] - h.targets[q + 2]))
  }
  check('[9] placed at (2, 0, −3): at rest every row on its target within 1e-5 m', err <= 1e-5, `${err.toExponential(2)} m`)
  h.dispose()
  const torsoBind = (placed) => {
    const { fig: g } = figure()
    if (placed) { g.position.set(2, 0, -3); g.updateMatrixWorld(true) }
    const gc = createGarmentCollision(THREE, g, { version: COLLISION_VERSION, capsules: CAPSULES })
    gc.update()
    const entry = gc.entries[0]
    const bind = entry.local[entry.capsules.findIndex(c => c.capsule.id === 'torso')].bind
    gc.dispose()
    return [...bind.a, ...bind.b]
  }
  const atOrigin = torsoBind(false), placed = torsoBind(true)
  const d = Math.max(...atOrigin.map((v, i) => Math.abs(v - placed[i])))
  check('[9] the garment bind rule: the placed torso bind ends = the ones at the origin (0, 1.30, 0) → (0, 1.45, 0)',
    d <= 1e-9 && Math.abs(atOrigin[1] - 1.30) < 1e-6 && Math.abs(atOrigin[4] - 1.45) < 1e-6 && Math.abs(atOrigin[0]) < 1e-9,
    `${atOrigin.map(v => +v.toFixed(4))} vs ${placed.map(v => +v.toFixed(4))}`)
}

// [10] .. [12] Ruling H-R11: the fixed 60 Hz step
{
  /** ω_k = v_k of 20 fps frame k (docstring [10]). */
  const rate = k => (k <= 30 ? 0.02 * k : k <= 60 ? 0.02 * (60 - k) : 0)
  /** yaw / z at time t: the integral of the piecewise-constant rate (kinks on the 20 fps frame ends). */
  const integral = t => {
    let sum = 0
    for (let k = 1; k <= 100; k++) {
      const a = (k - 1) / 20, b = k / 20
      if (t <= a) break
      sum += rate(k) * (Math.min(t, b) - a)
    }
    return sum
  }
  const run = fps => {
    const { fig } = figure()
    const h = createStrandHair(THREE, fig, record())
    h.setEnabled(true)
    h.update(1)
    const ends = []
    let tip = 0
    const frames = 100 * fps / 20
    for (let f = 1; f <= frames; f++) {
      const t = f / fps
      fig.rotation.y = integral(t)
      fig.position.z = integral(t)
      fig.updateMatrixWorld(true)
      h.update(1 / fps)
      for (let c = 0; c < 2; c++) {
        const q = 3 * (c * R + R - 1)
        tip = Math.max(tip, Math.hypot(h.sim.X[q] - h.targets[q], h.sim.X[q + 1] - h.targets[q + 1], h.sim.X[q + 2] - h.targets[q + 2]))
      }
      if (f % (fps / 20) === 0) ends.push(Float32Array.from(h.sim.X))
    }
    h.dispose()
    return { ends, tip }
  }
  const r60 = run(60), r20 = run(20)
  let worst = 0
  r20.ends.forEach((x, i) => { for (let q = 0; q < x.length; q++) worst = Math.max(worst, Math.abs(x[q] - r60.ends[i][q])) })
  check('[10] the turning walk swings the tips > 5 mm off their targets (the case is real)', r60.tip > 0.005,
    `${(r60.tip * 1000).toFixed(1)} mm`)
  check('[10] 20 fps = 60 fps: every row at every 20 fps frame end within 1 mm', worst <= 1e-3,
    `max ${worst.toExponential(2)} m`)

  /** The rows' offsets from their targets (X − T) after `seconds` of the 1 m/s walk at `fps`. */
  const walk = (fps, seconds) => {
    const { fig } = figure()
    const h = createStrandHair(THREE, fig, record())
    h.setEnabled(true)
    h.update(1)
    for (let f = 1; f <= seconds * fps; f++) {
      fig.position.z = f / fps
      fig.updateMatrixWorld(true)
      h.update(1 / fps)
    }
    const off = h.sim.X.map((x, q) => x - h.targets[q])
    h.dispose()
    return off
  }
  const w60 = walk(60, 2), w10 = walk(10, 3)
  let lag = 0, diff = 0
  for (let q = 0; q < w60.length; q += 3) {
    lag = Math.max(lag, Math.hypot(w60[q], w60[q + 1], w60[q + 2]))
    diff = Math.max(diff, Math.abs(w10[q] - w60[q]), Math.abs(w10[q + 1] - w60[q + 1]), Math.abs(w10[q + 2] - w60[q + 2]))
  }
  check('[11] 60 fps after 2 s: the start still swings > 1 mm (the case is real)', lag > 0.001, `${(lag * 1000).toFixed(3)} mm`)
  check('[11] 10 fps after 3 s (4 steps + the rigid carry per frame) = 60 fps after 2 s: X − T within 1 mm',
    diff <= 1e-3, `max ${diff.toExponential(2)} m`)

  const { fig } = figure()
  const h = createStrandHair(THREE, fig, record())
  h.setEnabled(true)
  for (let f = 1; f <= 30; f++) { fig.position.z = f / 60; fig.updateMatrixWorld(true); h.update(1 / 60) }
  fig.position.z += 0.3
  fig.updateMatrixWorld(true)
  h.update(0.3)
  let off = 0
  for (let q = 0; q < h.sim.X.length; q++) off = Math.max(off, Math.abs(h.sim.X[q] - h.targets[q]))
  check('[12] a 0.3 s frame resets: every row == its target', off === 0, `max ${off}`)
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
  const gc = createGarmentCollision(THREE, fig, { version: COLLISION_VERSION, capsules: CAPSULES })
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

// [13] a record of an older collision version keeps its colliders
{
  const { fig } = figure()
  const h = createStrandHair(THREE, fig, record(2, 4))
  check('[13] a capsules.version 4 record still binds its colliders: capsuleIds == the v4 list ["torso"]',
    JSON.stringify(h?.capsuleIds) === '["torso"]', JSON.stringify(h?.capsuleIds))
  h?.dispose()
}

console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed')
process.exit(failures ? 1 : 0)
