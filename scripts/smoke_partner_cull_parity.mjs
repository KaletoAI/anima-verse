#!/usr/bin/env node
/**
 * THE SHARED PARTNER CULL (cross-person collision plan Task 9b, `packages/scene-render/src/partnerContact.ts`
 * "the shared partner cull", `secondaryMotion.ts` PARTNER CAPSULES) changes the COST of partner contact, never a
 * result: this smoke runs the package of BASE (47579fee5, the per-chain `broadPhase` + `nearestCapsules`, the
 * allocating TypeScript push) and the current one side by side and demands equality BIT FOR BIT (`Object.is` on
 * every float, `===` on every key list).
 *
 * Usage: node scripts/smoke_partner_cull_parity.mjs   (no server, no world; bundles the current package and the
 *        BASE package from `git archive 47579fee5` with esbuild)
 *
 * FIXTURE (metres, bind rotations identity): Hips (0,0,0) → Spine (0,0.5,0) → Head (0,1.0,0). FOUR hair chains
 *   (two `hair: true` groups, three links each) hang from Head at (±0.06, 0.05, ±0.06), links 0.08 apart straight
 *   down; THREE extension chains (one group, two links each) hang from Hips at (−0.1/0/0.1, 0.4, −0.12), links 0.1
 *   apart backward-down. One vertex per link 0.03 past its last joint (the tips). Own capsules (collision version of
 *   the package): Hips→Spine r 0.12 `arm`, Spine→Head r 0.09 `arm`. Every group swings (gain 1, gravity 1,
 *   max_deg 30). So the hair consumer has four chains and the extension consumer three: both run the cull.
 * PARTNERS: four snapshots per frame (made anew each frame, as the client does), each 22 capsules of mixed regions
 *   (`arm`, `torso`, `outer_trunk`, `chest_hair`, `shoulder_hair` — the hair-only ones and the `torso` drop
 *   exercise both consumer filters), clustered so that a hair chain keeps MORE than `COLLIDE_MAX` (16) of them and
 *   the farthest drop. They sweep at 0.5 m/s: in front and behind the head laterally (x −0.5 … +0.5), left and right
 *   approaching along x (a ±0.08 triangle wave about contact), while the body turns (Hips yaw 0.4·sin) — 240 frames,
 *   then 30 frames with `partners: []` (the release).
 *
 * [1] OUTPUTS: after every frame every bone's `matrixWorld` (the driven ones included) is equal between BASE and
 *     now, and so is `contactTips()` (bone, tip, partner keys, own capsule ids) — over all 270 frames. CONTROL: the
 *     fixture touches (some frame has a partner key in a row, and some hair chain keeps more than 16 capsules),
 *     so the equality is not that of two idle figures.
 * [2] PARTNER LISTS: for every frame's pool (both consumers) and every chain root joint of the fixture with its
 *     lever (and 40 seeded random joints and levers about the head and the hips), `chainPartners` over the whole pool
 *     returns the indices of BASE's `broadPhase` → `nearestCapsules(COLLIDE_MAX)` → pool order, and over the CULLED
 *     list (`cullPartnerList` about the joints' mean, radius covering joint + lever) the same capsules (keys).
 * [3] REGION FILTER ONCE: `consumerPartnerCapsules('hair' | 'extension', partners)` equals BASE's inline
 *     `partnerCapsules(consumer, snap.capsules.map(c => ({ capsule: c })))` per snapshot — the same `now` objects in
 *     the same order — and a second call on the same snapshot returns the same lists (the memo).
 * [4] THE PUSH: `pushOutOfCapsules` (the early exit of the ordinary passes, the scratch buffers) equals BASE for
 *     5000 seeded points against seeded capsule lists of 1–20 capsules, with and without the SQUEEZE rule, with the
 *     bind rule (a `bind` capsule and `bindP`), with `partners`, and with a weight of 0.5.
 * TEETH (tried by hand on the change): the secondary motion culling 0.15 m tighter than the sphere its chains are
 * checked against, or capping a chain at 15 instead of `COLLIDE_MAX`, fails both [1] checks within the first 40
 * frames. A smaller cull SPHERE alone passes, by design: a chain outside it reads the whole pool.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import assert from 'node:assert/strict'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
/** The commit before the shared cull: per-chain `broadPhase` + `nearestCapsules`, the allocating push. */
const BASE = '47579fee573001283ff6620ba4c7e830a5da0966'

async function bundle(dir, srcRoot, name) {
  const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
  const src = join(srcRoot, 'packages/scene-render/src')
  const built = await esbuild.build({
    stdin: { contents: `export * from '${src}/index.ts';`, resolveDir: srcRoot, loader: 'ts' },
    bundle: true, platform: 'node', format: 'esm', write: false,
    outfile: join(dir, `${name}.mjs`), external: ['three', 'three/*'], logLevel: 'error',
  })
  const file = join(dir, `${name}.mjs`)
  await writeFile(file, built.outputFiles[0].text, 'utf8')
  return await import(`file://${file}`)
}

async function loadPackages() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-partner-cull-'))
  try {
    const now = await bundle(dir, ROOT, 'now')
    const base = join(dir, 'base')
    await mkdir(base)
    const tar = spawnSync('sh', ['-c', `git -C "${ROOT}" archive ${BASE} packages/scene-render/src | tar -x -C "${base}"`],
      { stdio: 'inherit' })
    assert.equal(tar.status, 0, `git archive ${BASE} failed`)
    const old = await bundle(dir, base, 'base')
    return { now, old }
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
/** A seeded generator (Park–Miller), so every run checks the same numbers. */
function seeded(seed) {
  let s = seed
  return () => (s = (s * 16807) % 2147483647) / 2147483647
}

const THREE = await import('three')
const { now: NOW, old: OLD } = await loadPackages()

const defaults = { freq_hz: 2, zeta: 0.6, gravity: 1, gravity_scale: 1, gain: 1,
  max_deg: 30, sag_max_deg: 30, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1 }
const HAIR = [[0.06, 0.06], [-0.06, 0.06], [0.06, -0.06], [-0.06, -0.06]]
const TAILS = [-0.1, 0, 0.1]

function rig() {
  const root = new THREE.Group()
  const bones = []
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = `mixamorig:${name}`; b.position.set(...at); (parent ?? root).add(b); bones.push(b); return b
  }
  const hips = bone('Hips', null, [0, 0, 0])
  const spine = bone('Spine', hips, [0, 0.5, 0])
  const head = bone('Head', spine, [0, 0.5, 0])
  const positions = [], links = []
  HAIR.forEach(([x, z], k) => {
    let parent = bone(`H${k}_1`, head, [x, 0.05, z]); links.push([parent, [0, -0.11, 0]])
    for (let j = 2; j <= 3; j++) { parent = bone(`H${k}_${j}`, parent, [0, -0.08, 0]); links.push([parent, [0, -0.03, 0]]) }
  })
  TAILS.forEach((x, k) => {
    const first = bone(`T${k}_1`, hips, [x, 0.4, -0.12]); links.push([first, [0, -0.06, -0.08]])
    const second = bone(`T${k}_2`, first, [0, -0.06, -0.08]); links.push([second, [0, -0.02, -0.03]])
  })
  // One vertex per link past its last joint (the tip of a chain's end; inner links take the next joint).
  const skinIndex = [], skinWeight = []
  root.updateMatrixWorld(true)
  for (const [b, off] of links) {
    const p = new THREE.Vector3(...off).applyMatrix4(b.matrixWorld)
    positions.push(p.x, p.y, p.z)
    skinIndex.push(bones.indexOf(b), 0, 0, 0); skinWeight.push(1, 0, 0, 0)
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(skinIndex, 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(skinWeight, 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton(bones))
  return { root, hips, head, bones }
}
const motionPayload = () => ({ rev: 'parity', groups: {
  hairA: { ...defaults, hair: true, bones: ['H0_1', 'H0_2', 'H0_3', 'H1_1', 'H1_2', 'H1_3'] },
  hairB: { ...defaults, hair: true, bones: ['H2_1', 'H2_2', 'H2_3', 'H3_1', 'H3_2', 'H3_3'] },
  tails: { ...defaults, bones: TAILS.flatMap((_, k) => [`T${k}_1`, `T${k}_2`]) },
} })
const collisionPayload = (version) => ({ version, capsules: [
  { id: 'lower', a: 'mixamorig:Hips', b: 'mixamorig:Spine', r: 0.12, region: 'arm' },
  { id: 'upper', a: 'mixamorig:Spine', b: 'mixamorig:Head', r: 0.09, region: 'arm' },
] })

/** One partner's 22 capsules about `centre` (world), short segments of mixed regions; seeded per partner. */
function partnerCapsules(centre, seed) {
  const rnd = seeded(seed)
  const regions = ['arm', 'arm', 'torso', 'outer_trunk', 'chest_hair', 'shoulder_hair', 'arm']
  return Array.from({ length: 22 }, (_, k) => {
    const a = [centre[0] + (rnd() - 0.5) * 0.3, centre[1] + (rnd() - 0.5) * 0.4, centre[2] + (rnd() - 0.5) * 0.3]
    const b = [a[0] + (rnd() - 0.5) * 0.15, a[1] + (rnd() - 0.5) * 0.2, a[2] + (rnd() - 0.5) * 0.15]
    return { id: `c${k}`, region: regions[k % regions.length], now: { a, b, r: 0.02 + 0.04 * rnd() } }
  })
}
const FRAMES = 240, RELEASE = 30, DT = 1 / 60, SPEED = 0.5
/** The four snapshots of frame f: front/back lateral passes, left/right approaches (module docstring). */
function partnersAt(f) {
  const t = f * DT
  const lateral = -0.5 + ((SPEED * t) % 1.0)
  const wave = 0.08 * (2 * Math.abs(((SPEED * t / 0.32) % 2) - 1) - 1)
  const places = [[lateral, 0.95, 0.14], [-lateral, 0.95, -0.16], [0.16 + wave, 0.9, 0], [-0.16 - wave, 0.75, -0.1]]
  return places.map((c, k) => ({ name: `p${k}`, channels: [], interaction: null, capsules: partnerCapsules(c, 11 + k) }))
}

// [1] outputs over the sweep ------------------------------------------------------------------------------------
let poolsSeen = []
{
  const a = rig(), b = rig()
  const mA = OLD.createSecondaryMotion(THREE, a.root, motionPayload())
  const mB = NOW.createSecondaryMotion(THREE, b.root, motionPayload())
  mA.setCollision(collisionPayload(OLD.COLLISION_VERSION))
  mB.setCollision(collisionPayload(NOW.COLLISION_VERSION))
  let same = true, rows = true, detail = '', touched = 0
  for (let f = 0; f < FRAMES + RELEASE; f++) {
    const yaw = 0.4 * Math.sin(f / 20)
    a.hips.rotation.set(0, yaw, 0); b.hips.rotation.set(0, yaw, 0)
    const partners = f < FRAMES ? partnersAt(f) : []
    mA.update(DT, { partners })
    mB.update(DT, { partners })
    if (f < FRAMES && f % 8 === 0) poolsSeen.push({ partners, joints: b.bones.filter(x => /_1$/.test(x.name)).map(x => {
      const p = new THREE.Vector3().setFromMatrixPosition(x.matrixWorld); return [p.x, p.y, p.z] }) })
    for (let i = 0; i < a.bones.length; i++) {
      const ea = a.bones[i].matrixWorld.elements, eb = b.bones[i].matrixWorld.elements
      if (!ea.every((x, j) => Object.is(x, eb[j]))) { if (same) detail = `frame ${f} ${a.bones[i].name}`; same = false }
    }
    const ta = JSON.stringify(mA.contactTips()), tb = JSON.stringify(mB.contactTips())
    if (ta !== tb) { if (rows) detail ||= `frame ${f} contactTips`; rows = false }
    if (mB.contactTips().some(r => r.partner.length)) touched++
  }
  check('[1] every bone matrixWorld equals BASE bit for bit (240 sweep + 30 release frames)', same, detail)
  check('[1] contactTips() (tips, partner keys, own ids) equal BASE every frame', rows, detail)
  check('[1] control: partner contact happens', touched > 20, `${touched} frames with a partner key`)
}

// [2] partner lists --------------------------------------------------------------------------------------------
{
  const COLLIDE_MAX = NOW.COLLIDE_MAX
  const rnd = seeded(7)
  let equal = true, culled = true, over = 0, cases = 0, detail = ''
  const out = [], dist = []
  const pool = NOW.createPartnerList(), cut = NOW.createPartnerList()
  for (const { partners, joints } of poolsSeen) {
    for (const consumer of ['hair', 'extension']) {
      NOW.fillPartnerList(pool, consumer, partners)
      const nows = pool.nows.slice(0, pool.n)
      const probes = joints.map(j => [j, 0.25])
      for (let k = 0; k < 40; k++) {
        const c = k % 2 ? [0, 1.0, 0] : [0, 0.4, -0.12]
        probes.push([[c[0] + (rnd() - 0.5) * 0.4, c[1] + (rnd() - 0.5) * 0.4, c[2] + (rnd() - 0.5) * 0.4], 0.05 + 0.4 * rnd()])
      }
      // The cull about the joints' mean, radius covering every probe's joint + lever.
      const centre = [0, 0, 0]
      for (const [j] of probes) for (let d = 0; d < 3; d++) centre[d] += j[d] / probes.length
      let radius = 0
      for (const [j, lever] of probes) radius = Math.max(radius, Math.hypot(j[0] - centre[0], j[1] - centre[1], j[2] - centre[2]) + lever)
      NOW.cullPartnerList(pool, centre, radius, cut)
      for (const [joint, lever] of probes) {
        cases++
        let want = OLD.broadPhase(joint, lever, nows)
        if (want.length > COLLIDE_MAX) {
          over++
          const all = want
          want = OLD.nearestCapsules({ c: joint, r: 0 }, all.map(i => nows[i]), COLLIDE_MAX).map(k => all[k]).sort((p, q) => p - q)
        }
        const n = NOW.chainPartners(pool, joint, lever, COLLIDE_MAX, out, dist)
        const got = out.slice(0, n)
        if (JSON.stringify(got) !== JSON.stringify(want)) { if (equal) detail = `${consumer} ${JSON.stringify(joint)} ${lever}`; equal = false }
        const m = NOW.chainPartners(cut, joint, lever, COLLIDE_MAX, out, dist)
        const keys = out.slice(0, m).map(i => cut.keys[i]).join()
        if (keys !== want.map(i => pool.keys[i]).join()) { if (culled) detail ||= `culled ${consumer} ${JSON.stringify(joint)}`; culled = false }
      }
    }
  }
  check('[2] chainPartners = BASE broadPhase → nearestCapsules → pool order, every case', equal, `${cases} cases; ${detail}`)
  check('[2] the culled list keeps the same capsules', culled, detail)
  check('[2] control: the cap bites (more than COLLIDE_MAX kept)', over > 10, `${over} cases over ${COLLIDE_MAX}`)
}

// [3] the region filter once per snapshot ------------------------------------------------------------------------
{
  const partners = partnersAt(17)
  let same = true
  for (const consumer of ['hair', 'extension']) {
    const want = []
    for (const snap of partners) {
      for (const { capsule } of OLD.partnerCapsules(consumer, snap.capsules.map(capsule => ({ capsule })))) want.push(capsule.now)
    }
    const got = NOW.consumerPartnerCapsules(consumer, partners)
    if (got.length !== want.length || got.some((c, i) => c !== want[i])) same = false
  }
  check('[3] consumerPartnerCapsules = BASE inline partnerCapsules, both consumers (same objects, same order)', same)
  const first = NOW.snapshotPartnerLists(partners[0]), again = NOW.snapshotPartnerLists(partners[0])
  check('[3] one snapshot is filtered once (the memo hands back the same lists)', first === again)
  const hair = NOW.consumerPartnerCapsules('hair', partners).length, ext = NOW.consumerPartnerCapsules('extension', partners).length
  check('[3] control: the consumers differ (hair-only regions, torso drop)', hair > ext, `hair ${hair}, extension ${ext}`)
}

// [4] the push ---------------------------------------------------------------------------------------------------
{
  const rnd = seeded(3)
  const cap = () => {
    const a = [rnd() - 0.5, rnd() - 0.5, rnd() - 0.5]
    return { a, b: [a[0] + (rnd() - 0.5) * 0.4, a[1] + (rnd() - 0.5) * 0.4, a[2] + (rnd() - 0.5) * 0.4], r: 0.05 + 0.2 * rnd() }
  }
  let same = true, moved = 0, detail = ''
  for (let k = 0; k < 5000; k++) {
    const list = Array.from({ length: 1 + Math.floor(rnd() * 20) }, cap)
    if (k % 3 === 0) list[0] = { ...list[0], bind: cap() }
    const p = [(rnd() - 0.5) * 0.8, (rnd() - 0.5) * 0.8, (rnd() - 0.5) * 0.8]
    const bindP = k % 3 === 0 ? [p[0] + 0.01, p[1], p[2]] : undefined
    const options = [undefined, { squeeze: true }, { squeeze: true, partners: Array.from({ length: 1 + (k % 10) }, cap) }, { partners: [cap()] }][k % 4]
    const weight = k % 5 === 0 ? 0.5 : 1
    const want = OLD.pushOutOfCapsules(p, list, weight, bindP, options)
    const got = NOW.pushOutOfCapsules(p, list, weight, bindP, options)
    if (!want.every((x, i) => Object.is(x, got[i]))) { if (same) detail = `case ${k}`; same = false }
    if (want.some((x, i) => x !== p[i])) moved++
  }
  check('[4] pushOutOfCapsules = BASE bit for bit (5000 cases: passes, squeeze, bind rule, partners, weight)', same, detail)
  check('[4] control: points are pushed', moved > 1000, `${moved} moved`)
}

console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed')
process.exit(failures ? 1 : 0)
