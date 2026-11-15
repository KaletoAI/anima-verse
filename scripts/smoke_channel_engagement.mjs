#!/usr/bin/env node
/**
 * CHANNEL ENGAGEMENT in the solver (`SecondaryMotion.update(dt, { partners, interaction })`,
 * packages/scene-render/src/secondaryMotion.ts, contract header "CHANNELS"; the rule in `channels.ts`; spec
 * docs/superpowers/specs/2026-11-13-cross-person-collision-design.md Part 4 "Guidance rule", plan Task 14).
 * Every expected number is derived BY HAND below from the geometry (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_channel_engagement.mjs   (no server, no world; bundles the current package and the
 *        BASE package from `git archive a0e50ae66` with esbuild — BASE only for the parity section [7])
 *
 * FIXTURE (metres, bind rotations identity, dt 1/60 s). Reader: Hips → A1 → A2 → A3, A1 at (x, 0, 0) under Hips
 *   (x = δ, the chain's offset from the channel axis), A2 and A3 0.1 further along +z each; two vertices per link,
 *   at its joint and 0.1 further along +z, skinned 1 to it. So every lever is 0.1 along +z (A1 → A2, A2 → A3, and
 *   A3's tip = its own vertex reaching farthest along its centroid lever, (0, 0, 0.1) in its frame) and the chain's
 *   tip lies 0.3 ahead of A1. One group `g`: op `appendage_chain`, length 1.0, gravity 0, gain 0 (no swing, no sag:
 *   every frame is the bind pose carried by Hips, so every turn below is the channel's or a partner's alone),
 *   max_deg 25. Swing budget per link = 25° × its motion share; spans 0.1, 0.1, 2 × 0.05 = 0.1 → shares ∝ 0.3²·0.1,
 *   0.2²·0.1, 0.1²·0.1 = 0.009 : 0.004 : 0.001 → budgets 16.07°, 7.14°, 1.79°. Own collision payload: one
 *   `appendage` capsule per link, start joint = the link, r 0.005 → r_c = 0.005 (Hips unscaled, girth 1); they
 *   ride the chain itself, so no own capsule pushes it.
 * PARTNER `p`: a snapshot with the channel CH (D2 geometry, moved so its funnel faces the chain): O = (0, 0, 0),
 *   u = +z, R 0.02, D 0.12, α 30°, F 0.05, accepts [appendage_chain], min_length 1.0, compress_min 0.8,
 *   interaction_kinds [k], suppress [cap_s]; the interaction {i1, k} on both sides. Hips at z = zH puts the joints at
 *   s = zH, zH + 0.1, zH + 0.2 and the tip at zH + 0.3 (ρ = δ for all).
 *   R' in C = R − r_c = 0.015; in the funnel R'(s) = 0.02 + (−s)·tan 30° − 0.005.
 * ENGAGEMENT TIMING: an update steps engagement BEFORE its solve on the zone the chain's tips were rendered in the
 *   previous update — so the first update in which a tip is in Φ ∪ C is followed by the first one with w > 0, and
 *   w = n · (1/60)/0.2 = n/12 in the n-th engaged update (1 after twelve).
 *
 * [1] ADVANCE, δ 0.017: zH = −0.40 + 0.16·f/30 (f = 1 … 30, the tip from s −0.0947 to 0.06), then held 20 frames.
 *     The tip enters Φ when s ≥ −F = −0.05 ⇔ f ≥ 9.375 (ρ 0.017 ≤ R'(s) there): at f = 10, s = −0.04667. So the
 *     first update with a `channel` row is f = 11, w = 1/12 (±1e-9), the row names `pkg:chan`; w = 1 (±1e-9) at
 *     f = 22, 0.2 s after the engaging update's start; while w = 1 every link tip with s ≥ −F keeps
 *     ρ ≤ R'(s) + 1 mm. (With w = 1 the tip link, its tip in C at ρ 0.017 > 0.015, turns about its joint by
 *     asin(0.002/0.1) = 1.146° < its 1.79° budget → ρ 0.015 exactly; the other tips lie in front of Φ or in it
 *     with ρ 0.017 < R'(s).)
 * [2] SUPPRESSION, static at zH −0.21, δ 0.017, after 40 frames (w = 1, the held partner turns released): the A2
 *     tip lies in Φ at s −0.01 with ρ 0.017 < R'(−0.01) = 0.015 + 0.01·tan 30° = 0.020774 (no turn); the A3 tip at
 *     s 0.09 is in C with ρ 0.017 > 0.015, so A3 turns about its joint (s −0.01) by asin(0.002/0.1) = 1.146°
 *     (budget 1.79°): the guided tip lies at (0.015, 0, −0.01 + 0.1·cos 1.146°) = (0.015, 0, 0.08998). A capsule
 *     along z from (0.03, 0, 0.05) to (0.03, 0, 0.15), r 0.02, holds it 5 mm deep (distance 0.015) and pushes
 *     towards −x. Named `cap_s` (in `suppress`): no push — the chain's bones equal, bit for bit, those of the same
 *     run with no partner capsule at all, and no row names `p:cap_s`. The same capsule named `cap_u`: it pushes
 *     (the A3 row names `p:cap_u`; the A3 tip moves ≥ 1 mm off the suppressed run's — out to x ≤ 0.01 needs
 *     more than the 1.79° budget, which moves it 0.1·sin 1.79° ≈ 3 mm). The A2 tip (0.017, 0, −0.01) lies
 *     √(0.013² + 0.06²) = 0.0614 from that segment: only A3 is touched.
 * [3] OWN CHANNEL: the reader's OWN collision payload carries a channel (Hips, opening (δ, 0, 0.25), bottom
 *     (δ, 0, 0.37), r 0.02 — it binds: `bindChannels` gives one channel) right where its chain lies (tip at s 0.3 −
 *     0.25 = 0.05 inside it), interaction i1, and a partner `p` without channels in the same interaction: over 30
 *     frames no row has `channel` and the bones equal those of a reader whose payload has no channel.
 * [4] RELEASE (Review Focus 4), static at zH −0.18, δ 0.017: joints at s −0.18, −0.08, 0.02, tip 0.12 (ρ 0.017,
 *     in C). w = 1 from the 13th update on. Then, by hand at w = 1: the A1 tip (s −0.08 < −F) is not guided; the
 *     A2 tip (s 0.02, ρ 0.017 > R' 0.015) turns A2 by asin(0.02) = 1.14593° (budget 7.14°) → joint A3 at
 *     (0.015, 0, −0.08 + 0.1·cos 1.14593°) = (0.015, 0, 0.019980); the A3 tip rides it to ρ 0.013 ≤ R' (no turn),
 *     s 0.019980 + 0.099980 = 0.119960 > D − r_c = 0.115 → s_e = 0.019980 (A3's joint, the first at s ≥ 0),
 *     k = max(0.8, (0.115 − 0.019980)/(0.119960 − 0.019980)) = 0.950390 → the tip at s 0.115 (±1e-6), x 0.015 −
 *     0.950390 · 0.002 = 0.013099 (±1e-6); its row says k 0.950390 (±1e-5). Then `interaction: null`: w falls by
 *     1/12 an update (linear, ±1e-9) to 0 in 12 updates, the A3 tip moves ≤ 1 mm a frame (the free chain moves
 *     0; the whole way back is √(0.0039² + 0.005²) = 6.3 mm), the row's k climbs to 1, and once w = 0 every bone
 *     equals, bit for bit, a reader that never had an interaction (the spring state was never touched).
 * [5] PASSER-BY: the [2] scene with `cap_s` (the unguided A3 tip 0.013 from its axis, 7 mm deep) and (a) the reader without an interaction, (b) the partner without one,
 *     (c) the group's length 0.9 < min_length 1.0 (the levers 0.09): never a `channel` row, the capsule pushes
 *     (A3's row names `p:cap_s`), and the bones equal those of the same run with a partner WITHOUT channels.
 *     And the [1] advance without an interaction: never a `channel` row.
 * [6] A GROWING EXTENT, δ 0 (on the axis: no radial turn, so the guided chain is the free one but for k), static at
 *     zH −0.18, engaged (w = 1), then at update 20 the group's length → 1.4 (blended over 1.5 s). Joints at s
 *     −0.18, −0.18 + 0.1λ, −0.18 + 0.2λ, tip −0.18 + 0.3λ. Every update the tip lies at
 *     s_e + k(s_raw − s_e), k = max(0.8, (0.115 − s_e)/(s_raw − s_e)) (s_raw, s_e from the free reader's joints;
 *     ±1e-6), i.e. at most D − r_c plus what compress_min cannot absorb; no link folds (each lever·u > 0); w stays
 *     1. λ 1: s_e 0.02, s_raw 0.12, k 0.95, tip 0.115. λ 1.4: joints −0.18, −0.04, 0.10 → s_e 0.10, s_raw 0.24,
 *     k = max(0.8, 0.015/0.14) = 0.8 → tip 0.212, 97 mm past D − r_c, left there. Then the interaction ends: after
 *     the ramp every bone equals the free reader's bit for bit (swing state untouched).
 *     PAST THE BOTTOM (ruling for Task 14): a ONE-link chain B1 (joint at s −0.02, lever 0.1, tip s 0.08, in C)
 *     engages; its length then grows to 1.6 → tip s −0.02 + 0.16 = 0.14 > D. No joint lies at s ≥ 0, so k = 1 and
 *     the tip stays past the bottom — and the chain stays ENGAGED (w = 1) for the whole growth and 1 s after: a tip
 *     with s > D counts as inside the grown release zone (ρ 0 ≤ R + h).
 * [7] PARITY with BASE (a0e50ae66, before this task): with no channel in any payload every output is BIT-IDENTICAL —
 *     over the [1] advance with `cap_u` on the way and a swinging variant (gain 1, gravity 1, Hips turning) against
 *     a moving partner capsule, with the reader's interaction passed (BASE ignores it) and partners with
 *     `channels: []`: every bone's matrixWorld (`Object.is`) and `contactTips()` (JSON) equal BASE every frame. And
 *     the passer-by: a partner WITH a channel but the reader without an interaction equals BASE fed the same
 *     snapshot. CONTROL: the runs do touch (rows name a partner capsule).
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import assert from 'node:assert/strict'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
/** The commit before this task: the solver without channel engagement. */
const BASE = 'a0e50ae662b1bbf33b799f326f5a3845b1ad2ebb'

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
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-channel-engagement-'))
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
const near = (x, want, tol) => typeof x === 'number' && Math.abs(x - want) <= tol

const THREE = await import('three')
const { now: NOW, old: OLD } = await loadPackages()

const DT = 1 / 60
const DEG = Math.PI / 180
const defaults = { freq_hz: 2, zeta: 1, gravity: 0, gravity_scale: 1, gain: 0,
  max_deg: 25, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1 }

/** The reader: Hips → `links` links of 0.1 along +z from (x, 0, z0), two vertices per link (module docstring). */
function rig({ x = 0.017, links = 3, z0 = 0, prefix = 'A' } = {}) {
  const root = new THREE.Group()
  const bones = []
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = `mixamorig:${name}`; b.position.set(...at); (parent ?? root).add(b); bones.push(b); return b
  }
  const hips = bone('Hips', null, [0, 0, 0])
  const chain = []
  let parent = hips
  for (let j = 0; j < links; j++) {
    parent = bone(`${prefix}${j + 1}`, parent, j ? [0, 0, 0.1] : [x, 0, z0])
    chain.push(parent)
  }
  const positions = [], skinIndex = [], skinWeight = []
  chain.forEach((b, j) => {
    for (const dz of [0, 0.1]) {
      positions.push(x, 0, z0 + 0.1 * j + dz)
      skinIndex.push(bones.indexOf(b), 0, 0, 0); skinWeight.push(1, 0, 0, 0)
    }
  })
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(skinIndex, 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(skinWeight, 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton(bones))
  return { root, hips, chain, bones, x, z0, prefix }
}
const group = (r, over = {}) => ({ rev: `g${JSON.stringify(over)}`, groups: { g: { ...defaults,
  bones: r.chain.map(b => b.name.replace('mixamorig:', '')), op: 'appendage_chain', ...over } } })
const ownPayload = (pkg, r, channels) => ({ version: pkg.COLLISION_VERSION,
  capsules: r.chain.map((b, j) => ({ id: `g:${b.name}`, a: b.name, b: (r.chain[j + 1] ?? b).name, r: 0.005,
    region: 'appendage', ...(r.chain[j + 1] ? {} : { b_pos: [r.x, 0, r.z0 + 0.1 * j + 0.1] }) })),
  ...(channels ? { channels } : {}) })
const CH = (over = {}) => ({ id: 'pkg:chan', o: [0, 0, 0], u: [0, 0, 1], depth: 0.12, r: 0.02, coneDeg: 30, funnel: 0.05,
  accepts: ['appendage_chain'], minLength: 1.0, compressMin: 0.8, kinds: ['k'], suppress: new Set(['cap_s']), ...over })
const I1 = { id: 'i1', kind: 'k' }
/** A fresh snapshot of `p` (as the client makes one each frame). */
const snap = ({ capsules = [], channels = [CH()], interaction = I1 } = {}) => ({ name: 'p', capsules, channels, interaction })
const capAlongZ = (id, x = 0.03) => ({ id, region: 'arm', now: { a: [x, 0, 0.05], b: [x, 0, 0.15], r: 0.02 } })

/** A reader made with package `pkg`: the rig, its motion (payload `over`), its own collision payload. */
function reader(pkg, { x = 0.017, links = 3, z0 = 0, over = {}, channels } = {}) {
  const r = rig({ x, links, z0 })
  const motion = pkg.createSecondaryMotion(THREE, r.root, group(r, over))
  motion.setCollision(ownPayload(pkg, r, channels))
  return { ...r, motion }
}
const place = (rd, zH) => { rd.hips.position.z = zH }
const step = (rd, partners, interaction = { id: 'i1' }) => rd.motion.update(DT, { partners, interaction })
/** World joint and tip of every link (the tip = 0.1 along the link's +z in its frame). */
const linksOf = (rd) => rd.chain.map(b => {
  const j = new THREE.Vector3().setFromMatrixPosition(b.matrixWorld)
  const t = new THREE.Vector3(0, 0, 0.1).applyMatrix4(b.matrixWorld)
  return { joint: j, tip: t }
})
const rowsOf = (rd) => rd.motion.contactTips()
const channelOf = (rd) => rowsOf(rd).find(r => r.channel)?.channel ?? null
const sameBones = (a, b) => a.bones.every((x, i) => x.matrixWorld.elements.every((e, k) => Object.is(e, b.bones[i].matrixWorld.elements[k])))
const sRho = (p) => ({ s: p.z, rho: Math.hypot(p.x, p.y) })
const allowed = (s) => Math.max(0, (s < 0 ? 0.02 + (-s) * Math.tan(30 * DEG) : 0.02) - 0.005)

console.log('--- [1] advance into the funnel ---')
{
  const rd = reader(NOW)
  let first = -1, firstW = NaN, oneAt = -1, names = new Set(), worst = -Infinity, wOneFrames = 0
  for (let f = 1; f <= 50; f++) {
    place(rd, -0.40 + 0.16 * Math.min(f, 30) / 30)
    step(rd, [snap()])
    const ch = channelOf(rd)
    if (ch) names.add(ch.id)
    if (ch && first < 0) { first = f; firstW = ch.w }
    if (ch && ch.w >= 1 - 1e-9 && oneAt < 0) oneAt = f
    if (ch && ch.w >= 1 - 1e-9) {
      wOneFrames++
      for (const { tip } of linksOf(rd)) {
        const { s, rho } = sRho(tip)
        if (s >= -0.05) worst = Math.max(worst, rho - allowed(s))
      }
    }
  }
  check('[1] first update with a channel row: f = 11, w = 1/12', first === 11 && near(firstW, 1 / 12, 1e-9), `f ${first} w ${firstW}`)
  check('[1] the row names the channel pkg:chan', names.size === 1 && names.has('pkg:chan'), [...names].join())
  check('[1] w = 1 at f = 22 — within CHANNEL_BLEND_S (12 updates of 1/60 s) of engaging', oneAt === 22, `f ${oneAt}`)
  check('[1] while w = 1 no tip (s ≥ −F) ends with ρ > R\'(s) + 1 mm', wOneFrames > 20 && worst <= 0.001,
    `${wOneFrames} frames, worst ρ − R' ${(worst * 1000).toFixed(4)} mm`)
}

console.log('--- [2] suppression ---')
{
  const run = (capsules) => {
    const rd = reader(NOW)
    place(rd, -0.21)
    let named = new Set()
    for (let f = 1; f <= 40; f++) {
      step(rd, [snap({ capsules: capsules.map(c => ({ ...c })) })])
      for (const row of rowsOf(rd)) for (const k of row.partner) named.add(`${row.bone}|${k}`)
    }
    return { rd, named, ch: channelOf(rd) }
  }
  const bare = run([]), sup = run([capAlongZ('cap_s')]), uns = run([capAlongZ('cap_u')])
  const tipBare = linksOf(bare.rd)[2].tip
  check('[2] engaged at w = 1, the guided tip at (0.015, 0, 0.08998)', bare.ch?.w === 1 &&
    near(tipBare.x, 0.015, 1e-6) && near(tipBare.z, 0.08998, 1e-6), `${tipBare.x.toFixed(6)}, ${tipBare.z.toFixed(6)}`)
  check('[2] cap_s (in suppress) does not push: bones equal the run without it', sameBones(sup.rd, bare.rd))
  check('[2] cap_s is never named in the last frame', !rowsOf(sup.rd).some(r => r.partner.includes('p:cap_s')))
  const tipU = linksOf(uns.rd)[2].tip
  const rowU = rowsOf(uns.rd).find(r => r.bone === 'mixamorig:A3')
  check('[2] cap_u (not in suppress) pushes the A3 tip', !!rowU && rowU.partner.includes('p:cap_u') &&
    tipU.distanceTo(tipBare) >= 0.001, `moved ${(tipU.distanceTo(tipBare) * 1000).toFixed(3)} mm, ${JSON.stringify(rowU?.partner)}`)
  check('[2] only A3 is touched by cap_u', [...uns.named].every(k => k.startsWith('mixamorig:A3|')), [...uns.named].join())
}

console.log('--- [3] the reader\'s own channel ---')
{
  const record = { id: 'own:chan', kind: 'channel', a: 'mixamorig:Hips', b: 'mixamorig:Hips', a_pos: [0.017, 0, 0.25],
    b_pos: [0.017, 0, 0.37], r: 0.02, cone_deg: 30, funnel: 0.05, accepts: ['appendage_chain'], min_length: 1,
    compress_min: 0.8, suppress: [], frame: { side: [1, 0, 0], up: [0, 1, 0], front: [0, 0, 1] }, placement: 'declared',
    applied: null }
  const own = reader(NOW, { channels: [record] }), plain = reader(NOW)
  const bound = NOW.bindChannels(THREE, own.root, ownPayload(NOW, own, [record]))
  check('[3] the own channel binds (one channel)', bound?.channels.length === 1)
  let rows = 0, same = true
  for (let f = 1; f <= 30; f++) {
    for (const rd of [own, plain]) step(rd, [snap({ channels: [], capsules: [] })])
    if (channelOf(own)) rows++
    if (!sameBones(own, plain)) same = false
  }
  check('[3] never engaged: no channel row in 30 frames', rows === 0, `${rows}`)
  check('[3] bones equal a reader without the own channel', same)
}

console.log('--- [4] the interaction ends while engaged ---')
{
  const rd = reader(NOW), free = reader(NOW)
  place(rd, -0.18); place(free, -0.18)
  let oneAt = -1
  for (let f = 1; f <= 30; f++) {
    step(rd, [snap()]); step(free, [snap()], null)
    if (oneAt < 0 && channelOf(rd)?.w >= 1 - 1e-9) oneAt = f
  }
  const ch = channelOf(rd)
  const tip = linksOf(rd)[2].tip
  check('[4] w = 1 from update 13 on', oneAt === 13 && ch?.w === 1, `f ${oneAt}`)
  check('[4] engaged tip at s 0.115, x 0.013099 (±1e-6)', near(tip.z, 0.115, 1e-6) && near(tip.x, 0.013099, 1e-6),
    `${tip.z.toFixed(7)}, ${tip.x.toFixed(7)}`)
  check('[4] the row says k 0.950390 (±1e-5)', near(ch?.k, 0.950390, 1e-5), String(ch?.k))
  const ws = [], ks = [], moves = []
  let prev = tip.clone(), prevFree = linksOf(free)[2].tip.clone()
  for (let f = 1; f <= 20; f++) {
    step(rd, [snap()], null); step(free, [snap()], null)
    const c = channelOf(rd)
    ws.push(c ? c.w : 0); ks.push(c ? c.k : 1)
    const t = linksOf(rd)[2].tip, tf = linksOf(free)[2].tip
    moves.push(t.distanceTo(prev) - tf.distanceTo(prevFree))
    prev = t.clone(); prevFree = tf.clone()
  }
  const linear = ws.slice(0, 12).every((w, i) => near(w, 1 - (i + 1) / 12, 1e-9))
  check('[4] w falls linearly by 1/12 an update to 0 in 12 updates', linear && ws.slice(13).every(w => w === 0),
    ws.slice(0, 13).map(w => w.toFixed(4)).join(' '))
  check('[4] the tip moves ≤ the free chain + 1 mm a frame', Math.max(...moves) <= 0.001,
    `max ${(Math.max(...moves) * 1000).toFixed(4)} mm`)
  check('[4] k climbs back to 1 with w', ks.every((k, i) => i === 0 || k >= ks[i - 1] - 1e-12) && ks.at(-1) === 1,
    ks.slice(0, 13).map(k => k.toFixed(5)).join(' '))
  check('[4] after the ramp every bone equals the free reader bit for bit (spring state untouched)', sameBones(rd, free))
}

console.log('--- [5] the passer-by ---')
{
  const cases = [
    ['(a) no reader interaction', {}, { id: null }, I1],
    ['(b) no partner interaction', {}, { id: 'i1' }, null],
    ['(c) length 0.9 < min_length', { length: 0.9 }, { id: 'i1' }, I1],
  ]
  for (const [label, over, mine, theirs] of cases) {
    const rd = reader(NOW, { over }), bare = reader(NOW, { over })
    place(rd, -0.21); place(bare, -0.21)
    let rows = 0, pushed = 0, same = true
    for (let f = 1; f <= 40; f++) {
      const interaction = mine.id ? { id: mine.id } : null
      step(rd, [snap({ capsules: [capAlongZ('cap_s')], interaction: theirs })], interaction)
      step(bare, [snap({ capsules: [capAlongZ('cap_s')], channels: [], interaction: theirs })], interaction)
      if (channelOf(rd)) rows++
      if (rowsOf(rd).some(r => r.partner.includes('p:cap_s'))) pushed++
      if (!sameBones(rd, bare)) same = false
    }
    check(`[5] ${label}: never engaged`, rows === 0, `${rows}`)
    check(`[5] ${label}: cap_s pushes (the passer-by rule)`, pushed > 0, `${pushed} frames`)
    check(`[5] ${label}: bones equal a partner without channels`, same)
  }
  const rd = reader(NOW)
  let rows = 0
  for (let f = 1; f <= 50; f++) {
    place(rd, -0.40 + 0.16 * Math.min(f, 30) / 30)
    step(rd, [snap()], null)
    if (channelOf(rd)) rows++
  }
  check('[5] the [1] advance without an interaction: never engaged', rows === 0, `${rows}`)
}

console.log('--- [6] a growing extent while engaged ---')
{
  const rd = reader(NOW, { x: 0 }), free = reader(NOW, { x: 0 })
  place(rd, -0.18); place(free, -0.18)
  let worst = 0, folded = false, wDrop = false, hand1 = null, hand14 = null
  for (let f = 1; f <= 140; f++) {
    if (f === 20) { rd.motion.configure(group(rd, { length: 1.4 })); free.motion.configure(group(free, { length: 1.4 })) }
    step(rd, [snap()]); step(free, [snap()], null)
    if (f < 13) continue
    if (channelOf(rd)?.w !== 1) wDrop = true
    const L = linksOf(rd), F = linksOf(free)
    const sRaw = F[2].tip.z, sE = F.map(l => l.joint.z).find(s => s >= 0)
    const k = sRaw > 0.115 ? Math.max(0.8, (0.115 - sE) / (sRaw - sE)) : 1
    const want = sE + k * (sRaw - sE)
    worst = Math.max(worst, Math.abs(L[2].tip.z - want))
    if (L.some(l => l.tip.z - l.joint.z <= 0)) folded = true
    if (f === 19) hand1 = L[2].tip.z
    if (f === 140) hand14 = L[2].tip.z
  }
  check('[6] the tip lies at s_e + k(s_raw − s_e) every update (±1e-6)', worst <= 1e-6, `worst ${worst.toExponential(2)}`)
  check('[6] λ 1: tip at 0.115; λ 1.4: tip at 0.212 (97 mm past, left there)', near(hand1, 0.115, 1e-6) &&
    near(hand14, 0.212, 1e-6), `${hand1?.toFixed(7)} / ${hand14?.toFixed(7)}`)
  check('[6] no link folds, w stays 1 through the growth', !folded && !wDrop)
  for (let f = 1; f <= 20; f++) { step(rd, [snap()], null); step(free, [snap()], null) }
  check('[6] after the release every bone equals the free reader (swing state untouched)', sameBones(rd, free))

  // Past the bottom: one link, joint at s −0.02 (z0 −0.02 under Hips at 0).
  const one = reader(NOW, { x: 0, links: 1, z0: -0.02 })
  let dropped = false, tipEnd = NaN
  for (let f = 1; f <= 240; f++) {
    if (f === 20) one.motion.configure(group(one, { length: 1.6 }))
    step(one, [snap()])
    if (f >= 13 && channelOf(one)?.w !== 1) dropped = true
    tipEnd = linksOf(one)[0].tip.z
  }
  check('[6] one link past the bottom: the tip at s 0.14 (> D, k 1)', near(tipEnd, 0.14, 1e-6), String(tipEnd))
  check('[6] one link past the bottom stays engaged (w 1) through the growth and 1 s after', !dropped)
}

console.log('--- [7] parity with BASE (no channels) ---')
{
  const runPair = (label, over, mover, partnersAt, interaction) => {
    const a = reader(OLD, { over }), b = reader(NOW, { over })
    let same = true, rows = true, touched = 0, detail = ''
    for (let f = 1; f <= 120; f++) {
      mover(a, f); mover(b, f)
      a.motion.update(DT, { partners: partnersAt(f) })
      b.motion.update(DT, { partners: partnersAt(f), interaction })
      if (!sameBones(a, b)) { if (same) detail = `frame ${f}`; same = false }
      const ta = JSON.stringify(a.motion.contactTips()), tb = JSON.stringify(b.motion.contactTips())
      if (ta !== tb) { if (rows) detail ||= `frame ${f} contactTips`; rows = false }
      if (b.motion.contactTips().some(r => r.partner.length)) touched++
    }
    check(`[7] ${label}: bones equal BASE bit for bit`, same, detail)
    check(`[7] ${label}: contactTips equal BASE`, rows, detail)
    check(`[7] ${label}: control — contact happens`, touched > 5, `${touched} frames`)
  }
  const advance = (rd, f) => place(rd, -0.40 + 0.16 * Math.min(f, 30) / 30)
  runPair('advance, channels []', {}, advance, () => [snap({ capsules: [capAlongZ('cap_u')], channels: [] })], { id: 'i1' })
  runPair('swinging, channels []', { gain: 1, gravity: 1 }, (rd, f) => {
    place(rd, -0.22); rd.hips.rotation.set(0, 0.3 * Math.sin(f / 15), 0.2 * Math.sin(f / 23))
  }, (f) => [snap({ capsules: [{ id: 'm', region: 'arm', now: { a: [0.05 * Math.sin(f / 10), -0.1, 0.06],
    b: [0.05 * Math.sin(f / 10), 0.1, 0.06], r: 0.03 } }], channels: [] })], { id: 'i1' })
  runPair('passer-by: a channel, no reader interaction', {}, advance,
    () => [snap({ capsules: [capAlongZ('cap_s')] })], null)
}

if (failures) { console.log(`\n${failures} check(s) FAILED`); process.exit(1) }
console.log('\nall channel engagement checks passed')
