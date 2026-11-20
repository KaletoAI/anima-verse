#!/usr/bin/env node
/**
 * Exporter of the per-strand hair vectors for the native port (stage 4 of the hair port): shared/test-vectors/
 * strand_sim.json (the pure sim, packages/scene-render/src/hairSimMath.ts) and shared/test-vectors/strand_clock.json
 * (the clock of packages/scene-render/src/hairSim.ts, run through three exactly as the browser runs it). Every
 * expectation is the OUTPUT OF THE TYPESCRIPT, never of the C# — native/tests/StrandVectorTests.cs replays the files.
 * The hand derivations stay in scripts/smoke_hair_sim.mjs (cases named after its numbers); this script asserts the
 * hand numbers of that smoke on the TypeScript before it writes anything (a drift stops the export).
 *
 * Usage:
 *   node scripts/export_strand_vectors.mjs           write the two files
 *   node scripts/export_strand_vectors.mjs --check   regenerate in memory, replay the files on disk through the
 *                                                    TypeScript (shared/test-vectors/vectors.mjs runVectors) and fail
 *                                                    when a file differs from what the TypeScript gives now
 * No server, no world, no DOM. Needs the root node_modules (three, esbuild).
 *
 * FIXTURES are RECIPES, not data: the adapters build the record + hair primitive from a "build" spec exactly as
 * smoke_hair_sim.mjs does (the head sphere SDF, curved fan cards, straight cards), and native/tests/StrandVectorTests.cs
 * mirrors that builder; the case "[fx] fixture digest" pins the built inputs (SDF sum and weighted sum exact, the
 * float sums to 1e-9), so a builder that drifted on either side fails there first.
 *
 * ADAPTERS (mirrored by native/tests/StrandVectorTests.cs). Matrices column-major 16 numbers.
 *   build spec = {fan?: n, cards?: [{curved: thetaDeg | straight: [x, z, y0?, gap?], pins, side}], spine?: true
 *     (bones [Head, Spine2], rows with y < 1.52 follow Spine2), torso?: true (the chest capsule of [7]), params?: {…}}
 *   strandParams(params) → object (a NaN as the string "NaN": JSON has none);  limitSegmentAngle(prev, cur, restDir, cosLim) → point
 *   lerpFrame(a, b, s) → matrix;  boxDepth(box, x, y, z) → [depth, exit]
 *   sdfAt(points) → [[sdf, gx, gy, gz]] on the fixture SDF (gradient through a Float32Array, as the sim reads it)
 *   fixtureDigest(build) → sums;  bind(build) → the binding arrays (small builds only)
 *   run(build, run) — smoke_hair_sim's spike loop: run = {kind, seconds, settle, params?, capsules?: 'torso',
 *     snapshots: [step], full?: [step], rebuild?: step, metrics?: true} → {snapshots: [{step, X}], rebuild?: {pos, nrm},
 *     deep, eye}. A snapshot holds rows 4, 10 and 16 of every card ("sampled"), all rows at a "full" step; a
 *     rebuild every 7th vertex (the full arrays made the files MBs).
 *   rest1(build) → max |rebuilt − rest| (positions, normals) after 120 steps at rest
 *   haar6(rootDeg) / clamp9 / tether10 / walk11 / lastWord12 / gravity14(deg, steps, loose) → the rows after;
 *   gravityOff14(deg) → max |hang − targets| after one step (0 = bit for bit)
 *   inertia13(roots, dt) → carries (null = identity);  carry13e(m) → X, Xp
 *   mismatch8(which) → throws;  pick(candidates, limits?) → names in admission order
 *   strandClock(spec) → hairSim.ts createStrandHair on a three rig (group → Spine2 → Head, one skinned hair mesh
 *     carrying _strand_card / _strand_u): per frame the group's matrix, the bones' local rotations, update(dt,
 *     {frozen}); X and the mesh's position / normal arrays at the recorded frames.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import assert from 'node:assert/strict'
import { build as esbuild } from 'esbuild'
import * as THREE from 'three'
import { parseVectors, runVectors } from '../shared/test-vectors/vectors.mjs'

const root = fileURLToPath(new URL('../', import.meta.url))
const SRC = root + 'packages/scene-render/src/'

async function modules() {
  const dir = await mkdtemp(join(root, 'scripts/.export-strand-vectors-'))
  try {
    const result = await esbuild({ stdin: { contents: [
      "export * as M from '" + SRC + "hairSimMath.ts'",
      "export * as H from '" + SRC + "hairSim.ts'",
      "export * as C from '" + SRC + "collision.ts'"].join('\n'), resolveDir: root, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false, external: ['three', 'three/*'], logLevel: 'error' })
    const file = join(dir, 'strand.mjs')
    await writeFile(file, result.outputFiles[0].text)
    return await import('file://' + file)
  } finally { await rm(dir, { recursive: true, force: true }) }
}
const { M, H, C: Col } = await modules()

// ---- the fixture (smoke_hair_sim.mjs, verbatim arithmetic) -------------------------------------------------------

const R = M.STRAND_ROWS
const C = [0, 1.60, 0], RAD = 0.09, RHO = 0.092, EAR = 1.5625
const ALPHA0 = 30 * Math.PI / 180, SPHERE_ARC = RHO * (Math.PI / 2 - ALPHA0)
const FACE_BOX = [-0.06, 0.06, 1.48, 1.66, 0.0225], EYE_BOX = [-0.04, 0.04, 1.555, 1.645, 0.0225]
const PARAMS = { damping: 0.04, stiffness: 1.0, bend: 0.15, iterations: 6, root_deg: 10, root_frac: 0.2,
  fly_soft: true, fly_arc: 0.30, tether: true, tether_r0: 0.015, tether_r1: 0.06, tether_head: 0.012,
  head_clr: 0.03, face_box: true }
const DT = 1 / 60

function sdfPayload() {
  const lo = [-0.15, 1.46, -0.16], vox = 0.0068, dims = [45, 44, 48]
  const q = new Int8Array(dims[0] * dims[1] * dims[2])
  for (let iz = 0; iz < dims[2]; iz++) for (let iy = 0; iy < dims[1]; iy++) for (let ix = 0; ix < dims[0]; ix++) {
    const x = lo[0] + ix * vox, y = lo[1] + iy * vox, z = lo[2] + iz * vox
    const d = Math.hypot(x - C[0], y - C[1], z - C[2]) - RAD
    q[ix + dims[0] * (iy + dims[1] * iz)] = Math.max(-127, Math.min(127, Math.round(d * 1000)))
  }
  return { dims, lo, vox, order: 'x_fastest', unit: 'mm_int8', data: Buffer.from(q.buffer).toString('base64') }
}
const SDF = sdfPayload()

function curvedRows(theta) {
  const st = Math.sin(theta), ct = Math.cos(theta), rows = []
  for (let i = 0; i < R; i++) {
    const s = 0.02 * i
    if (s <= SPHERE_ARC) {
      const a = ALPHA0 + s / RHO
      rows.push([RHO * Math.sin(a) * st, C[1] + RHO * Math.cos(a), RHO * Math.sin(a) * ct])
    } else rows.push([RHO * st, C[1] - (s - SPHERE_ARC), RHO * ct])
  }
  return rows
}
const straightRows = (x, z, y0 = 1.60, gap = 0.02) => Array.from({ length: R }, (_, i) => [x, y0 - gap * i, z])
const TORSO = { id: 'chest', a: 'mixamorig:Spine2', b: 'mixamorig:Spine2', r: 0.08, region: 'torso',
  a_pos: [0, 1.0, 0], b_pos: [0, 1.45, 0] }

function buildFrom(cards, { bones = ['mixamorig:Head'], followOf = () => [1], capsules = [], params = PARAMS } = {}) {
  const rest = [], pins = [], freeArc = [], freeFrac = [], w = [], pos = [], nrm = [], card = [], u = []
  cards.forEach((cd, k) => {
    pins.push(cd.pins)
    const arc = [0]
    for (let i = 1; i < R; i++) arc.push(arc[i - 1] + Math.hypot(...cd.rows[i].map((v, d) => v - cd.rows[i - 1][d])))
    const last = arc[cd.pins - 1], total = arc[R - 1] - last
    cd.rows.forEach((p, i) => {
      rest.push(...p)
      const fa = i < cd.pins ? 0 : arc[i] - last
      freeArc.push(fa); freeFrac.push(i < cd.pins ? 0 : fa / total)
      w.push(...followOf(p, i))
      const n = [p[0] - C[0], p[1] - C[1], p[2] - C[2]], nl = Math.hypot(...n)
      for (const sgn of [-1, 1]) {
        pos.push(p[0] + sgn * 0.004 * cd.side[0], p[1] + sgn * 0.004 * cd.side[1], p[2] + sgn * 0.004 * cd.side[2])
        nrm.push(n[0] / nl, n[1] / nl, n[2] / nl)
        card.push(k + 1); u.push(i)
      }
    })
  })
  for (const [x, z] of [[-0.02, -0.02], [0.02, -0.02], [0.02, 0.02], [-0.02, 0.02]]) {
    pos.push(x, 1.695, z); nrm.push(0, 1, 0); card.push(0); u.push(0)
  }
  const record = { version: 2, item_id: 'hair_fixture', fsig: '0123456789ab', mode: 'hairdeck', fit_sha256: '0',
    frame: 'head_bind', head_bone: 'mixamorig:Head', rows: R, cards: cards.length, rest, pins,
    free_arc: freeArc, free_frac: freeFrac, follow: { bones, w }, ear_y: EAR, face_box: FACE_BOX, eye_box: EYE_BOX,
    landmarks: 'fallback', sdf: SDF, capsules: { version: Col.COLLISION_VERSION, capsules, scales: {} }, params,
    vertex_attributes: { card: '_STRAND_CARD', u: '_STRAND_U' } }
  const prim = { pos: Float32Array.from(pos), nrm: Float32Array.from(nrm), card: Uint16Array.from(card),
    u: Float32Array.from(u) }
  return { record, prim }
}
const curvedCard = theta => ({ rows: curvedRows(theta), pins: 3, side: [Math.cos(theta), 0, -Math.sin(theta)] })
const fan = n => Array.from({ length: n }, (_, k) => curvedCard((75 + (k + 0.5) * 210 / n) * Math.PI / 180))

/** A build spec (module docstring) → {record, prim}. */
function build(spec) {
  const cards = [...(spec.fan ? fan(spec.fan) : [])]
  for (const c of spec.cards ?? []) {
    if (c.curved !== undefined) { cards.push(curvedCard(c.curved * Math.PI / 180)); continue }
    const [x, z, y0 = 1.60, gap = 0.02] = c.straight
    cards.push({ rows: straightRows(x, z, y0, gap), pins: c.pins, side: c.side })
  }
  const opts = { params: { ...PARAMS, ...(spec.params ?? {}) } }
  if (spec.spine) { opts.bones = ['mixamorig:Head', 'mixamorig:Spine2']; opts.followOf = p => (p[1] < 1.52 ? [0, 1] : [1, 0]) }
  if (spec.torso) opts.capsules = [TORSO]
  return buildFrom(cards, opts)
}

function rootMotion(kind, t, amp, pivot = [0, EAR, 0]) {
  let yaw = 0, pitch = 0, ox = 0, oy = 0, oz = 0
  if (kind === 'sway') {
    yaw = amp * (15 * Math.PI / 180) * Math.sin(2 * Math.PI * 0.5 * t)
    pitch = amp * (5 * Math.PI / 180) * Math.sin(2 * Math.PI * 0.5 * t + Math.PI / 2)
  } else if (kind === 'walk') {
    oz = amp * 0.25 * Math.sin(2 * Math.PI * 0.5 * t)
    oy = amp * 0.015 * (1 - Math.cos(2 * Math.PI * 1.0 * t))
  }
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch)
  const Rm = [cy, sy * sp, sy * cp, 0, cp, -sp, -sy, cy * sp, cy * cp]
  const T = [0, 1, 2].map(r => pivot[r] - (Rm[3 * r] * pivot[0] + Rm[3 * r + 1] * pivot[1] + Rm[3 * r + 2] * pivot[2]))
  T[0] += ox; T[1] += oy; T[2] += oz
  return [Rm[0], Rm[3], Rm[6], 0, Rm[1], Rm[4], Rm[7], 0, Rm[2], Rm[5], Rm[8], 0, T[0], T[1], T[2], 1]
}

function makeSim(fx) {
  const b = M.bindStrands(fx.record, fx.prim.pos, fx.prim.nrm, fx.prim.card, fx.prim.u)
  return new M.StrandSim(b, fx.record)
}
function frameOf(record, m, capsules = []) {
  const targets = new Float32Array(record.cards * R * 3)
  M.strandTargets(record, record.follow.bones.map(() => m), targets)
  return { targets, head: m, capsules }
}
const xf = (m, p) => [m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12], m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
  m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14]]
/** [7]'s torso capsule now under the figure matrix m, bind = its bind ends (one object per sim: the factor key). */
const torsoNow = (m, bind) => [{ a: xf(m, TORSO.a_pos), b: xf(m, TORSO.b_pos), r: 0.08, bind }]

/** float32 values, shortest exact text (9 significant digits round-trip a float32). */
const f32 = a => Array.from(a, v => Number(Math.fround(v).toPrecision(9)))
const rowOf = (sim, q) => [sim.X[3 * q], sim.X[3 * q + 1], sim.X[3 * q + 2]]
/** The sampled rows of a run's snapshot: rows 4, 10 and 16 of every card (the full arrays would make the files MBs). */
const SAMPLED = [4, 10, 16]
const sampled = X => { const out = []; for (let c = 0; c < X.length / (3 * R); c++) for (const i of SAMPLED) for (let d = 0; d < 3; d++) out.push(X[3 * (c * R + i) + d]); return f32(out) }
/** Every 7th vertex of a rebuilt attribute. */
const everySeventh = A => { const out = []; for (let v = 0; v < A.length / 3; v += 7) out.push(A[3 * v], A[3 * v + 1], A[3 * v + 2]); return f32(out) }

// ---- the dispatch (TypeScript side) ----------------------------------------------------------------------------

function run(spec, r) {
  const fx = build(spec), sim = makeSim(fx), p = { ...M.strandParams(fx.record.params), ...(r.params ?? {}) }
  const bind = { a: TORSO.a_pos, b: TORSO.b_pos }
  const snaps = new Set(r.snapshots ?? []), out = { snapshots: [] }
  const restEye = M.restInsideBox(sim, EYE_BOX)
  let amp = 0, deep = 0, eye = 0
  sim.reset(frameOf(fx.record, rootMotion(r.kind, 0, 0)).targets)
  const N = Math.round((r.seconds + r.settle) / DT)
  for (let s = 0; s < N; s++) {
    const t = s * DT
    amp += ((t < r.seconds ? 1 : 0) - amp) * Math.min(1, DT / 0.5)
    const m = rootMotion(r.kind, t, amp)
    const f = frameOf(fx.record, m, r.capsules === 'torso' ? torsoNow(m, bind) : [])
    sim.step(DT, f, p)
    if (r.metrics && s % 6 === 0) {
      deep = Math.max(deep, M.maxSdfDepthMm(sim, m, sim.sdf))
      eye = Math.max(eye, M.eyePointsEntered(sim, m, EYE_BOX, restEye))
    }
    if (snaps.has(s)) out.snapshots.push({ step: s, X: r.full?.includes(s) ? f32(sim.X) : sampled(sim.X) })
    if (r.rebuild === s) {
      const pos = new Float32Array(fx.prim.pos.length), nrm = new Float32Array(pos.length)
      sim.rebuild(M.invertAffine(m), pos, nrm)
      out.rebuild = { pos: everySeventh(pos), nrm: everySeventh(nrm) }
    }
  }
  if (r.metrics) { out.deep = deep; out.eye = eye }
  return out
}

function rest1(spec) {
  const fx = build(spec), sim = makeSim(fx), I = rootMotion('off', 0, 0), f = frameOf(fx.record, I)
  const prm = M.strandParams(fx.record.params)
  sim.reset(f.targets)
  for (let s = 0; s < 120; s++) sim.step(DT, f, prm)
  const pos = new Float32Array(fx.prim.pos.length), nrm = new Float32Array(fx.prim.nrm.length)
  sim.rebuild(M.invertAffine(I), pos, nrm)
  let dp = 0, dn = 0
  for (let i = 0; i < pos.length; i++) {
    dp = Math.max(dp, Math.abs(pos[i] - fx.prim.pos[i])); dn = Math.max(dn, Math.abs(nrm[i] - fx.prim.nrm[i]))
  }
  return [dp, dn]
}

const STRAIGHT = { cards: [{ straight: [0.5, 0], pins: 2, side: [1, 0, 0] }] }
const STRAIGHT_Z = { cards: [{ straight: [0.5, 0], pins: 2, side: [0, 0, 1] }] }
const stillOf = prm => ({ ...prm, iterations: 0, bend: 0, rootDeg: 0, tether: false })

function haar6(rootDeg) {
  const fx = build(STRAIGHT), sim = makeSim(fx), I = rootMotion('off', 0, 0), f = frameOf(fx.record, I)
  sim.reset(f.targets)
  const c = Math.cos(Math.PI / 6), s = Math.sin(Math.PI / 6), p1 = [0.5, 1.58, 0]
  for (let i = 2; i < R; i++) {
    const dx = sim.X[3 * i] - p1[0], dy = sim.X[3 * i + 1] - p1[1]
    sim.X[3 * i] = sim.Xp[3 * i] = p1[0] + c * dx - s * dy
    sim.X[3 * i + 1] = sim.Xp[3 * i + 1] = p1[1] + s * dx + c * dy
  }
  sim.step(0, f, { ...M.strandParams(fx.record.params), rootDeg, bend: 0, tether: false })
  return f32(sim.X)
}

function follow7(withCapsule) {
  const pitch = 30 * Math.PI / 180, c = Math.cos(pitch), s = Math.sin(pitch)
  const P = [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 1.30 - 1.30 * c, -1.30 * s, 1]
  const fx = build({ fan: 60, cards: [{ straight: [0, -0.10], pins: 2, side: [1, 0, 0] },
    { straight: [0, -0.095, 1.60, 0.03], pins: 2, side: [1, 0, 0] }], spine: true, torso: true })
  const sim = makeSim(fx), prm = M.strandParams(fx.record.params)
  const T = new Float32Array(fx.record.cards * R * 3)
  M.strandTargets(fx.record, [P, P], T)
  const caps = withCapsule ? torsoNow(P, { a: TORSO.a_pos, b: TORSO.b_pos }) : []
  sim.reset(frameOf(fx.record, rootMotion('off', 0, 0)).targets)
  const f = frameOf(fx.record, P, caps)
  const mid = []
  for (let st = 0; st < 120; st++) {
    sim.step(DT, f, prm)
    if (st === 29) mid.push(...sampled(sim.X))
  }
  return { targets: sampled(T), X30: mid, X: f32(sim.X) }
}

function clamp9() {
  const fx = build(STRAIGHT_Z), sim = makeSim(fx), f = frameOf(fx.record, rootMotion('off', 0, 0))
  sim.reset(f.targets)
  sim.X[27] += 0.10; sim.Xp[27] += 0.10
  sim.step(0, f, stillOf(M.strandParams(fx.record.params)))
  return f32(sim.X)
}

function tether10() {
  const theta = Math.PI, rows = curvedRows(theta)
  const r3 = rows[3], rr = Math.hypot(r3[0] - C[0], r3[1] - C[1], r3[2] - C[2])
  rows[3] = r3.map((v, d) => C[d] + (v - C[d]) * (rr + 0.04) / rr)
  const fx = buildFrom([{ rows, pins: 3, side: [Math.cos(theta), 0, -Math.sin(theta)] }])
  const sim = makeSim(fx), f = frameOf(fx.record, rootMotion('off', 0, 0))
  const p = { ...stillOf(M.strandParams(fx.record.params)), tether: true, tetherR0: 10, tetherR1: 10 }
  const turn = sign => {
    sim.reset(f.targets)
    const a = sign * 25 * Math.PI / 180, c = Math.cos(a), sn = Math.sin(a), p3 = rowOf(sim, 3)
    for (let i = 4; i < R; i++) {
      const dy = sim.X[3 * i + 1] - p3[1], dz = sim.X[3 * i + 2] - p3[2]
      sim.X[3 * i + 1] = sim.Xp[3 * i + 1] = p3[1] + c * dy - sn * dz
      sim.X[3 * i + 2] = sim.Xp[3 * i + 2] = p3[2] + sn * dy + c * dz
    }
    return Math.hypot(...[0, 1, 2].map(d => sim.X[18 + d] - C[d]))
  }
  const sign = turn(1) > turn(-1) ? 1 : -1
  turn(sign)
  const before = f32(sim.X), onHead = f32(sim.onHead)
  sim.step(0, f, p)
  return { before, onHead, X: f32(sim.X) }
}

function walk11() {
  const fx = build(STRAIGHT_Z), sim = makeSim(fx), prm = M.strandParams(fx.record.params)
  const at = t => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 3.4 * t, 1]
  sim.reset(frameOf(fx.record, at(0)).targets)
  const snaps = []
  for (let st = 1; st <= 240; st++) {
    sim.step(DT, frameOf(fx.record, at(st * DT)), prm)
    if (st % 60 === 0) snaps.push(st === 240 ? f32(sim.X) : sampled(sim.X))
  }
  return snaps
}

function lastWord12() {
  const fx = build({ cards: [{ straight: [0, -0.095], pins: 2, side: [1, 0, 0] }] })
  const sim = makeSim(fx), prm = M.strandParams(fx.record.params)
  const cap = { a: [0, 1.56, -0.135], b: [0, 1.56, -0.135], r: 0.06, bind: { a: [0, 0, 5], b: [0, 0, 5] } }
  const f = frameOf(fx.record, rootMotion('off', 0, 0), [cap])
  sim.reset(f.targets)
  sim.step(0, f, { ...stillOf(prm), faceBox: false })
  return f32(sim.X)
}

function inertia13(roots, dt) {
  const ri = new M.RootInertia()
  return roots.map(m => ri.update(m, dt))
}

function carry13e(m) {
  const fx = build(STRAIGHT_Z), sim = makeSim(fx)
  sim.reset(frameOf(fx.record, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]).targets)
  for (let q = 0; q < sim.X.length; q++) sim.Xp[q] -= 0.001 * (q % 3 === 2 ? 1 : 0)
  sim.carry(m)
  return { X: f32(sim.X), Xp: f32(sim.Xp) }
}

function gravity14(deg, steps, loose) {
  const fx = build(STRAIGHT), sim = makeSim(fx), P = [0.5, 1.58, 0], prm = M.strandParams(fx.record.params)
  const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a)
  const Mt = [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, P[1] - (c * P[1] - s * P[2]), P[2] - (s * P[1] + c * P[2]), 1]
  const I = rootMotion('off', 0, 0)
  const p = loose ? { ...prm, bend: 0, rootDeg: 0 } : prm
  const f = frameOf(fx.record, Mt)
  if (steps === 1) sim.reset(f.targets); else sim.reset(frameOf(fx.record, I).targets)
  for (let st = 0; st < steps; st++) sim.step(DT, f, p)
  return { hang: f32(sim.hang), targets: f32(f.targets), X: f32(sim.X) }
}

function mismatch8(which) {
  const fx = build({ fan: 60, cards: [{ straight: [0, -0.10], pins: 2, side: [1, 0, 0] }] })
  if (which === 'card') {
    const card = Uint16Array.from(fx.prim.card); card[0] = 62
    return M.bindStrands(fx.record, fx.prim.pos, fx.prim.nrm, card, fx.prim.u)
  }
  return M.bindStrands(fx.record, fx.prim.pos, fx.prim.nrm, fx.prim.card, fx.prim.u.subarray(1))
}

function fixtureDigest(spec) {
  const fx = build(spec)
  const q = M.decodeStrandSdf(fx.record.sdf).q
  let sdfSum = 0, sdfWeighted = 0
  for (let i = 0; i < q.length; i++) { sdfSum += q[i]; sdfWeighted += q[i] * (i % 9973) }
  const sum = a => Array.from(a).reduce((s, v) => s + v, 0)
  return { sdfSum, sdfWeighted, rest: sum(fx.record.rest), freeArc: sum(fx.record.free_arc), freeFrac: sum(fx.record.free_frac),
    w: sum(fx.record.follow.w), pins: sum(fx.record.pins), pos: sum(fx.prim.pos), nrm: sum(fx.prim.nrm), card: sum(fx.prim.card),
    u: sum(fx.prim.u), cards: fx.record.cards, vertices: fx.prim.card.length }
}

function bindValue(spec) {
  const fx = build(spec)
  const b = M.bindStrands(fx.record, fx.prim.pos, fx.prim.nrm, fx.prim.card, fx.prim.u)
  return { C0: f32(b.C0), N00: Array.from(b.N00), vk: Array.from(b.vk), va: Array.from(b.va), vt: Array.from(b.vt),
    off: Array.from(b.off), noff: Array.from(b.noff), cStart: Array.from(b.cStart), cVerts: Array.from(b.cVerts),
    rigid: Array.from(b.rigid) }
}

function sdfAt(points) {
  const sdf = M.decodeStrandSdf(SDF), g = new Float32Array(3)
  return points.map(p => { const s = M.strandSdfAt(sdf, p[0], p[1], p[2], g); return [s, g[0], g[1], g[2]] })
}

const compose = (p, q) => new THREE.Matrix4().compose(new THREE.Vector3(...p), new THREE.Quaternion(...q), new THREE.Vector3(1, 1, 1))

/** hairSim.ts createStrandHair on a three rig (module docstring). */
function strandClock(spec) {
  const fx = build(spec.build)
  const group = new THREE.Group()
  group.matrixAutoUpdate = false
  const spine = new THREE.Bone(); spine.name = 'mixamorig:Spine2'; spine.position.set(0, 1.30, 0)
  const head = new THREE.Bone(); head.name = 'mixamorig:Head'; head.position.set(0, 0.30, 0)
  group.add(spine); spine.add(head)
  const nv = fx.prim.card.length
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(Float32Array.from(fx.prim.pos), 3))
  geo.setAttribute('normal', new THREE.BufferAttribute(Float32Array.from(fx.prim.nrm), 3))
  const si = new Uint16Array(4 * nv), sw = new Float32Array(4 * nv)
  for (let v = 0; v < nv; v++) { si[4 * v] = 1; sw[4 * v] = 1 }
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(si, 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(sw, 4))
  geo.setAttribute('_strand_card', new THREE.Uint16BufferAttribute(Uint16Array.from(fx.prim.card), 1))
  geo.setAttribute('_strand_u', new THREE.Float32BufferAttribute(Float32Array.from(fx.prim.u), 1))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  group.add(mesh)
  group.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([spine, head]))
  const pose = f => {
    group.matrix.fromArray(f.root ?? spec.root0)
    if (f.spine) spine.quaternion.fromArray(f.spine)
    if (f.head) head.quaternion.fromArray(f.head)
    group.updateMatrixWorld(true)
  }
  pose({ root: spec.root0 })
  const hair = H.createStrandHair(THREE, group, fx.record)
  assert.ok(hair, 'strandClock: createStrandHair bound nothing')
  try {
    hair.setEnabled(true)
    const record = new Set(spec.record), out = { capsuleIds: [...hair.capsuleIds], frames: [] }
    spec.frames.forEach((f, k) => {
      pose(f)
      hair.update(f.dt, { frozen: !!f.frozen })
      if (record.has(k + 1)) {
        const entry = { frame: k + 1 }
        if (!spec.restDev) entry.X = spec.full?.includes(k + 1) ? f32(hair.sim.X) : sampled(hair.sim.X)
        const pos = mesh.geometry.getAttribute('position').array, nrm = mesh.geometry.getAttribute('normal').array
        if (spec.mesh?.includes(k + 1)) { entry.pos = everySeventh(pos); entry.nrm = everySeventh(nrm) }
        if (spec.restDev) {
          let dp = 0, dn = 0
          for (let i = 0; i < pos.length; i++) { dp = Math.max(dp, Math.abs(pos[i] - fx.prim.pos[i])); dn = Math.max(dn, Math.abs(nrm[i] - fx.prim.nrm[i])) }
          entry.restDev = [dp, dn]
        }
        out.frames.push(entry)
      }
    })
    return out
  } finally { hair.dispose(); geo.dispose(); mesh.material.dispose() }
}

export const dispatch = {
  strandParams: params => Object.fromEntries(Object.entries(M.strandParams(params)).map(([k, v]) => [k, Number.isNaN(v) ? 'NaN' : v])),
  limitSegmentAngle: (prev, cur, restDir, cosLim) => M.limitSegmentAngle(prev, cur, restDir, cosLim),
  lerpFrame: (a, b, s) => M.lerpFrame(a, b, s, new Array(16).fill(0)),
  boxDepth: (box, x, y, z) => M.boxDepth(box, x, y, z),
  sdfAt,
  fixtureDigest,
  bind: bindValue,
  run,
  rest1,
  haar6,
  follow7,
  clamp9,
  tether10,
  walk11,
  lastWord12,
  inertia13,
  carry13e,
  gravity14,
  mismatch8,
  gravityOff14: deg => { const g = gravity14(deg, 1, false); return Math.max(...g.hang.map((v, i) => Math.abs(v - g.targets[i]))) },
  pick: (cands, limits) => [...M.pickStrandFigures(cands, limits ?? undefined)],
  strandClock,
}

// ---- the cases --------------------------------------------------------------------------------------------------

const cases = { sim: [], clock: [] }
const add = (file, label, fn, args, eps) => {
  let expect
  try { expect = dispatch[fn](...structuredClone(args)) } catch (e) {
    if (!(e instanceof M.StrandMismatch)) throw e
    expect = { $throws: true }
  }
  cases[file].push({ label, fn, args, expect: JSON.parse(JSON.stringify(expect)), ...(eps !== undefined ? { eps } : {}) })
  return expect
}
const near = (a, b, eps) => a.length === b.length && a.every((x, i) => Math.abs(x - b[i]) <= eps)
const MAIN = { fan: 60 }
/** The tolerance of the sim runs (m): float32 rows, V8's and .NET's libm differ in the last bit of sin/cos/acos. */
const RUN = 1e-7

add('sim', '[fx] fixture digest: the 60-card fan', 'fixtureDigest', [MAIN])
add('sim', '[fx] fixture digest: [7] spine + torso + back + long card', 'fixtureDigest',
  [{ fan: 60, cards: [{ straight: [0, -0.10], pins: 2, side: [1, 0, 0] }, { straight: [0, -0.095, 1.60, 0.03], pins: 2, side: [1, 0, 0] }], spine: true, torso: true }])
const prm0 = add('sim', '[0] strandParams maps the record params', 'strandParams', [PARAMS])
assert.ok(prm0.rootDeg === 10 && prm0.tetherR1 === 0.06 && prm0.flyArc === 0.30 && prm0.faceBox === true && prm0.iterations === 6)
add('sim', '[0] strandParams: JS Number / !! of odd values', 'strandParams', [{ damping: '0.5', stiffness: true, bend: null,
  iterations: 3, fly_soft: 0, tether: 'yes', face_box: false }])

// [1] rest
const r1 = add('sim', '[1] rest: 120 steps, max |rebuilt − rest| == 0 (positions, normals)', 'rest1', [MAIN], 0)
assert.ok(r1[0] === 0 && r1[1] === 0, '[1] ' + r1)

// [2] limitSegmentAngle
const lim = add('sim', '[2] 30° limited to 10°', 'limitSegmentAngle', [[0, 0, 0], [0.05, -0.0866025, 0], [0, -1, 0], Math.cos(10 * Math.PI / 180)], 1e-12)
assert.ok(near(lim, [0.0173648, -0.0984808, 0], 1e-6), '[2] ' + lim)
add('sim', '[2] 5° within the limit: unchanged', 'limitSegmentAngle',
  [[0, 0, 0], [0.1 * Math.sin(5 * Math.PI / 180), -0.1 * Math.cos(5 * Math.PI / 180), 0], [0, -1, 0], Math.cos(10 * Math.PI / 180)], 0)
add('sim', '[2] degenerate rest direction and a zero segment', 'limitSegmentAngle', [[0, 0, 0], [0, 0, 0], [0, 0, 0], 0.5], 0)

// small maths
const rx = d => { const a = d * Math.PI / 180; return [1, 0, 0, 0, 0, Math.cos(a), Math.sin(a), 0, 0, -Math.sin(a), Math.cos(a), 0, 0.1, 1.5, -0.2, 1] }
const ryS = (d, s) => { const a = d * Math.PI / 180; return [s * Math.cos(a), 0, -s * Math.sin(a), 0, 0, s, 0, 0, s * Math.sin(a), 0, s * Math.cos(a), 0, 1, 2, 3, 1] }
for (const s of [-0.1, 0, 0.25, 0.5, 0.9, 1, 1.2])
  add('sim', '[H-R11] lerpFrame Rx(10°) → Ry(80°)·1.1, s ' + s, 'lerpFrame', [rx(10), ryS(80, 1.1), s], 1e-12)
add('sim', '[H-R11] lerpFrame nearly equal rotations (the normalised linear blend)', 'lerpFrame', [rx(10), rx(10.01), 0.3], 1e-12)
add('sim', '[H-R11] lerpFrame a 170° turn', 'lerpFrame', [rx(0), rx(170), 0.5], 1e-12)
for (const [p, label] of [[[0, 1.6, 0.05], 'inside, nearest exit +y? no: −x'], [[0.055, 1.6, 0.05], '+x'], [[0, 1.655, 0.05], '+y'],
  [[0, 1.6, 0.02], 'behind z0'], [[0.07, 1.6, 0.05], 'outside x']])
  add('sim', '[box] boxDepth ' + p.join(', ') + ' (' + label + ')', 'boxDepth', [FACE_BOX, ...p], 1e-12)
add('sim', '[sdf] strandSdfAt on the fixture sphere (value and float32 gradient)', 'sdfAt',
  [[[0, 1.6, 0], [0.05, 1.65, -0.03], [0.0921, 1.6, 0.0013], [0.2, 1.6, 0], [-0.1499, 1.461, -0.159], [0, 1.69, 0.0003], [0.01, 1.7, 0.01]]], 1e-12)

// binding of a small build
add('sim', '[bind] bindStrands: two curved cards + one straight + the cap', 'bind',
  [{ cards: [{ curved: 120 }, { curved: 200 }, { straight: [0.5, 0], pins: 2, side: [1, 0, 0] }] }], 1e-8)

// [3] [4] spike runs
add('sim', '[3] sway 4 s: the rows at step 239', 'run', [MAIN, { kind: 'sway', seconds: 4, settle: 0, snapshots: [59, 239] }], RUN)
for (const kind of ['sway', 'walk']) {
  const got = add('sim', '[4] ' + kind + ' 8 s + 6 s settle: rows, rebuild, SDF depth, eye box', 'run',
    [MAIN, { kind, seconds: 8, settle: 6, snapshots: [239, 479, 839], full: kind === 'sway' ? [839] : [], rebuild: 479, metrics: true }], RUN)
  assert.ok(got.deep <= 3 && got.eye === 0, '[4] ' + kind + ' ' + got.deep + ' ' + got.eye)
}

// [6] HAAR / HairDeck
const h0 = add('sim', '[6] HAAR (root_deg 0): the 30° chain is not limited', 'haar6', [0], RUN)
const h10 = add('sim', '[6] HairDeck (root_deg 10): the segment 1→2 turned back to 10°', 'haar6', [10], RUN)
{
  const d = [h10[6] - h10[3], h10[7] - h10[4], h10[8] - h10[5]]
  const ang = Math.acos(-d[1] / Math.hypot(...d)) * 180 / Math.PI
  assert.ok(Math.abs(ang - 10) <= 1e-4, '[6] ' + ang)
}

// [7] follow rows + torso capsule
const f7 = add('sim', '[7] pitched spine, torso capsule under the bind rule: 2 s', 'follow7', [true], RUN)
{
  const q = 3 * (60 * SAMPLED.length + 1), c = Math.cos(Math.PI / 6), s = Math.sin(Math.PI / 6)
  assert.ok(near(f7.targets.slice(q, q + 3), [0, 1.30 + 0.1 * c + 0.1 * s, 0.1 * s - 0.1 * c], 1e-5), '[7] row 10')
}
add('sim', '[7] the same without the capsule (the case is real)', 'follow7', [false], RUN)

// [8] mismatch
add('sim', '[8] _STRAND_CARD 62 for 61 cards → StrandMismatch', 'mismatch8', ['card'])
add('sim', '[8] _STRAND_U one short → StrandMismatch', 'mismatch8', ['u'])

// [9]–[12] Ruling H-R10
const c9 = add('sim', '[9] length clamp: row 9 held 0.10 m out', 'clamp9', [], RUN)
assert.ok(near(c9.slice(27, 30), [0.5205922, 1.4358816, 0], 1e-6), '[9] ' + c9.slice(27, 30))
add('sim', '[10] head tether holds the leading run only', 'tether10', [], RUN)
const w11 = add('sim', '[11] damping relative to the target: 4 s at 3.4 m/s', 'walk11', [], RUN)
add('sim', '[12] the head has the last word over a capsule', 'lastWord12', [], RUN)

// [13] RootInertia
const tr = (x, y = 0, z = 0) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]
const ry = a => [Math.cos(a), 0, -Math.sin(a), 0, 0, 1, 0, 0, Math.sin(a), 0, Math.cos(a), 0, 0, 0, 0, 1]
add('sim', '[13a] 1 m/s from the first frame', 'inertia13', [Array.from({ length: 30 }, (_, st) => tr(st * DT)), DT], 1e-12)
add('sim', '[13b] at rest, then 1 m/s² for 1 s', 'inertia13', [Array.from({ length: 90 }, (_, st) => { const t = Math.max(0, st * DT - 1); return tr(0.5 * t * t) }), DT], 1e-12)
const c13 = add('sim', '[13c] a 1 m snap after rest', 'inertia13', [[...Array.from({ length: 10 }, () => tr(0)), tr(1), tr(1), tr(1)], DT], 1e-12)
assert.ok(near(c13[10], tr(0.99931461), 1e-9), '[13c]')
const d13 = add('sim', '[13d] a 90° yaw snap after rest', 'inertia13', [[...Array.from({ length: 10 }, () => tr(0)), ry(Math.PI / 2), ry(Math.PI / 2)], DT], 1e-12)
assert.ok(near(d13[10], ry(Math.PI / 2 - 0.000717738), 1e-9), '[13d]')
add('sim', '[13] a turn and a scaled root (rigid part only), dt 0 records', 'inertia13',
  [[tr(0), ryS(30, 1.3), ryS(31, 1.3), ryS(179.5, 1), ryS(180, 1)], DT], 1e-12)
add('sim', '[13e] carry(Ry 90°): rows and previous rows turned with it', 'carry13e', [ry(Math.PI / 2)], 1e-7)

// [14] gravity
assert.equal(add('sim', '[14] upright: hang == the targets, bit for bit', 'gravityOff14', [0], 0), 0, '[14] upright')
const g90 = add('sim', '[14] turned 90°: 4 s loose', 'gravity14', [90, 240, true], RUN)
assert.ok(near(g90.hang.slice(48, 51), [0.5, 1.28, 0], 1e-6), '[14] 90 ' + g90.hang.slice(48, 51))
assert.equal(add('sim', '[14] turned 10° (< 20°): hang == the targets, bit for bit', 'gravityOff14', [10], 0), 0, '[14] 10')
const g32 = add('sim', '[14] turned 32.5°: the share of gravity', 'gravity14', [32.5, 1, false], RUN)
assert.ok(Math.abs(Math.hypot(...[0, 1, 2].map(k => g32.hang[48 + k] - g32.targets[48 + k])) - 0.0625147) <= 1e-6, '[14] 32.5')

// the budget (spec § 6.2.2)
const cand = (name, distance, costMs, running = false) => ({ name, distance, costMs, running })
for (const [label, list] of [
  ['nearest first, at most 2', [cand('c', 3, 1), cand('a', 1, 1), cand('b', 2, 1)]],
  ['the nearest whatever its cost', [cand('a', 1, 20), cand('b', 2, 1)]],
  ['the budget ends the list (no farther cheaper one jumps)', [cand('a', 1, 5), cand('b', 2, 4), cand('c', 3, 0.5)]],
  ['beyond the cutoff', [cand('a', 8.5, 1), cand('b', 7.9, 1)]],
  ['a running one keeps its place up to 9 m', [cand('a', 8.5, 1, true), cand('b', 9.1, 1, true)]],
  ['ties by name', [cand('b', 2, 1), cand('a', 2, 1), cand('c', 2, 1)]],
  ['nobody', []]])
  add('sim', '[budget] pickStrandFigures: ' + label, 'pick', [list, null])
add('sim', '[budget] pickStrandFigures: custom limits', 'pick', [[cand('a', 1, 1), cand('b', 2, 1), cand('c', 3, 1)], { maxFigures: 3, cutoffM: 8, leaveM: 9, budgetMs: 2.5 }])

// ---- the clock (hairSim.ts through three) ---------------------------------------------------------------------
{
  const q = (axis, deg) => new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...axis).normalize(), deg * Math.PI / 180).toArray()
  const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
  const frames = []
  let t = 0
  const push = (dt, extra = {}) => {
    t += dt
    frames.push({ dt, root: rootMotion('sway', t, 1, [0, 1.3, 0]), head: q([1, 0, 0], 12 * Math.sin(2 * Math.PI * 0.7 * t)),
      spine: q([0, 0, 1], 6 * Math.sin(2 * Math.PI * 0.4 * t)), ...extra })
  }
  for (let i = 0; i < 30; i++) push(1 / 60)
  for (let i = 0; i < 20; i++) push(1 / 20)
  for (let i = 0; i < 5; i++) push(1 / 7)
  push(0.3)
  for (let i = 0; i < 14; i++) push(1 / 144)
  { const last = frames[frames.length - 1]; push(1 / 60); const f = frames[frames.length - 1]; f.root = [...f.root]; f.root[12] += 1; void last }
  for (let i = 0; i < 9; i++) { push(1 / 60, { frozen: true }); frames[frames.length - 1].root[12] += 1 }
  // a walk start at 3.4 m/s along +z from where the sway left the figure: the root inertia carries the snap
  const base = frames[frames.length - 1].root
  for (let i = 1; i <= 40; i++) {
    const m = [...base]; m[12] += 0; m[14] += 3.4 * i / 60
    frames.push({ dt: 1 / 60, root: m })
  }
  const spec = { build: { fan: 60, cards: [{ straight: [0, -0.10], pins: 2, side: [1, 0, 0] },
    { straight: [0, -0.095, 1.60, 0.03], pins: 2, side: [1, 0, 0] }], spine: true, torso: true },
    root0: I, frames, record: [1, 30, 50, 55, 56, 70, 71, 80, 81, 120], full: [120], mesh: [55, 120] }
  const got = add('clock', '[clock] 60 Hz with remainders, long frames, a stall, sub-step frames, a jump, frozen, a walk start',
    'strandClock', [spec], RUN)
  assert.deepEqual(got.capsuleIds, ['chest'], 'clock capsules')
  const at = k => got.frames.find(f => f.frame === k)
  // the frozen frames wrote nothing: X at 80 equals X at 71 (after the jump's reset)
  assert.ok(near(at(80).X, at(71).X, 0), 'clock frozen')
  const still = { ...spec, frames: frames.slice(0, 30).map(f => ({ ...f, root: I, head: [0, 0, 0, 1], spine: [0, 0, 0, 1] })), record: [30], mesh: [], restDev: true }
  const rest = add('clock', '[clock] at rest the rebuilt mesh is the bind mesh', 'strandClock', [still], 0)
  const fx = build(spec.build)
  assert.ok(rest.frames[0].restDev[0] === 0 && rest.frames[0].restDev[1] === 0, 'clock rest mesh ' + rest.frames[0].restDev)
  void fx
}

// ---- write / check -------------------------------------------------------------------------------------------------

const files = {
  strand_sim: { format: 'anima-test-vectors/1', source: 'scripts/export_strand_vectors.mjs', fixtures: {}, cases: cases.sim },
  strand_clock: { format: 'anima-test-vectors/1', source: 'scripts/export_strand_vectors.mjs', fixtures: {}, cases: cases.clock },
}
function format(v, pad = '') {
  if (Array.isArray(v)) {
    if (v.every(x => x === null || typeof x !== 'object')) return JSON.stringify(v).replaceAll(',', ', ')
    return '[\n' + v.map(x => pad + '  ' + format(x, pad + '  ')).join(',\n') + '\n' + pad + ']'
  }
  if (v && typeof v === 'object') {
    const keys = Object.keys(v)
    if (!keys.length) return '{}'
    return '{\n' + keys.map(k => pad + '  ' + JSON.stringify(k) + ': ' + format(v[k], pad + '  ')).join(',\n') + '\n' + pad + '}'
  }
  return JSON.stringify(v)
}
let failed = 0
for (const [name, data] of Object.entries(files)) {
  const path = root + 'shared/test-vectors/' + name + '.json'
  const text = format(data) + '\n'
  parseVectors(text)
  if (process.argv.includes('--check')) {
    const disk = await readFile(path, 'utf8')
    const r = runVectors(parseVectors(disk), dispatch, { log: () => {} })
    failed += r.failed
    if (r.failed) console.log('FAIL  ' + name + '.json: ' + r.failed + ' case(s) differ when replayed')
    if (disk !== text) { console.log('DRIFT ' + name + '.json differs from what the TypeScript gives now'); failed++ }
    else console.log('same  ' + name + '.json (' + data.cases.length + ' cases)')
  } else {
    await writeFile(path, text)
    console.log('wrote shared/test-vectors/' + name + '.json (' + data.cases.length + ' cases, ' + text.length + ' bytes)')
  }
}
process.exit(failed ? 1 : 0)
