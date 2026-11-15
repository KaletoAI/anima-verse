#!/usr/bin/env node
/**
 * Ruling A110 phase 1: the per-figure runtime moved from client3d's `Figure` / `NpcManager.tickSecondary` into
 * `@anima/scene-render` (`figureRuntime.ts`, `frameLoop.ts`) WITHOUT a behaviour change. Proof: the same two
 * figures run the same fixed clip for 90 frames on BASE (b1670f752, the commit before the extraction — the old
 * `Figure` and the old phase-B loop, reproduced below line for line from that commit's `tickSecondary`) and on the
 * working tree (`Figure` wrapping `FigureRuntime`, phase B through `runFigureFrame`). Every bone's world matrix and
 * every strand-hair target must agree within 1e-6 on every frame.
 *
 * Usage: node scripts/smoke_figure_runtime_equality.mjs   (no server, no world; bundles both clients with esbuild)
 *
 * FIXTURE (by hand): Hips (0,0,0) → Spine2 (0,1.30,0) → Neck (+0.15) → Head (+0.10); a driven chain
 *   LinkB_00 (Hips + (0, 0.9, −0.15)) → LinkB_01 (+(0, −0.15, −0.05)), motion group chain_b (freq 2 Hz, ζ 0.3,
 *   gravity 1 — it swings); a hair garment of 2 cards × 17 rows bound by a strand record (strands ON); capsules
 *   head (Neck→Head r 0.2), torso (Spine2→Neck r 0.12), link (LinkB_00→LinkB_01 r 0.12, attached_part).
 *   The clip `standing` (1 s loop): Hips x = 0.05·sin(2πt) (0, 0.25, 0.5, 0.75, 1 s → 0, 0.05, 0, −0.05, 0),
 *   Spine2 turns about z by 0 → 10° → 0 → −10° → 0 — the head (and the hair on it) moves, so the strands work.
 *   P stands at the origin facing +z, Q at (0.3, 0, 0) facing −z: 0.3 m apart, each reads the other (partner
 *   capsules into the strands and the chain), so the cross-person path is exercised too.
 * [1] the clip moves the head (> 1 cm over the run) and the chain swings (the comparison compares something);
 * [2] max |Δ| over all bone matrixWorld elements of P and Q, 90 frames: ≤ 1e-6;
 * [3] max |Δ| over all strand targets of P and Q, 90 frames: ≤ 1e-6;
 * [4] the plans are equal every frame (P reads [Q], Q reads [P]).
 */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtemp, rm, writeFile, mkdir, symlink } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
const BASE = 'b1670f752'

async function bundle(dir, srcRoot, entry, name) {
  const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
  const built = await esbuild.build({
    stdin: { contents: entry, resolveDir: join(srcRoot, 'client3d'), loader: 'ts' },
    bundle: true, platform: 'node', format: 'esm', write: false,
    outfile: join(dir, `${name}.mjs`), external: ['three', 'three/*'], logLevel: 'error',
  })
  const file = join(dir, `${name}.mjs`)
  await writeFile(file, built.outputFiles[0].text, 'utf8')
  return await import(`file://${file}`)
}

async function loadClients() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-runtime-eq-'))
  try {
    const now = await bundle(dir, ROOT, [
      `export { Figure, hairPartnerCapsules } from '${ROOT}/client3d/src/scene/figures';`,
      "export { runFigureFrame, COLLISION_VERSION } from '@anima/scene-render';",
    ].join('\n'), 'now')
    const base = join(dir, 'base')
    await mkdir(base)
    const tar = spawnSync('sh', ['-c', `git -C "${ROOT}" archive ${BASE} client3d/src packages | tar -x -C "${base}"`],
      { stdio: 'inherit' })
    assert.equal(tar.status, 0, `git archive ${BASE} failed`)
    await mkdir(join(base, 'node_modules/@anima'), { recursive: true })
    for (const pkg of ['scene-render', 'player-ui']) {
      await symlink(join(base, 'packages', pkg), join(base, 'node_modules/@anima', pkg))
    }
    const old = await bundle(dir, base, [
      `export { Figure, hairPartnerCapsules } from '${base}/client3d/src/scene/figures';`,
      `export { planPartnerFrame } from '${base}/client3d/src/scene/partnerFrame';`,
    ].join('\n'), 'base')
    return { now, old }
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

const THREE = await import('three')
const { now, old } = await loadClients()
const COLLISION_VERSION = now.COLLISION_VERSION

// --- fixture ------------------------------------------------------------------------------------------------------
const R = 17, XK = [-0.03, 0.03]
const PARAMS = { damping: 0.04, stiffness: 1.0, bend: 0.15, iterations: 6, root_deg: 10, root_frac: 0.2,
  fly_soft: true, fly_arc: 0.30, tether: true, tether_r0: 0.015, tether_r1: 0.06, tether_head: 0.012,
  head_clr: 0.03, face_box: true }
const CAPSULES = [
  { id: 'head', a: 'mixamorigNeck', b: 'mixamorigHead', r: 0.2, region: 'head' },
  { id: 'torso', a: 'mixamorigSpine2', b: 'mixamorigNeck', r: 0.12, region: 'torso' },
  { id: 'link', a: 'LinkB_00', b: 'LinkB_01', r: 0.12, region: 'attached_part' },
]
function record() {
  const rest = [], pins = [], freeArc = [], freeFrac = [], w = []
  for (let k = 0; k < 2; k++) {
    pins.push(2)
    for (let i = 0; i < R; i++) {
      rest.push(XK[k], 1.60 - 0.02 * i, -0.10)
      freeArc.push(i < 2 ? 0 : 0.02 * (i - 1)); freeFrac.push(i < 2 ? 0 : (i - 1) / 15); w.push(1)
    }
  }
  return { version: 1, item_id: 'hair_fixture', fsig: '0123456789ab', mode: 'hairdeck', fit_sha256: 'f'.repeat(64),
    frame: 'head_bind', head_bone: 'mixamorigHead', rows: R, cards: 2, rest, pins, free_arc: freeArc,
    free_frac: freeFrac, follow: { bones: ['mixamorigHead'], w }, ear_y: 1.50,
    face_box: [-0.06, 0.06, 1.48, 1.66, 0.05], eye_box: [-0.04, 0.04, 1.55, 1.64, 0.05],
    sdf: { dims: [2, 2, 2], lo: [-0.2, 1.3, -0.2], vox: 0.4, order: 'x_fastest', unit: 'mm_int8',
      data: Buffer.from(new Int8Array(8).fill(127).buffer).toString('base64') },
    capsules: { version: COLLISION_VERSION, capsules: CAPSULES, scales: {} }, params: PARAMS,
    vertex_attributes: { card: '_STRAND_CARD', u: '_STRAND_U' } }
}
function template() {
  const fig = new THREE.Group()
  const bones = []
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = name; b.position.set(...at); (parent ?? fig).add(b); bones.push(b); return b
  }
  const hips = bone('mixamorigHips', null, [0, 0, 0])
  const spine = bone('mixamorigSpine2', hips, [0, 1.30, 0])
  const neck = bone('mixamorigNeck', spine, [0, 0.15, 0])
  bone('mixamorigHead', neck, [0, 0.10, 0])
  const b0 = bone('LinkB_00', hips, [0, 0.9, -0.15])
  bone('LinkB_01', b0, [0, -0.15, -0.05])
  fig.updateMatrixWorld(true)
  const skeleton = new THREE.Skeleton(bones)
  const bodyGeo = new THREE.BufferGeometry()
  bodyGeo.setAttribute('position', new THREE.Float32BufferAttribute(
    [-0.15, 0, 0.25, 0.15, 0, -0.25, 0, 1.7, 0, 0, 0.9, -0.20, 0, 0.75, -0.25], 3))
  bodyGeo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0,
    4, 0, 0, 0, 5, 0, 0, 0], 4))
  bodyGeo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(Array.from({ length: 5 }, () => [1, 0, 0, 0]).flat(), 4))
  const body = new THREE.SkinnedMesh(bodyGeo, new THREE.MeshStandardMaterial()); body.name = 'body'
  const pos = [], nrm = [], card = [], u = [], si = [], sw = []
  for (let k = 0; k < 2; k++) for (let i = 0; i < R; i++) for (const s of [-1, 1]) {
    pos.push(XK[k] + s * 0.004, 1.60 - 0.02 * i, -0.10); nrm.push(0, 0, -1)
    card.push(k + 1); u.push(i); si.push(2, 3, 0, 0); sw.push(0.5, 0.5, 0, 0)
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
  const hair = new THREE.SkinnedMesh(hairGeo, new THREE.MeshStandardMaterial()); hair.name = 'hair'
  const garment = new THREE.Group()
  garment.name = 'garment_hair_fixture'
  garment.userData.garment = { kind: 'hair' }
  garment.add(hair)
  fig.add(body, garment)
  fig.updateMatrixWorld(true)
  body.bind(skeleton, body.matrixWorld)
  hair.bind(skeleton, hair.matrixWorld)
  return fig
}
const DEFAULTS = { freq_hz: 2, zeta: 0.3, gravity: 1, gravity_scale: 1, gain: 1,
  max_deg: 25, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1 }
const MOTION = { rev: 'm1', groups: { chain_b: { ...DEFAULTS, bones: ['LinkB_00', 'LinkB_01'] } } }
function clip() {
  const t = [0, 0.25, 0.5, 0.75, 1]
  const hips = new THREE.VectorKeyframeTrack('mixamorigHips.position', t,
    [0, 0, 0, 0.05, 0, 0, 0, 0, 0, -0.05, 0, 0, 0, 0, 0])
  const q = deg => new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), deg * Math.PI / 180).toArray()
  const spine = new THREE.QuaternionKeyframeTrack('mixamorigSpine2.quaternion', t,
    [0, 10, 0, -10, 0].flatMap(q))
  return new THREE.AnimationClip('standing', 1, [hips, spine])
}
function model() {
  return { motion: { payload: MOTION }, collision: { version: COLLISION_VERSION, capsules: CAPSULES },
    footPose: null, hairStrands: { url: '/x', sha256: 'abc' }, name: 'Fixture', template: template(),
    clips: [clip()], scale: 1, height: 1.7, assignOnly: true, noClips: false, tier: 'full', libraryFits: false }
}
function seeded(build, seed = 7) {
  const random = Math.random
  let s = seed
  Math.random = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648 }
  try { return build() } finally { Math.random = random }
}

/** BASE phase B, from b1670f752 `NpcManager.tickSecondary` (no pair interaction, no openings — no channels). */
function oldPhaseB(npcs) {
  const frames = []
  for (const [name, figure] of npcs) { const f = figure.frameFigure(name, []); if (f) frames.push(f) }
  const plan = frames.length > 1 ? old.planPartnerFrame(frames) : new Map()
  const snapshots = new Map()
  for (const names of plan.values()) {
    for (const name of names) {
      if (snapshots.has(name)) continue
      snapshots.set(name, npcs.get(name)?.partnerSnapshot(null, name) ?? null)
    }
  }
  const partnersOf = name => (plan.get(name) ?? []).map(n => snapshots.get(n)).filter(Boolean)
  for (const [name, figure] of npcs) figure.updateSecondary(partnersOf(name), null)
  for (const [, figure] of npcs) figure.applyChannelOpenings([], { left: 1 })
  const fresh = new Map()
  for (const [name, figure] of npcs) {
    const names = figure.hasHairPush ? plan.get(name) : undefined
    if (!names?.length) { figure.setGpuPartners(null); continue }
    const partners = []
    for (const n of names) {
      if (!snapshots.get(n)) continue
      if (!fresh.has(n)) fresh.set(n, npcs.get(n)?.partnerSnapshot(null, n) ?? null)
      const snap = fresh.get(n)
      if (snap) partners.push(snap)
    }
    figure.setGpuPartners(partners.length ? old.hairPartnerCapsules(partners) : null)
  }
  return plan
}

function world(lib, newLoop) {
  const make = () => {
    const f = seeded(() => new lib.Figure(model()))
    f.loadStrandRecord = () => record()
    assert.ok(f.prepareStrandHair(), 'strand handle')
    f.setStrandHair(true)
    f.play('standing')
    return f
  }
  const p = make(), q = make()
  p.root.rotation.y = 0; p.setYaw(0)
  q.root.position.set(0.3, 0, 0); q.root.rotation.y = Math.PI; q.setYaw(Math.PI)
  const npcs = new Map([['P', p], ['Q', q]])
  const state = { openingTurn: 0 }
  const frames = []
  for (let k = 0; k < 90; k++) {
    for (const f of npcs.values()) f.update(1 / 60, { realDelta: 1 / 60 })
    let plan = null
    if (newLoop) {
      // Capture the plan through the frame figures, then run the shared loop.
      const fr = [...npcs].map(([n, f]) => f.frameFigure(n, [])).filter(Boolean)
      plan = JSON.stringify(fr.map(f => [f.name, f.reader]))
      now.runFigureFrame([...npcs].map(([name, figure]) => ({ name, interaction: null, figure })), state)
    } else {
      const fr = [...npcs].map(([n, f]) => f.frameFigure(n, [])).filter(Boolean)
      plan = JSON.stringify(fr.map(f => [f.name, f.reader]))
      oldPhaseB(npcs)
    }
    const bones = [], strands = []
    for (const f of npcs.values()) {
      f.root.updateMatrixWorld(true)
      f.root.traverse(o => { if (o.isBone) bones.push(...o.matrixWorld.elements) })
      strands.push(...f.strandHair.targets)
    }
    frames.push({ bones, strands, plan })
  }
  const head = []
  p.root.traverse(o => { if (o.name === 'mixamorigHead') head.push(o.getWorldPosition(new THREE.Vector3())) })
  p.dispose(); q.dispose()
  return frames
}

const before = world(old, false)
const after = world(now, true)
let maxBone = 0, maxStrand = 0, planSame = true
let headTravel = 0, chainMoved = false
for (let k = 0; k < before.length; k++) {
  const a = before[k], b = after[k]
  assert.equal(a.bones.length, b.bones.length)
  assert.equal(a.strands.length, b.strands.length)
  for (let i = 0; i < a.bones.length; i++) maxBone = Math.max(maxBone, Math.abs(a.bones[i] - b.bones[i]))
  for (let i = 0; i < a.strands.length; i++) maxStrand = Math.max(maxStrand, Math.abs(a.strands[i] - b.strands[i]))
  if (a.plan !== b.plan) planSame = false
  if (k) {
    for (let i = 0; i < a.strands.length; i += 3) {
      headTravel = Math.max(headTravel, Math.hypot(a.strands[i] - before[0].strands[i], a.strands[i + 1] - before[0].strands[i + 1]))
    }
    if (a.bones.some((v, i) => Math.abs(v - before[0].bones[i]) > 1e-4)) chainMoved = true
  }
}
let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
check("[1] the clip moves the hair (> 1 cm) and the bones move", headTravel > 0.01 && chainMoved,
  `strand travel ${headTravel.toFixed(4)} m, bones moved ${chainMoved}`)
check('[2] bone matrixWorld, BASE vs runtime, 90 frames, max |Δ| ≤ 1e-6', maxBone <= 1e-6, maxBone.toExponential(3))
check('[3] strand targets, BASE vs runtime, 90 frames, max |Δ| ≤ 1e-6', maxStrand <= 1e-6, maxStrand.toExponential(3))
check('[4] the frame figures (name, reader) agree every frame', planSame, after[0].plan)
console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed')
assert.equal(failures, 0)
