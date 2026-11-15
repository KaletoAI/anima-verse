#!/usr/bin/env node
/**
 * The 3D client's TWO-PHASE FIGURE FRAME (cross-person collision plan Task 7; spec
 * docs/superpowers/specs/2026-11-13-cross-person-collision-design.md Part 1, "Update order and lag"):
 * `packages/scene-render/src/partnerFrame.ts` `planPartnerFrame` and `Figure.update` (phase A) /
 * `updateSecondary` / `frameFigure` / `partnerSnapshot` in `client3d/src/scene/figures.ts`. Hand-derived.
 *
 * Usage: node scripts/smoke_partner_frame.mjs   (no server, no world; bundles the client with esbuild, and the
 *        BASE edition of figures.ts from `git archive fe755a740` for [2])
 *
 * [1] PLAN, the D6 positions (plan "Derivations"): the reader `r` stands at the origin, bindRadius 1, lever 0,
 *     members [m], reach sphere (0,1,0) r 1.0. Candidates stand at x = 1.4 (m), 0.5 (a), 1.0 (b), 1.2 (c),
 *     1.5 (d), 3.0 (e), bindRadius 0.5, body sphere (x,1,0) r 0.5. Root prefilter: |x| ≤ 1 + 0 + 0.5 + 1.0 = 2.5
 *     → e (3.0) never has `body()` asked. Gaps (distance − 1.0 − 0.5): m −0.1, a −1.0, b −0.5, c −0.3, d 0.0 →
 *     member first, then the smallest gap: [m, a, b, c] (d cut by PARTNER_MAX 4). A reader `far` at x = 30:
 *     30 > 2.5 for everyone → [] with neither its `reach()` nor anyone's `body()` toward it asked; `body()` of e
 *     and of `far` is asked 0 times, the reader's `reach()` once, every other body once. A non-reader gets no entry.
 * FIGURE FIXTURE (metres, bind rotations identity, scale 1, no clips → the procedural idle; `Math.random` seeded so
 *   two figures of one fixture are bit for bit the same): Hips (0,0,0) → Spine2 (0,1.30,0) → Neck (0,1.45,0) →
 *   Head (0,1.55,0); chain A (a hair group, `hair: true`) LinkA_00 at Head + (0.12,0,0) → LinkA_01 0.12 below it,
 *   one vertex each 0.05 / 0.07 below its joint (tips (0.12,1.50,0) and (0.12,1.36,0)); chain B (an extension
 *   group) LinkB_00 at Hips + (0,0.9,−0.15) → LinkB_01 at + (0,−0.15,−0.05), one vertex each 0.05 behind its joint.
 *   Capsules (v COLLISION_VERSION): `torso` Hips→Spine2 r 0.12 (torso), `head` Neck→Head r 0.09 (head),
 *   `outer_spine` Spine2→Neck r 0.20 (outer_trunk — partner only), `link` LinkA_00→LinkA_01 r 0.12
 *   (attached_part — rides chain A's DRIVEN joints; chain A's own hair set never holds it). Both groups gain 1,
 *   gravity 1, max_deg 25 (swinging); [3] runs them with gain 0 and gravity 0 (standing at the bind frame, so
 *   every turn is a contact).
 * [2] PHASE A / PHASE B against BASE (fe755a740, one `update` with the secondary motion inside), 40 frames, dt =
 *     realDelta = 1/60, the owner moving the root by 0.05·sin(0.3 k) in x (BASE gets the same capsules under ITS
 *     `COLLISION_VERSION` — a payload bump, e.g. v7's channels, adds keys and leaves the capsules as they are): after the new `update(dt)` every bone
 *     (driven ones included) has the same `matrix` / `matrixWorld` as BASE right BEFORE its `secondary.update`;
 *     after `updateSecondary([])` the same as BASE after its whole `update` — bit for bit. A second
 *     `updateSecondary` without a new phase A changes nothing (no-op).
 * [3] ORDER INDEPENDENCE: P at the origin facing +z (yaw 0), Q at (0.3,0,0) turned by π (its chain A toward P).
 *     P's tips (0.12,1.50,0) / (0.12,1.36,0) lie hypot(0.18, 0.05) = 0.187 / 0.18 from Q's `outer_spine` segment
 *     (x 0.3, y 1.30…1.45) — inside r 0.20 — and Q's mirrored tips as far from P's: each pushes the other (a
 *     `contactTips` row with a partner key appears).
 *     Q's chain A hangs at x 0.18, 0.06 from P's `link` axis (x 0.12) — inside r 0.12 — so each also reads a
 *     capsule on the OTHER's driven joints. Plan: P → [Q], Q → [P]. Phase B with the snapshots taken before any
 *     solve, visiting P→Q in one world and Q→P in another (same seed, 30 frames): every bone matrix bit for bit
 *     equal. CONTROL (the check has teeth): snapshots taken lazily, right before each reader solves, read the
 *     `link` capsule of a partner that already solved in one order and not in the other → the two orders differ.
 * [4] A lone reader (L, 30 m from the others) and a far-tier reader (F, tier low, 0.3 m from a figure G without a
 *     driven link): no `partnerSnapshot` asked, no partner `bindCollision` (spy on the client's import), and every
 *     phase B still runs (with []).
 * [5] REVIEW FOCUS 3, a model swap through `FigureLibrary`: figure A of model 1 snapshots (one bind, on A's
 *     instance). `retireModels` → A's next `partnerSnapshot` and `frameFigure` are null and its binding is gone.
 *     Model 2 installed, figure B instantiated at x = 5: its `partnerSnapshot` binds on B's instance (the spy
 *     counts 2), every bound capsule's joint meshes are descendants of B's root (none of A's), and the capsule
 *     ends follow B (x within 5 ± 0.3). A payload of version 5: `partnerSnapshot` null, `frameFigure` null,
 *     nothing thrown; a reader next to it reads [] .
 * [6] FROZEN: `update(1/60, {frozen: true})` and the photo hold `update(0, {frozen: true})` both reach phase B:
 *     `secondary.update` is called once, with `frozen: true` and the given partners. Two phase A calls before one
 *     phase B add their real time: 0.01 + 0.02 → one `secondary.update` with 0.03.
 * [7] CHANNELS (plan Task 14): a figure whose payload carries a channel record (owning joint Hips, opening
 *     a_pos (0, 1.0, 0.1), bottom b_pos (0, 1.0, 0.0), r 0.02, funnel 0.05), its root at x = 2: its
 *     `partnerSnapshot({i1, k}, 'P')` carries that channel in the world — o (2, 1.0, 0.1), u (0, 0, −1), depth
 *     0.1, r 0.02 (±1e-9; bind rotations identity, scale 1) — and the interaction; a snapshot taken after the root
 *     moved to x = 3 has o.x 3 while the first keeps 2 (each snapshot owns its frame). Without a channel record the
 *     snapshot's `channels` is []. `updateSecondary(partners, {id: i1})` hands `interaction: {id: i1}` to the
 *     secondary motion, `updateSecondary(partners)` hands null.
 */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtemp, rm, writeFile, mkdir, symlink } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
/** The ledger's BASE of plan Task 7: figures.ts with the secondary motion inside `update`. */
const BASE = 'fe755a740'

async function bundle(dir, srcRoot, entry, spy, name) {
  const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
  const sceneRender = join(srcRoot, 'packages/scene-render/src/index.ts')
  // The spy: the partner binding's own `bindCollision` — since Ruling A110 the per-figure runtime
  // (`figureRuntime.ts`) binds the partner capsules, so ITS './collision' import goes through a module that counts
  // (the package's other internal binds — secondary motion, garment push — import './collision' directly and are
  // not counted). `spyCounts` rides on the client's `@anima/scene-render` import.
  const collision = join(srcRoot, 'packages/scene-render/src/collision.ts')
  const plugins = spy ? [{
    name: 'spy',
    setup(build) {
      build.onResolve({ filter: /^@anima\/scene-render$/ }, () => ({ path: 'spy', namespace: 'spy' }))
      build.onResolve({ filter: /^spy-counts$/ }, () => ({ path: 'counts', namespace: 'spy' }))
      build.onResolve({ filter: /^\.\/collision$/ }, args => args.importer.endsWith('figureRuntime.ts')
        ? { path: 'collision', namespace: 'spy' } : undefined)
      build.onLoad({ filter: /.*/, namespace: 'spy' }, args => ({
        resolveDir: ROOT, loader: 'ts',
        contents: args.path === 'counts' ? 'export const spyCounts = { bind: 0 };'
          : args.path === 'collision' ? [
            `export * from '${collision}';`,
            `import { bindCollision as realBind } from '${collision}';`,
            "import { spyCounts } from 'spy-counts';",
            'export function bindCollision(...args) { spyCounts.bind++; return realBind(...args); }',
          ].join('\n')
          : [`export * from '${sceneRender}';`, "export { spyCounts } from 'spy-counts';"].join('\n'),
      }))
    },
  }] : []
  const built = await esbuild.build({
    stdin: { contents: entry, resolveDir: join(srcRoot, 'client3d'), loader: 'ts' },
    bundle: true, platform: 'node', format: 'esm', write: false, plugins,
    outfile: join(dir, `${name}.mjs`), external: ['three', 'three/*'], logLevel: 'error',
  })
  const file = join(dir, `${name}.mjs`)
  await writeFile(file, built.outputFiles[0].text, 'utf8')
  return await import(`file://${file}`)
}

async function loadClients() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-partner-frame-'))
  try {
    const src = join(ROOT, 'client3d/src')
    const client = await bundle(dir, ROOT, [
      `export { planPartnerFrame } from '@anima/scene-render';`,
      `export { Figure, FigureLibrary } from '${src}/scene/figures';`,
      `export { COLLISION_VERSION, spyCounts } from '@anima/scene-render';`,
    ].join('\n'), true, 'client')
    // BASE: the whole client and package sources of fe755a740, resolved among themselves (`@anima/*` linked).
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
      `export { Figure } from '${base}/client3d/src/scene/figures';`,
      `export { COLLISION_VERSION } from '@anima/scene-render';`,
    ].join('\n'), false, 'base')
    return { client, old }
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}

const THREE = await import('three')
const { client, old } = await loadClients()
const { planPartnerFrame, Figure, FigureLibrary, COLLISION_VERSION, spyCounts } = client

// [1] the plan on the D6 positions -----------------------------------------------------------------------------
{
  const asked = { body: new Map(), reach: new Map() }
  const bump = (map, name) => map.set(name, (map.get(name) ?? 0) + 1)
  const frame = (name, x, { reader = false, bindRadius = 0.5, members = [], reach = null } = {}) => ({
    name, root: [x, 0, 0], bindRadius, reader, lever: 0, members,
    body: () => { bump(asked.body, name); return { c: [x, 1, 0], r: 0.5 } },
    reach: () => { bump(asked.reach, name); return reach },
  })
  const figures = [
    frame('r', 0, { reader: true, bindRadius: 1, members: ['m'], reach: { c: [0, 1, 0], r: 1.0 } }),
    frame('m', 1.4), frame('a', 0.5), frame('b', 1.0), frame('c', 1.2), frame('d', 1.5), frame('e', 3.0),
    frame('far', 30, { reader: true, bindRadius: 1, reach: { c: [30, 1, 0], r: 1.0 } }),
  ]
  const plan = planPartnerFrame(figures)
  check('[1] D6: the reader reads [m, a, b, c]', JSON.stringify(plan.get('r')) === '["m","a","b","c"]',
    JSON.stringify(plan.get('r')))
  check('[1] the reader 30 m away reads [] and its reach() is never asked',
    JSON.stringify(plan.get('far')) === '[]' && !asked.reach.get('far'), String(asked.reach.get('far')))
  check('[1] body() of the 30 m figure and of e (past the prefilter) is never asked',
    !asked.body.get('far') && !asked.body.get('e'), JSON.stringify([...asked.body]))
  check('[1] the reader\'s reach() once, every prefiltered body() once',
    asked.reach.get('r') === 1 && ['m', 'a', 'b', 'c', 'd'].every(n => asked.body.get(n) === 1))
  check('[1] a non-reader gets no entry', [...plan.keys()].sort().join() === 'far,r', [...plan.keys()].join())
}

// --- the figure fixture -------------------------------------------------------------------------------------------
const CAPSULES = [
  { id: 'torso', a: 'mixamorig:Hips', b: 'mixamorig:Spine2', r: 0.12, region: 'torso' },
  { id: 'head', a: 'mixamorig:Neck', b: 'mixamorig:Head', r: 0.09, region: 'head' },
  { id: 'outer_spine', a: 'mixamorig:Spine2', b: 'mixamorig:Neck', r: 0.20, region: 'outer_trunk' },
  { id: 'link', a: 'LinkA_00', b: 'LinkA_01', r: 0.12, region: 'attached_part' },
]
function template() {
  const fig = new THREE.Group()
  const bones = []
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = name; b.position.set(...at); (parent ?? fig).add(b); bones.push(b); return b
  }
  const hips = bone('mixamorig:Hips', null, [0, 0, 0])
  const spine = bone('mixamorig:Spine2', hips, [0, 1.30, 0])
  const neck = bone('mixamorig:Neck', spine, [0, 0.15, 0])
  const head = bone('mixamorig:Head', neck, [0, 0.10, 0])
  const a0 = bone('LinkA_00', head, [0.12, 0, 0])
  bone('LinkA_01', a0, [0, -0.12, 0])
  const b0 = bone('LinkB_00', hips, [0, 0.9, -0.15])
  bone('LinkB_01', b0, [0, -0.15, -0.05])
  fig.updateMatrixWorld(true)
  const skeleton = new THREE.Skeleton(bones)
  // body: three vertices on Hips / Spine2 / Head (a box centred on the origin in x and z, so the figure is not
  // shifted when it is centred over its feet); one vertex per chain link (indices 4..7)
  const pos = [-0.15, 0, 0.25, 0.15, 0, -0.25, 0, 1.7, 0, 0.12, 1.50, 0, 0.12, 1.36, 0, 0, 0.9, -0.20, 0, 0.75, -0.25]
  const idx = [0, 1, 3, 4, 5, 6, 7]
  const si = [], sw = []
  for (const i of idx) { si.push(i, 0, 0, 0); sw.push(1, 0, 0, 0) }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(si, 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(sw, 4))
  const body = new THREE.SkinnedMesh(geo, new THREE.MeshStandardMaterial()); body.name = 'body'
  fig.add(body)
  fig.updateMatrixWorld(true)
  body.bind(skeleton, body.matrixWorld)
  return fig
}
const DEFAULTS = { freq_hz: 2, zeta: 0.3, gravity: 1, gravity_scale: 1, gain: 1,
  max_deg: 25, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1 }
const MOTION = { rev: 'm1', groups: {
  chain_a: { ...DEFAULTS, bones: ['LinkA_00', 'LinkA_01'], hair: true },
  chain_b: { ...DEFAULTS, bones: ['LinkB_00', 'LinkB_01'] } } }
/** [3]: no swing (gain 0, gravity 0) — the chains stand at their bind frame, every turn is a contact. */
const CALM = { rev: 'calm', groups: {
  chain_a: { ...DEFAULTS, gain: 0, gravity: 0, bones: ['LinkA_00', 'LinkA_01'], hair: true },
  chain_b: { ...DEFAULTS, gain: 0, gravity: 0, bones: ['LinkB_00', 'LinkB_01'] } } }
function model({ tier = 'full', version = COLLISION_VERSION, motion = MOTION, name = 'Fixture', channels } = {}) {
  return { motion: { payload: motion }, collision: { version, capsules: CAPSULES, ...(channels ? { channels } : {}) },
    footPose: null, hairStrands: null,
    name, template: template(), clips: [], scale: 1, height: 1.7, assignOnly: true, noClips: false, tier,
    libraryFits: false }
}
/** `Math.random` from a fixed seed while a figure is built (its idle / walk phases). */
function seeded(build, seed = 7) {
  const random = Math.random
  let s = seed
  Math.random = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648 }
  try { return build() } finally { Math.random = random }
}
const bonesOf = f => { const out = []; f.root.traverse(o => { if (o.isBone) out.push(o) }); return out }
function matrices(f) {
  f.root.updateMatrixWorld(true)
  return bonesOf(f).flatMap(b => [...b.matrix.elements, ...b.matrixWorld.elements])
}
const same = (p, q) => p.length === q.length && p.every((v, i) => Object.is(v, q[i]))
const firstDiff = (p, q) => { const i = p.findIndex((v, k) => !Object.is(v, q[k])); return i < 0 ? '' : `#${i}: ${p[i]} vs ${q[i]}` }

// [2] phase A / phase B against BASE ------------------------------------------------------------------------------
{
  const fig = seeded(() => new Figure(model()))
  // BASE reads its own payload version (v6 there): the capsules are the same, a later bump only adds keys.
  const ref = seeded(() => new old.Figure(model({ version: old.COLLISION_VERSION })))
  let before = null
  const realUpdate = ref.secondary.update.bind(ref.secondary)
  ref.secondary.update = (dt, options) => { before = matrices(ref); realUpdate(dt, options) }
  let phaseA = true, phaseB = true, moved = false, noOp = true, detail = ''
  const start = matrices(fig)
  for (let k = 0; k < 40; k++) {
    const x = 0.05 * Math.sin(0.3 * k)
    fig.root.position.x = x
    ref.root.position.x = x
    fig.update(1 / 60, { realDelta: 1 / 60 })
    ref.update(1 / 60, { realDelta: 1 / 60 })
    const a = matrices(fig)
    if (!before || !same(a, before)) { phaseA = false; detail ||= `A frame ${k} ${before ? firstDiff(a, before) : 'no BASE secondary'}` }
    fig.updateSecondary([])
    const b = matrices(fig), r = matrices(ref)
    if (!same(b, r)) { phaseB = false; detail ||= `B frame ${k} ${firstDiff(b, r)}` }
    if (!same(b, a)) moved = true
    fig.updateSecondary([])
    if (!same(matrices(fig), b)) noOp = false
  }
  check('[2] after update(dt) every bone equals BASE before its secondary motion (40 frames)', phaseA, detail)
  check('[2] after updateSecondary([]) every bone equals BASE\'s single update, bit for bit', phaseB, detail)
  check('[2] the secondary motion moved the driven bones (the comparison has something to compare)',
    moved && !same(start, matrices(fig)))
  check('[2] updateSecondary without a pending phase A is a no-op', noOp)
  fig.dispose()
  ref.dispose()
}

/** Phase B as `NpcManager.tickSecondary` runs it: plan, every selected partner snapshot once, then each figure's
 *  `updateSecondary` in `order`. Returns the plan. `lazy` (the [3] control only): each reader snapshots its partners
 *  right before it solves instead. */
function phaseB(figs, order, lazy = false) {
  const frames = []
  for (const [name, f] of figs) { const fr = f.frameFigure(name, []); if (fr) frames.push(fr) }
  const plan = frames.length > 1 ? planPartnerFrame(frames) : new Map()
  const snaps = new Map()
  if (!lazy) {
    for (const names of plan.values()) {
      for (const n of names) if (!snaps.has(n)) snaps.set(n, figs.get(n).partnerSnapshot(null, n))
    }
  }
  for (const name of order) {
    const names = plan.get(name) ?? []
    const partners = lazy ? names.map(n => figs.get(n).partnerSnapshot(null, n)) : names.map(n => snaps.get(n))
    figs.get(name).updateSecondary(partners.filter(Boolean))
  }
  return plan
}

// [3] order independence ----------------------------------------------------------------------------------------
{
  const world = (order, lazy = false) => {
    const p = seeded(() => new Figure(model({ motion: CALM })), 11)
    const q = seeded(() => new Figure(model({ motion: CALM })), 13)
    // P faces +z (yaw 0, not the default π), Q the other way: the two chains A hang toward each other.
    p.root.rotation.y = 0
    p.setYaw(0)
    q.root.position.set(0.3, 0, 0)
    q.root.rotation.y = Math.PI
    q.setYaw(Math.PI)
    const figs = new Map([['P', p], ['Q', q]])
    let plan = null, pushed = false
    for (let k = 0; k < 30; k++) {
      p.update(1 / 60, { realDelta: 1 / 60 })
      q.update(1 / 60, { realDelta: 1 / 60 })
      plan = phaseB(figs, order, lazy)
      for (const f of [p, q]) if (f.runtime.secondary.contactTips().some(row => row.partner.length)) pushed = true
    }
    const out = { plan, pushed, p: matrices(p), q: matrices(q) }
    p.dispose(); q.dispose()
    return out
  }
  const pq = world(['P', 'Q']), qp = world(['Q', 'P'])
  check('[3] plan: P reads [Q], Q reads [P]',
    JSON.stringify(pq.plan.get('P')) === '["Q"]' && JSON.stringify(pq.plan.get('Q')) === '["P"]',
    JSON.stringify([...pq.plan]))
  check('[3] the partners push (a contactTips row names a partner capsule)', pq.pushed && qp.pushed)
  check('[3] P→Q and Q→P give bitwise equal bone matrices', same(pq.p, qp.p) && same(pq.q, qp.q),
    firstDiff(pq.p, qp.p) || firstDiff(pq.q, qp.q))
  const lazyPQ = world(['P', 'Q'], true), lazyQP = world(['Q', 'P'], true)
  check('[3] control: lazy snapshots make the two orders differ', !(same(lazyPQ.p, lazyQP.p) && same(lazyPQ.q, lazyQP.q)))
}

// [4] a lone reader and a far-tier reader -------------------------------------------------------------------------
{
  const binds = spyCounts.bind
  const lone = seeded(() => new Figure(model()))
  const far = seeded(() => new Figure(model({ tier: 'low' })))
  const still = seeded(() => new Figure(model({ motion: { rev: 'none', groups: {} } })))
  lone.root.position.set(30, 0, 0)
  far.root.position.set(0, 0, 0)
  still.root.position.set(0.3, 0, 0)
  const figs = new Map([['L', lone], ['F', far], ['G', still]])
  let snapshots = 0, solved = 0
  for (const f of figs.values()) {
    const snap = f.partnerSnapshot.bind(f)
    f.partnerSnapshot = (...args) => { snapshots++; return snap(...args) }
    const real = f.runtime.secondary.update.bind(f.runtime.secondary)
    f.runtime.secondary.update = (dt, options) => { solved++; real(dt, options) }
  }
  let plan = null
  for (let k = 0; k < 5; k++) {
    for (const f of figs.values()) f.update(1 / 60, { realDelta: 1 / 60 })
    plan = phaseB(figs, ['L', 'F', 'G'])
  }
  check('[4] the lone reader reads [], the far-tier and the still figure are no readers',
    JSON.stringify([...plan]) === '[["L",[]]]', JSON.stringify([...plan]))
  check('[4] no partnerSnapshot, no partner bindCollision', snapshots === 0 && spyCounts.bind === binds,
    `snapshots ${snapshots}, binds ${spyCounts.bind - binds}`)
  check('[4] every phase B still ran (3 figures × 5 frames)', solved === 15, String(solved))
  for (const f of figs.values()) f.dispose()
}

// [5] Review Focus 3: a model swap --------------------------------------------------------------------------------
{
  const lib = new FigureLibrary()
  const binds = spyCounts.bind
  const modelA = model({ name: 'One' })
  lib.apiModels.set('P', modelA)
  const a = seeded(() => lib.instantiate('P'))
  const snapA = a.partnerSnapshot(null, 'P')
  check('[5] figure A snapshots, bound once on its instance', !!snapA && spyCounts.bind === binds + 1
    && a.runtime.partnerBoundOn === a.root.children[0], String(spyCounts.bind - binds))
  lib.retireModels('P')
  let threw = null, afterRetire, frameRetired
  try { afterRetire = a.partnerSnapshot(null, 'P'); frameRetired = a.frameFigure('P') } catch (e) { threw = e }
  check('[5] after retireModels: A\'s snapshot and frame are null, its binding dropped',
    !threw && afterRetire === null && frameRetired === null && a.runtime.partnerBinding === null, String(threw ?? ''))
  lib.apiModels.set('P', model({ name: 'Two' }))
  const b = seeded(() => lib.instantiate('P'))
  b.root.position.set(5, 0, 0)
  b.update(1 / 60, { realDelta: 1 / 60 })
  const snapB = b.partnerSnapshot(null, 'P')
  const descends = (o, root) => { for (let n = o; n; n = n.parent) if (n === root) return true; return false }
  const meshes = (b.runtime.partnerBinding?.capsules ?? []).flatMap(c => [c.ja.mesh, c.jb.mesh])
  check('[5] the next snapshot binds on the new instance (spy +2)', !!snapB && spyCounts.bind === binds + 2
    && b.runtime.partnerBoundOn === b.root.children[0], String(spyCounts.bind - binds))
  check('[5] every bound capsule\'s meshes descend from the live root, none from the retired one',
    meshes.length === 8 && meshes.every(m => descends(m, b.root) && !descends(m, a.root)), String(meshes.length))
  check('[5] the capsule ends follow the live figure (x within 5 ± 0.3)',
    snapB.capsules.every(c => [c.now.a, c.now.b].every(p => Math.abs(p[0] - 5) <= 0.3)),
    JSON.stringify(snapB.capsules.map(c => c.now.a[0].toFixed(3))))
  a.dispose()
  lib.freeRetired('P')
  b.dispose()
  check('[5] dispose drops the partner binding', b.runtime.partnerBinding === null)

  const v5 = seeded(() => new Figure(model({ version: 5 })))
  const reader = seeded(() => new Figure(model()))
  v5.root.position.set(0.3, 0, 0)
  let snap5, frame5, plan5
  threw = null
  try {
    snap5 = v5.partnerSnapshot(null, 'V')
    frame5 = v5.frameFigure('V')
    reader.update(1 / 60, { realDelta: 1 / 60 })
    v5.update(1 / 60, { realDelta: 1 / 60 })
    plan5 = phaseB(new Map([['R', reader], ['V', v5]]), ['R', 'V'])
  } catch (e) { threw = e }
  check('[5] a version-5 payload: snapshot null, frame null, nothing thrown',
    !threw && snap5 === null && frame5 === null, String(threw ?? ''))
  check('[5] the reader next to it reads nobody', !plan5?.get('R')?.length, JSON.stringify([...(plan5 ?? [])]))
  v5.dispose(); reader.dispose()
}

// [6] frozen and the photo hold reach phase B ------------------------------------------------------------------------
{
  const fig = seeded(() => new Figure(model()))
  const calls = []
  const real = fig.runtime.secondary.update.bind(fig.runtime.secondary)
  fig.runtime.secondary.update = (dt, options) => { calls.push({ dt, ...options }); real(dt, options) }
  const partners = [{ name: 'X', capsules: [], channels: [], interaction: null }]
  fig.update(1 / 60, { frozen: true, realDelta: 1 / 60 })
  fig.updateSecondary(partners)
  check('[6] update(dt, {frozen}) → one secondary.update, frozen, with the partners',
    calls.length === 1 && calls[0].frozen === true && calls[0].partners === partners, JSON.stringify(calls))
  calls.length = 0
  fig.update(0, { frozen: true })
  fig.updateSecondary([])
  check('[6] the photo hold update(0, {frozen}) → one secondary.update, frozen',
    calls.length === 1 && calls[0].frozen === true, JSON.stringify(calls))
  calls.length = 0
  fig.update(0.01, { realDelta: 0.01 })
  fig.update(0.02, { realDelta: 0.02 })
  fig.updateSecondary([])
  check('[6] two phase A calls, one phase B: one secondary.update with 0.03 s',
    calls.length === 1 && Math.abs(calls[0].dt - 0.03) < 1e-12 && calls[0].frozen === false, JSON.stringify(calls))
  fig.dispose()
}

// [7] channels in the snapshot, the reader's interaction into phase B ----------------------------------------------------
{
  const record = { id: 'pkg:chan', kind: 'channel', a: 'mixamorig:Hips', b: 'mixamorig:Hips', a_pos: [0, 1.0, 0.1],
    b_pos: [0, 1.0, 0.0], r: 0.02, cone_deg: 30, funnel: 0.05, accepts: ['appendage_chain'], min_length: 1,
    compress_min: 0.8, suppress: ['torso'], frame: { side: [1, 0, 0], up: [0, 1, 0], front: [0, 0, 1] },
    placement: 'declared', applied: null }
  const fig = seeded(() => new Figure(model({ channels: [record] })))
  fig.root.position.set(2, 0, 0)
  const near = (v, w) => v.every((x, i) => Math.abs(x - w[i]) <= 1e-9)
  const s1 = fig.partnerSnapshot({ id: 'i1', kind: 'k' }, 'P')
  const c1 = s1?.channels[0]
  check('[7] the snapshot carries the channel in the world: o (2, 1, 0.1), u (0, 0, −1), D 0.1, r 0.02',
    s1?.channels.length === 1 && c1.id === 'pkg:chan' && near(c1.o, [2, 1, 0.1]) && near(c1.u, [0, 0, -1])
    && Math.abs(c1.depth - 0.1) <= 1e-9 && Math.abs(c1.r - 0.02) <= 1e-9, JSON.stringify(c1 && { o: c1.o, u: c1.u }))
  check('[7] … and the owner\'s interaction', s1?.interaction?.id === 'i1' && s1.interaction.kind === 'k')
  fig.root.position.set(3, 0, 0)
  const s2 = fig.partnerSnapshot(null, 'P')
  check('[7] a later snapshot has its own frame (3 vs the first\'s 2)', Math.abs(s2.channels[0].o[0] - 3) <= 1e-9
    && Math.abs(c1.o[0] - 2) <= 1e-9 && s2.channels !== s1.channels)
  const plain = seeded(() => new Figure(model()))
  check('[7] without a channel record: channels []', Array.isArray(plain.partnerSnapshot(null, 'Q')?.channels)
    && plain.partnerSnapshot(null, 'Q').channels.length === 0)
  const calls = []
  const real = plain.runtime.secondary.update.bind(plain.runtime.secondary)
  plain.runtime.secondary.update = (dt, options) => { calls.push(options); real(dt, options) }
  plain.update(1 / 60, { realDelta: 1 / 60 })
  plain.updateSecondary([s1], { id: 'i1' })
  plain.update(1 / 60, { realDelta: 1 / 60 })
  plain.updateSecondary([s1])
  check('[7] updateSecondary hands the reader\'s interaction to the secondary motion (null by default)',
    calls.length === 2 && calls[0].interaction?.id === 'i1' && calls[1].interaction === null, JSON.stringify(calls.map(c => c.interaction)))
  fig.dispose(); plain.dispose()
}

console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed')
assert.equal(failures, 0)
