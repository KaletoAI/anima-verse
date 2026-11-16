#!/usr/bin/env node
/**
 * Ruling A110 phase 3: the Library place preview's Collision / Channels readout says what client3d does. The SAME
 * two-figure setup runs through client3d's path (`Figure` — `play`, `setYaw`, `update` — and the shared
 * `runFigureFrame` over the figures, as `NpcManager.tickSecondary` calls it) and through the preview's path
 * (`frontend/src/tabs/poses/placeFigures.ts`: `mountPlaceFigure`, root placement, `runtime.poseStep`, `placePhaseB`);
 * every frame both are read by `FigureRuntime.inspect()` (client3d through `Figure.inspect()`) and `inspectFrame`.
 * Every expected number is derived BY HAND below from the geometry (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_place_preview_partners.mjs   (no server, no world; bundles both paths with esbuild)
 *
 * FIXTURE (metres; every bone's bind rotation identity; body box x ±0.15, z ±0.10, y 0 … 1.70 → the height is
 *   1.70 = FIGURE_HEIGHT_M, the box centred on x = z = 0 with its feet at y 0: `anchorFigureBind` scales by 1 and
 *   moves nothing, `Figure` (model scale 1) shifts nothing — the two owners hold the instance at the same place).
 *   Skeleton: Hips (0, 0.9, 0) → Spine2 (0, 1.3, 0); Hips → A1 at Hips + (0, 0, 0.15) → A2 (+0.1 z) → A3 (+0.1 z).
 *   Capsules (collision v7): torso Hips→Spine2 r 0.12; arm on Spine2 from a_pos (−0.1, y_arm, 0) to b_pos
 *   (−0.1, y_arm, 0.35), r 0.05; the chain's own `appendage` capsules A1→A2, A2→A3, A3→(0, 0.9, 0.45) r 0.005.
 *   P (the reader) has y_arm 1.30 and motion group g = [A1, A2, A3], op appendage_chain, gain 0, gravity 0 (a rigid
 *   chain, every move below is the guidance's). Q (the receiver) has y_arm 1.32 and ONE channel `pkg:chan` on
 *   Hips: opening (0, 0.9, 0.12), bottom (0, 0.9, 0.0) → u = −z, depth 0.12, r 0.02, cone 30°, funnel 0.05,
 *   accepts appendage_chain, min_length 1, compress_min 0.8, kinds [k], suppress [torso]; a ring of body vertices
 *   about the opening (radius 0.03, skinned to Hips) gives the opening its candidates.
 *   Q stands at the origin unturned. P stands at (0, 0, z_P) turned by π (its +z looks at Q): the chain's joints at
 *   world z = z_P − 0.15, − 0.25, − 0.35 and its tip at z_P − 0.45, all on the channel axis (x 0, y 0.9); P's arm
 *   at x = +0.1, y 1.30, z from z_P to z_P − 0.35. Both figures in the interaction {i1, k, [P, Q]}.
 *   Frame f = 1 … 90 (dt 1/60): z_P = 0.70 − 0.006·min(f, 25) (0.70 → 0.55 over 25 frames, then held).
 * HAND-DERIVED:
 *   [H1] ARM CONTACT. Q's arm runs z 0 … 0.35 at (0.1, 1.32), P's arm z_P − 0.35 … z_P at (0.1, 1.30): parallel,
 *        overlapping in z whenever z_P − 0.35 ≤ 0.35 (always here) → axis distance 0.02, depth 0.05 + 0.05 − 0.02 =
 *        0.08 m = 80.000 mm (±1e-6 m), every frame. The arms are the closest pair of P and Q (the chain's capsules
 *        overlap Q's torso by at most 0.12 + 0.005 − 0.10 = 0.025 at z_P 0.55: the tip at z 0.10).
 *   [H2] ENGAGEMENT. The tip at s = 0.12 − (z_P − 0.45) along u enters the funnel at s ≥ −0.05 ⇔ z_P ≤ 0.62 ⇔
 *        0.006·f ≥ 0.08 ⇔ f ≥ 13.33 → f = 14 (s −0.046, ρ 0); an update steps engagement on the zone of the previous
 *        render, so the first update with w > 0 is f = 15, w = 1/12, and w = 1 from f = 26 (12 engaged updates ×
 *        (1/60)/0.2). The tip ends at s 0.02 < D − r_c 0.115:
 *        no compression, on the axis: no radial turn.
 *   [H3] OPENING. The receiver opens `pkg:chan` around the chain's segments, radius r_c · w: at f ≥ 30 (w = 1, the
 *        budget of one recompute a frame has bound and applied by then) 0.005 m = 5.000 mm (±1e-6).
 * EQUALITY (the acceptance): every frame, client3d path vs preview path, ≤ 1e-6 — every capsule end and radius of
 *   both figures, Q's channel frame (o, u, r), the engagement rows (by, of, channel, w) and the opening radii, and
 *   the contact list (pairs + depths).
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function loadPaths() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-place-partners-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: [
        `export { Figure } from '${ROOT}/client3d/src/scene/figures';`,
        `export { mountPlaceFigure, placeInteraction, placePhaseB } from '${ROOT}/frontend/src/tabs/poses/placeFigures';`,
        "export { runFigureFrame, inspectFrame, COLLISION_VERSION, FIGURE_HEIGHT_M } from '@anima/scene-render';",
      ].join('\n'), resolveDir: join(ROOT, 'client3d'), loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'paths.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'paths.mjs')
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

const THREE = await import('three')
const { clone: skclone } = await import('three/examples/jsm/utils/SkeletonUtils.js')
const L = await loadPaths()
assert.equal(L.FIGURE_HEIGHT_M, 1.7, 'the fixture is 1.70 m tall so neither owner rescales it')

const DEFAULTS = { freq_hz: 2, zeta: 1, gravity: 0, gravity_scale: 1, gain: 0,
  max_deg: 25, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1 }
const MOTION = { rev: 'm1', groups: { g: { ...DEFAULTS, bones: ['A1', 'A2', 'A3'], op: 'appendage_chain' } } }

function template() {
  const fig = new THREE.Group()
  const bones = []
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = `mixamorig${name}`; b.position.set(...at); (parent ?? fig).add(b); bones.push(b); return b
  }
  const hips = bone('Hips', null, [0, 0.9, 0])
  bone('Spine2', hips, [0, 0.4, 0])
  const a1 = bone('A1', hips, [0, 0, 0.15])
  const a2 = bone('A2', a1, [0, 0, 0.1])
  bone('A3', a2, [0, 0, 0.1])
  fig.updateMatrixWorld(true)
  const pos = [], si = []
  const tri = (pts, b) => { for (const p of pts) { pos.push(...p); si.push(b, 0, 0, 0) } }
  tri([[-0.15, 0, -0.1], [0.15, 0, 0.1], [0, 1.7, 0]], 0)
  tri([[0.15, 0, -0.1], [-0.15, 0, 0.1], [0, 1.7, 0]], 0)
  tri([[0, 0.9, -0.45], [0, 0.9, -0.44], [0.001, 0.9, -0.45]], 0)   // the back twin of the chain's reach: box z ±0.45
  // the ring about the opening (0, 0.9, 0.12), radius 0.03
  const ring = Array.from({ length: 6 }, (_, k) => [0.03 * Math.cos(k * Math.PI / 3), 0.9 + 0.03 * Math.sin(k * Math.PI / 3), 0.12])
  tri([ring[0], ring[1], ring[2]], 0); tri([ring[3], ring[4], ring[5]], 0)
  tri([ring[0], ring[2], ring[4]], 0); tri([ring[1], ring[3], ring[5]], 0)
  // the chain's own skin (two vertices per link, skinned 1 to it) — its levers for the secondary motion
  ;[[a1, 2], [a2, 3]].forEach(([, b], j) => tri([[0, 0.9, 0.15 + 0.1 * j], [0, 0.9, 0.25 + 0.1 * j], [0.001, 0.9, 0.2 + 0.1 * j]], b))
  tri([[0, 0.9, 0.35], [0, 0.9, 0.45], [0.001, 0.9, 0.4]], 4)
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(pos.map((_, i) => (i % 3 === 2 ? 1 : 0)), 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(si, 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(si.map((_, i) => (i % 4 === 0 ? 1 : 0)), 4))
  const body = new THREE.SkinnedMesh(geo, new THREE.MeshStandardMaterial()); body.name = 'body'
  fig.add(body)
  fig.updateMatrixWorld(true)
  body.bind(new THREE.Skeleton(bones), body.matrixWorld)
  return fig
}
function collision(xArm, yArm, channel) {
  const caps = [
    { id: 'torso', a: 'mixamorigHips', b: 'mixamorigSpine2', r: 0.12, region: 'torso' },
    { id: 'arm', a: 'mixamorigSpine2', b: 'mixamorigSpine2', a_pos: [xArm, yArm, 0], b_pos: [xArm, yArm, 0.35], r: 0.05, region: 'arm' },
    { id: 'g:A1', a: 'mixamorigA1', b: 'mixamorigA2', r: 0.005, region: 'appendage' },
    { id: 'g:A2', a: 'mixamorigA2', b: 'mixamorigA3', r: 0.005, region: 'appendage' },
    { id: 'g:A3', a: 'mixamorigA3', b: 'mixamorigA3', b_pos: [0, 0.9, 0.45], r: 0.005, region: 'appendage' },
  ]
  return { version: L.COLLISION_VERSION, capsules: caps, ...(channel ? { channels: [{
    id: 'pkg:chan', kind: 'channel', a: 'mixamorigHips', b: 'mixamorigHips', a_pos: [0, 0.9, 0.12], b_pos: [0, 0.9, 0],
    r: 0.02, cone_deg: 30, funnel: 0.05, accepts: ['appendage_chain'], min_length: 1, compress_min: 0.8,
    interaction_kinds: ['k'], suppress: ['torso'], frame: { side: [1, 0, 0], up: [0, 1, 0], front: [0, 0, 1] },
    placement: 'declared', applied: null }] } : {}) }
}
const still = () => new THREE.AnimationClip('standing', 1,
  [new THREE.QuaternionKeyframeTrack('mixamorigSpine2.quaternion', [0, 1], [0, 0, 0, 1, 0, 0, 0, 1])])
const zP = f => 0.70 - 0.006 * Math.min(f, 25)
const FRAMES = 90, DT = 1 / 60
const MEMBERS = ['P', 'Q']

function clientPath() {
  const make = (xArm, yArm, channel, motion) => {
    const f = new L.Figure({ motion: motion ? { payload: MOTION } : null, collision: collision(xArm, yArm, channel),
      footPose: null, hairStrands: null, name: 'Fixture', template: template(), clips: [still()], scale: 1, height: 1.7,
      assignOnly: true, noClips: false, tier: 'full', libraryFits: false })
    f.play('standing')
    return f
  }
  const p = make(0.1, 1.30, false, true), q = make(-0.1, 1.32, true, false)
  p.root.rotation.y = Math.PI; p.setYaw(Math.PI)
  q.root.rotation.y = 0; q.setYaw(0)
  const interaction = { id: 'i1', kind: 'k', members: MEMBERS }
  const state = { openingTurn: 0 }
  const out = []
  for (let f = 1; f <= FRAMES; f++) {
    p.root.position.set(0, 0, zP(f))
    q.root.position.set(0, 0, 0)
    for (const fig of [p, q]) fig.update(DT, { realDelta: DT })
    L.runFigureFrame([{ name: 'P', interaction, figure: p }, { name: 'Q', interaction, figure: q }], state)
    const ins = { P: p.inspect(), Q: q.inspect() }
    out.push({ ins, frame: L.inspectFrame([{ name: 'P', inspection: ins.P }, { name: 'Q', inspection: ins.Q }]) })
  }
  p.dispose(); q.dispose()
  return out
}

function previewPath() {
  const make = (xArm, yArm, channel, motion) => L.mountPlaceFigure(THREE, skclone, template(),
    { collision: collision(xArm, yArm, channel), motion: () => (motion ? MOTION : undefined) })
  const p = make(0.1, 1.30, false, true), q = make(-0.1, 1.32, true, false)
  const mixers = [p, q].map(fig => { const m = new THREE.AnimationMixer(fig.inst); m.clipAction(still()).play(); return m })
  const interaction = L.placeInteraction('k', 'i1', MEMBERS)
  const state = { openingTurn: 0 }
  const out = []
  let time = 0
  for (let f = 1; f <= FRAMES; f++) {
    time = (time + DT) % 1
    mixers.forEach(m => m.setTime(time))
    p.root.position.set(0, 0, zP(f)); p.root.rotation.set(0, Math.PI, 0, 'YXZ'); p.root.updateMatrixWorld(true)
    q.root.position.set(0, 0, 0); q.root.updateMatrixWorld(true)
    p.runtime.poseStep({ realDelta: DT }); q.runtime.poseStep({ realDelta: DT })
    const res = L.placePhaseB([{ name: 'P', interaction, figure: p.runtime }, { name: 'Q', interaction, figure: q.runtime }], state, true)
    out.push({ ins: { P: res.figures[0].inspection, Q: res.figures[1].inspection }, frame: res.frame })
  }
  p.runtime.dispose(); q.runtime.dispose()
  return out
}

const A = clientPath(), B = previewPath()
let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
// --- equality -----------------------------------------------------------------------------------------------------
let engagedFrames = 0, maxCap = 0, maxCh = 0, maxW = 0, maxOpen = 0, maxDepth = 0, sameShape = true
const diff = (x, y) => Math.abs(x - y)
for (let k = 0; k < FRAMES; k++) {
  const a = A[k], b = B[k]
  for (const n of MEMBERS) {
    const ca = a.ins[n].capsules, cb = b.ins[n].capsules
    if (ca.length !== cb.length) { sameShape = false; if (process.env.DBG) console.log('caps', k); continue }
    ca.forEach((c, i) => {
      const d = cb[i]
      if (c.id !== d.id) sameShape = false
      for (let j = 0; j < 3; j++) maxCap = Math.max(maxCap, diff(c.now.a[j], d.now.a[j]), diff(c.now.b[j], d.now.b[j]))
      maxCap = Math.max(maxCap, diff(c.now.r, d.now.r))
    })
    const ha = a.ins[n].channels, hb = b.ins[n].channels
    if (ha.length !== hb.length) sameShape = false
    else ha.forEach((c, i) => {
      for (let j = 0; j < 3; j++) maxCh = Math.max(maxCh, diff(c.o[j], hb[i].o[j]), diff(c.u[j], hb[i].u[j]))
      maxCh = Math.max(maxCh, diff(c.r, hb[i].r), diff(c.depth, hb[i].depth))
    })
  }
  const ea = a.frame.engagements, eb = b.frame.engagements
  if (ea.length !== eb.length) { sameShape = false; if (process.env.DBG) console.log('eng', k, JSON.stringify(ea), JSON.stringify(eb)) }
  else ea.forEach((e, i) => {
    if (e.w > 0) engagedFrames++
    const o = eb[i]
    if (e.by !== o.by || e.of !== o.of || e.channel !== o.channel || (e.opening === null) !== (o.opening === null)) {
      sameShape = false
      if (process.env.DBG) console.log('eng', k, JSON.stringify(e), JSON.stringify(o))
    }
    maxW = Math.max(maxW, diff(e.w, o.w))
    if (e.opening !== null && o.opening !== null) maxOpen = Math.max(maxOpen, diff(e.opening, o.opening))
  })
  const qa = a.ins.Q.openings, qb = b.ins.Q.openings
  if (qa.length !== qb.length) { sameShape = false; if (process.env.DBG) console.log('open', k, JSON.stringify(qa), JSON.stringify(qb)) }
  else qa.forEach((o, i) => { maxOpen = Math.max(maxOpen, diff(o.radius, qb[i].radius), diff(o.maxPush, qb[i].maxPush)) })
  const xa = a.frame.contacts, xb = b.frame.contacts
  if (xa.length !== xb.length) { sameShape = false; if (process.env.DBG) console.log('cont', k, xa.length, xb.length) }
  else {
    // keyed by the pair: two pairs of (nearly) equal depth may sort either way
    const key = c => `${c.a}:${c.capA}|${c.b}:${c.capB}`
    const other = new Map(xb.map(c => [key(c), c.depth]))
    for (const c of xa) {
      if (!other.has(key(c))) { sameShape = false; continue }
      maxDepth = Math.max(maxDepth, diff(c.depth, other.get(key(c))))
    }
  }
}
check('[E1] the same rows every frame (capsule ids, channels, engagements, openings, contact pairs)', sameShape && engagedFrames > 60,
  `${engagedFrames} frames with an engaged chain`)
check('[E2] capsule ends + radii, client3d vs preview, 90 frames, max |Δ| ≤ 1e-6', maxCap <= 1e-6, maxCap.toExponential(3))
check('[E3] channel frame (o, u, r, depth) ≤ 1e-6', maxCh <= 1e-6, maxCh.toExponential(3))
check('[E4] engagement weights ≤ 1e-6', maxW <= 1e-6, maxW.toExponential(3))
check('[E5] opening radii + pushes ≤ 1e-6', maxOpen <= 1e-6, maxOpen.toExponential(3))
check('[E6] contact depths ≤ 1e-6', maxDepth <= 1e-6, maxDepth.toExponential(3))
// --- by hand (on both paths) ----------------------------------------------------------------------------------------
for (const [label, run] of [['client3d', A], ['preview', B]]) {
  const arm = run.map(r => r.frame.closest[0])
  check(`[H1 ${label}] the closest pair is arm↔arm at 80.000 mm every frame`,
    arm.every(c => c.capA === 'arm' && c.capB === 'arm' && Math.abs(c.depth - 0.08) <= 1e-6),
    `f1 ${(arm[0].depth * 1000).toFixed(3)} mm, f90 ${(arm[89].depth * 1000).toFixed(3)} mm`)
  const w = run.map(r => r.frame.engagements.find(e => e.by === 'P' && e.of === 'Q' && e.channel === 'pkg:chan')?.w ?? 0)
  const first = w.findIndex(x => x > 0) + 1
  const full = w.findIndex(x => Math.abs(x - 1) <= 1e-9) + 1
  check(`[H2 ${label}] first w > 0 at f 15 (w 1/12), w = 1 from f 26`,
    first === 15 && Math.abs(w[14] - 1 / 12) <= 1e-9 && full === 26, `first ${first} (w ${w[first - 1]?.toFixed(6)}), full ${full}`)
  const open = run.slice(29).map(r => r.frame.engagements.find(e => e.of === 'Q')?.opening)
  check(`[H3 ${label}] Q opens pkg:chan to 5.000 mm from f 30`, open.every(x => x !== null && x !== undefined && Math.abs(x - 0.005) <= 1e-6),
    `f30 ${open[0] == null ? 'none' : (open[0] * 1000).toFixed(3)} mm, push ${(run[89].ins.Q.openings[0]?.maxPush * 1000).toFixed(3)} mm`)
}
console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed')
assert.equal(failures, 0)
