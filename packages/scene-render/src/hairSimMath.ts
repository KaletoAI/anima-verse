/**
 * Per-strand hair dynamics, pure (no `three`): strand-hair spec
 * `docs/superpowers/specs/2026-11-13-strand-hair-design.md` § 6.2, a port of the HAAR spike's `sim.js`
 * round 3 (`ChainSim`, `PerStrand.skin`, `frameAt`, `boxDepth`, `sdfAt`, `measure`).
 *
 * The server computes everything geometric once per hair fit (the strand record, `app/core/hair_strands.py`,
 * `docs/schnittstellen-3d.md` "Hair strands"): per card 17 centreline rows root first, the pinned leading rows,
 * the free arc, the follow blend of every row, the head SDF, the face box, the capsules and the mode's
 * parameters. The served hair primitive carries `_STRAND_CARD` (card + 1, 0 = rigid) and `_STRAND_U` (place
 * along the 17 rows) per vertex; `bindStrands` turns them into rest frames and per-vertex offsets.
 *
 * FRAMES. Record positions are in the bind space of the served GLB. `StrandFrame.head` is world ← bind space
 * carried by the head bone (`Head_now · Head_bind⁻¹`); the SDF and the face box ride it rigidly. The
 * simulated points live in WORLD space; `strandTargets` puts every row where today's skin puts it
 * (`Σ_b w_b · (bone_b now · bone_b bind⁻¹) · p_bind`). `rebuild` writes the vertices in head-bind space (the
 * strand hair is skinned to the Head alone while it runs).
 *
 * ONE STEP (spec § 6.2.1 items 1–7, `ChainSim.step`):
 *   1. pinned rows = their target; free rows: Verlet in the target's frame (Ruling H-R10: the damping works on the
 *      velocity relative to the target's — still air moves with the figure, a constant walk drags nothing — and
 *      the pull is towards the previous step's target, the one of the row's own time) with a pendulum pull towards the
 *      target, `k = g / max(free_arc, 0.03)` × stiffness (a "fly" row — above the ear line, resting > 3 cm off
 *      the head — `g / max(free_arc, fly_arc)`);
 *   2. `iterations` Gauss-Seidel passes of distance (i−1, i) with stiffness 1 and (i−2, i) with the bend
 *      stiffness (gradient on: `kb(f) = bend + (1 − bend)·max(0, 1 − f/0.5)²`);
 *   3. gradient on (`root_deg` > 0): the angle limit, carried down the strand (`limitSegmentAngle`);
 *   4. the head SDF (clearance ≤ the row's own rest clearance), then the capsules under the bind rule
 *      (`tipBindFactors`, `pushOutOfCapsules`), then the face keep-out box — all in head-bind space; a row a
 *      capsule or the box pushed back into the head goes out of the head SDF once more, and a capsule or the box
 *      pushes a row no further than its length reaches from its parent (Ruling H-R10: a raised arm held rows 32 mm
 *      deep in Lirien's head, celebrating, and a first free row 6 cm off its pinned parent);
 *   5. the tether of the upper free third (and of the rows that rest on the head from the last pin on);
 *   6. the length clamp (Ruling H-R10): a free segment longer than `STRAND_STRETCH_MAX` × its target length is
 *      shortened towards its parent, root to tip — the collision and the tether run after the constraints, so
 *      without it a row pushed out (or held) alone stretched its card (Kira, sit: 1.43×; a held row in a swinging
 *      card's middle: 3.6×).
 * The ROOT'S MOTION (Ruling H-R10, `RootInertia`): the game turns a figure with a 10/s ease and starts / stops a walk
 * at once; the sim feels the root's motion only up to the spike's tuning motions (`STRAND_ROOT_LIMITS`), the rest
 * carries the simulated rows rigidly (`StrandSim.carry`).
 * The rest lengths and the angle limit's rest direction are those of the TARGET chain (the rest chain under a
 * rigid head, as in the spike; under a bent neck or a scaled figure the target's own), so a held pose is exactly
 * at rest: at rest every term is zero and the rebuilt mesh equals the rest mesh bit for bit.
 */
import type { CollisionCapsule, Mat4, Vec3 } from './collision'
import { linearScale } from './collision'
import { capsuleInFrame, COLLIDE_MAX, HAIR_REGIONS, pushOutOfCapsules } from './garmentCollision'
import type { CollideCapsule } from './garmentCollision'
import { tipBindFactors } from './secondaryMotion'

/** Simulated rows per card, root first (`hair_strands.ROWS`). */
export const STRAND_ROWS = 17
const R = STRAND_ROWS
const G = 9.81
/** Pendulum floor of an ordinary free row (m). */
const MIN_ARC = 0.03
/** A row is "fly" when it rests more than this off the head above the ear line (m). */
const FLY_CLEAR = 0.03
/** Collision clearance cap: a row keeps at most this off the head, never more than at rest (m). */
const CLEARANCE = 0.003
/** The SDF outside its grid (m). */
const SDF_OUTSIDE = 0.127
/** The length clamp (Ruling H-R10): no free segment ends longer than this × its target length. */
export const STRAND_STRETCH_MAX = 1.05
/**
 * The root motion the sim feels at most (Ruling H-R10, `RootInertia`): the envelope of the spike's tuning motions
 * (`sim.js` `rootMotion`, the motions the parameters were tuned on) — its walk `z 0.25·sin(πt)` peaks at
 * 0.25·π² = 2.47 m/s², its sway `yaw 15°·sin(πt)` at 0.2618·π² = 2.58 rad/s². The spike has no per-step clamp of
 * its own; the game turns a figure at up to 10·Δ rad/s (`easeNpcYaw`, 15.7 rad/s for a 90° corner), snaps it
 * (`faceTowards(…, snap)`) and starts a walk at 3.4 m/s in one frame.
 */
export const STRAND_ROOT_LIMITS = { accel: 0.25 * Math.PI * Math.PI, angAccel: (15 * Math.PI / 180) * Math.PI * Math.PI }

/** The strand record (spec § 6.2.3, `docs/schnittstellen-3d.md` "Hair strands"). */
/** The record version this simulation reads (`hair_strands.RECORD_VERSION`; 2: the head SDF ends at the chin, the
 *  neck cut away, Ruling H-R8). A record of another version is not used — the hair stays on its skin. */
export const STRAND_RECORD_VERSION = 2

export interface HairStrandRecord {
  version: number
  item_id: string
  fsig: string
  mode: 'hairdeck' | 'haar' | string
  fit_sha256: string
  frame: 'head_bind' | string
  head_bone: string
  rows: number
  cards: number
  rest: number[]
  pins: number[]
  free_arc: number[]
  free_frac: number[]
  follow: { bones: string[]; w: number[] }
  ear_y: number
  face_box: number[]
  eye_box: number[]
  landmarks?: string
  sdf: { dims: number[]; lo: number[]; vox: number; order: string; unit: string; data: string }
  capsules: { version: number; capsules: CollisionCapsule[]; scales?: Record<string, number> }
  params: Record<string, number | boolean>
  vertex_attributes: { card: string; u: string }
}

/** The record's `params`, camelCase (`strandParams`). */
export interface StrandParams {
  damping: number
  stiffness: number
  bend: number
  iterations: number
  rootDeg: number
  rootFrac: number
  flySoft: boolean
  flyArc: number
  tether: boolean
  tetherR0: number
  tetherR1: number
  tetherHead: number
  headClr: number
  faceBox: boolean
}

/** The record's snake_case `params` as `StrandParams`. */
export function strandParams(p: HairStrandRecord['params']): StrandParams {
  const num = (k: string) => Number(p[k])
  return {
    damping: num('damping'), stiffness: num('stiffness'), bend: num('bend'), iterations: num('iterations'),
    rootDeg: num('root_deg'), rootFrac: num('root_frac'), flySoft: !!p.fly_soft, flyArc: num('fly_arc'),
    tether: !!p.tether, tetherR0: num('tether_r0'), tetherR1: num('tether_r1'), tetherHead: num('tether_head'),
    headClr: num('head_clr'), faceBox: !!p.face_box,
  }
}

/** A record and a hair primitive that do not belong together — the hair stays on its skin, never scrambled. */
export class StrandMismatch extends Error {
  constructor(message: string) { super(message); this.name = 'StrandMismatch' }
}

// --- small math (column-major Mat4, as three's `Matrix4.elements`) ---------------------------------------------

/** The inverse of an affine column-major 4×4 (zeros for a singular one). */
export function invertAffine(m: Mat4): number[] {
  const a = m[0], b = m[4], c = m[8], d = m[1], e = m[5], f = m[9], g = m[2], h = m[6], i = m[10]
  const A = e * i - f * h, B = f * g - d * i, C = d * h - e * g
  const det = a * A + b * B + c * C
  if (!det) return new Array<number>(16).fill(0)
  const s = 1 / det
  const r = [A * s, B * s, C * s, 0, (c * h - b * i) * s, (a * i - c * g) * s, (b * g - a * h) * s, 0,
    (b * f - c * e) * s, (c * d - a * f) * s, (a * e - b * d) * s, 0, 0, 0, 0, 1]
  const tx = m[12], ty = m[13], tz = m[14]
  r[12] = -(r[0] * tx + r[4] * ty + r[8] * tz)
  r[13] = -(r[1] * tx + r[5] * ty + r[9] * tz)
  r[14] = -(r[2] * tx + r[6] * ty + r[10] * tz)
  return r
}

/** Parallel-transport frames along one centreline `C[base .. base + 17·3)` (tangents = forward segments),
 *  from the root normal `n0`: per row 9 numbers (tangent, normal, binormal) into `out`. */
function frameAt(C: ArrayLike<number>, base: number, out: Float64Array, n0x: number, n0y: number, n0z: number): void {
  let nx = n0x, ny = n0y, nz = n0z
  for (let i = 0; i < R; i++) {
    const a = base + 3 * Math.min(i, R - 2), b = a + 3
    let tx = C[b] - C[a], ty = C[b + 1] - C[a + 1], tz = C[b + 2] - C[a + 2]
    let l = Math.hypot(tx, ty, tz) || 1e-9
    tx /= l; ty /= l; tz /= l
    const d = nx * tx + ny * ty + nz * tz
    nx -= d * tx; ny -= d * ty; nz -= d * tz
    l = Math.hypot(nx, ny, nz)
    if (l < 1e-9) {     // tangent parallel to the carried normal: any perpendicular
      if (Math.abs(tx) < 0.9) { nx = 0; ny = -tz; nz = ty } else { nx = tz; ny = 0; nz = -tx }
      l = Math.hypot(nx, ny, nz)
    }
    nx /= l; ny /= l; nz /= l
    const o = 9 * i
    out[o] = tx; out[o + 1] = ty; out[o + 2] = tz
    out[o + 3] = nx; out[o + 4] = ny; out[o + 5] = nz
    out[o + 6] = ty * nz - tz * ny; out[o + 7] = tz * nx - tx * nz; out[o + 8] = tx * ny - ty * nx
  }
}

/** A box `[x0, x1, y0, y1, z0]` open to the front: `[depth, exit]` of a point inside (exit 0 = −x, 1 = +x,
 *  2 = +y, the nearest), `[0, −1]` outside. */
export function boxDepth(b: ArrayLike<number>, x: number, y: number, z: number): [number, number] {
  if (x <= b[0] || x >= b[1] || y <= b[2] || y >= b[3] || z <= b[4]) return [0, -1]
  let d = x - b[0], e = 0
  if (b[1] - x < d) { d = b[1] - x; e = 1 }
  if (b[3] - y < d) { d = b[3] - y; e = 2 }
  return [d, e]
}

const inBox = (b: ArrayLike<number>, x: number, y: number, z: number) =>
  x > b[0] && x < b[1] && y > b[2] && y < b[3] && z > b[4]

/** Distance of `p` to the segment a–b. */
function segDist(p: Vec3, a: Vec3, b: Vec3): number {
  const abx = b[0] - a[0], aby = b[1] - a[1], abz = b[2] - a[2]
  const apx = p[0] - a[0], apy = p[1] - a[1], apz = p[2] - a[2]
  const l2 = abx * abx + aby * aby + abz * abz
  const t = l2 > 1e-12 ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / l2)) : 0
  return Math.hypot(apx - abx * t, apy - aby * t, apz - abz * t)
}

// --- the head SDF -------------------------------------------------------------------------------------------------

/** The record's head SDF, decoded: int8 millimetres, x fastest. */
export interface StrandSdf { q: Int8Array; dims: [number, number, number]; lo: Vec3; vox: number }

/** Decode the record's `sdf` (base64 int8 mm, x fastest). */
export function decodeStrandSdf(sdf: HairStrandRecord['sdf']): StrandSdf {
  const bin = atob(sdf.data)
  const q = new Int8Array(bin.length)
  for (let i = 0; i < bin.length; i++) q[i] = (bin.charCodeAt(i) << 24) >> 24
  const [nx, ny, nz] = sdf.dims
  if (q.length !== nx * ny * nz) throw new StrandMismatch(`SDF holds ${q.length} values for ${nx}×${ny}×${nz}`)
  return { q, dims: [nx, ny, nz], lo: [sdf.lo[0], sdf.lo[1], sdf.lo[2]], vox: sdf.vox }
}

/** Trilinear SDF in metres at a head-bind-space point (+0.127 outside the grid); writes the (unnormalised)
 *  gradient into `g` when given. */
export function strandSdfAt(s: StrandSdf, x: number, y: number, z: number, g?: Float32Array | number[]): number {
  const [nx, ny, nz] = s.dims, v = s.vox
  const fx = (x - s.lo[0]) / v, fy = (y - s.lo[1]) / v, fz = (z - s.lo[2]) / v
  if (fx < 0 || fy < 0 || fz < 0 || fx > nx - 1.001 || fy > ny - 1.001 || fz > nz - 1.001) {
    if (g) { g[0] = 0; g[1] = 0; g[2] = 0 }
    return SDF_OUTSIDE
  }
  const ix = fx | 0, iy = fy | 0, iz = fz | 0, ux = fx - ix, uy = fy - iy, uz = fz - iz
  const q = s.q, sy = nx, sz = nx * ny, o = ix + nx * (iy + ny * iz)
  const c000 = q[o], c100 = q[o + 1], c010 = q[o + sy], c110 = q[o + 1 + sy]
  const c001 = q[o + sz], c101 = q[o + 1 + sz], c011 = q[o + sy + sz], c111 = q[o + 1 + sy + sz]
  const c00 = c000 + (c100 - c000) * ux, c10 = c010 + (c110 - c010) * ux
  const c01 = c001 + (c101 - c001) * ux, c11 = c011 + (c111 - c011) * ux
  const c0 = c00 + (c10 - c00) * uy, c1 = c01 + (c11 - c01) * uy
  if (g) {
    g[0] = (c100 - c000) * (1 - uy) * (1 - uz) + (c110 - c010) * uy * (1 - uz) + (c101 - c001) * (1 - uy) * uz
      + (c111 - c011) * uy * uz
    g[1] = (c10 - c00) * (1 - uz) + (c11 - c01) * uz
    g[2] = c1 - c0
  }
  return (c0 + (c1 - c0) * uz) * 0.001
}

// --- the rest binding ---------------------------------------------------------------------------------------------

/** The rest frames of every card and the per-vertex offsets (`bindStrands`). */
export interface StrandBinding {
  /** Cards. */
  S: number
  /** The rest centrelines (bind space), float32 — the precision the simulated points have. */
  C0: Float32Array
  /** Per card the root normal of its parallel-transport frames. */
  N00: Float64Array
  /** Per vertex: card (−1 rigid), lower row and the weight of the row above. */
  vk: Int32Array
  va: Uint8Array
  vt: Float64Array
  /** Per vertex and row (a, a+1): the offset of position / normal in that row's frame. */
  off: Float64Array
  noff: Float64Array
  /** The vertices of each card (CSR). */
  cStart: Int32Array
  cVerts: Int32Array
  /** The vertices on no card (a scalp cap). */
  rigid: Int32Array
  pos0: Float32Array
  nrm0: Float32Array
}

/**
 * Bind a hair primitive (`pos0` / `nrm0` its bind positions and normals, `card` / `u` its `_STRAND_CARD` /
 * `_STRAND_U`) to the record: rest frames + per-vertex offsets in them. Throws `StrandMismatch` when the
 * attribute lengths differ, a card number exceeds `record.cards`, or the record's arrays do not fit its card
 * count.
 */
export function bindStrands(record: HairStrandRecord, pos0: Float32Array, nrm0: Float32Array, card: Uint16Array,
  u: Float32Array): StrandBinding {
  const nv = card.length, S = record.cards
  if (pos0.length !== 3 * nv || nrm0.length !== 3 * nv || u.length !== nv) {
    throw new StrandMismatch(`attribute lengths differ: ${pos0.length / 3} positions, ${nrm0.length / 3} normals, `
      + `${nv} cards, ${u.length} u`)
  }
  if (!(S > 0) || record.rows !== R || record.rest.length !== S * R * 3 || record.pins.length !== S
    || record.free_arc.length !== S * R || record.free_frac.length !== S * R
    || record.follow.w.length !== S * R * record.follow.bones.length) {
    throw new StrandMismatch(`the record's arrays do not fit ${S} cards of ${R} rows`)
  }
  let maxCard = 0
  for (let v = 0; v < nv; v++) if (card[v] > maxCard) maxCard = card[v]
  if (maxCard - 1 >= S) throw new StrandMismatch(`_STRAND_CARD ${maxCard} names card ${maxCard - 1}; the record has ${S} cards`)
  const C0 = Float32Array.from(record.rest)
  const vk = new Int32Array(nv), va = new Uint8Array(nv), vt = new Float64Array(nv)
  for (let v = 0; v < nv; v++) {
    const k = card[v] - 1
    vk[v] = k
    if (k < 0) continue
    const uu = Math.min(R - 1, Math.max(0, u[v]))
    const ia = Math.min(R - 2, Math.floor(uu))
    va[v] = ia
    const t = Math.min(1, Math.max(0, uu - ia))
    vt[v] = t < 1e-6 ? 0 : t
  }
  const cStart = new Int32Array(S + 1), cVerts = new Int32Array(nv)
  for (let v = 0; v < nv; v++) if (vk[v] >= 0) cStart[vk[v] + 1]++
  for (let k = 0; k < S; k++) cStart[k + 1] += cStart[k]
  const fill = cStart.slice(0, S)
  const rigid: number[] = []
  for (let v = 0; v < nv; v++) {
    if (vk[v] >= 0) cVerts[fill[vk[v]]++] = v
    else rigid.push(v)
  }
  const N00 = new Float64Array(S * 3), frames = new Float64Array(R * 9)
  const off = new Float64Array(nv * 6), noff = new Float64Array(nv * 6)
  for (let k = 0; k < S; k++) {
    const b = k * R * 3
    const tx = C0[b + 3] - C0[b], tz = C0[b + 5] - C0[b + 2]
    let nx = -tz, nz = tx
    let l = Math.hypot(nx, nz)
    if (l < 1e-6) { nx = 1; nz = 0; l = 1 }      // initial normal: horizontal, perpendicular to the root tangent
    N00[3 * k] = nx / l; N00[3 * k + 1] = 0; N00[3 * k + 2] = nz / l
    frameAt(C0, b, frames, N00[3 * k], N00[3 * k + 1], N00[3 * k + 2])
    for (let q = cStart[k]; q < cStart[k + 1]; q++) {
      const v = cVerts[q]
      for (let h = 0; h < 2; h++) {
        if (h && !vt[v]) break
        const i = va[v] + h, c = b + 3 * i, f = 9 * i, o = 6 * v + 3 * h
        const dx = pos0[3 * v] - C0[c], dy = pos0[3 * v + 1] - C0[c + 1], dz = pos0[3 * v + 2] - C0[c + 2]
        for (let a = 0; a < 3; a++) {
          off[o + a] = dx * frames[f + 3 * a] + dy * frames[f + 3 * a + 1] + dz * frames[f + 3 * a + 2]
          noff[o + a] = nrm0[3 * v] * frames[f + 3 * a] + nrm0[3 * v + 1] * frames[f + 3 * a + 1]
            + nrm0[3 * v + 2] * frames[f + 3 * a + 2]
        }
      }
    }
  }
  return { S, C0, N00, vk, va, vt, off, noff, cStart, cVerts, rigid: Int32Array.from(rigid),
    pos0: Float32Array.from(pos0), nrm0: Float32Array.from(nrm0) }
}

// --- the animated targets -----------------------------------------------------------------------------------------

const TARGET_DATA = new WeakMap<HairStrandRecord, { rest: Float64Array; w: Float64Array }>()

/**
 * The animated target of every row into `out` (cards·17·3, world): `Σ_b w_b · follow[b] · p_bind` with
 * `follow[b] = bone_b now · bone_b bind⁻¹` (world ← bind) for `record.follow.bones[b]`.
 */
export function strandTargets(record: HairStrandRecord, follow: readonly Mat4[], out: Float32Array): void {
  let data = TARGET_DATA.get(record)
  if (!data) {
    data = { rest: Float64Array.from(record.rest), w: Float64Array.from(record.follow.w) }
    TARGET_DATA.set(record, data)
  }
  const { rest, w } = data
  const nb = record.follow.bones.length, n = rest.length / 3
  if (follow.length !== nb) throw new StrandMismatch(`${follow.length} follow matrices for ${nb} bones`)
  for (let p = 0; p < n; p++) {
    const x = rest[3 * p], y = rest[3 * p + 1], z = rest[3 * p + 2]
    let tx = 0, ty = 0, tz = 0
    for (let b = 0; b < nb; b++) {
      const wb = w[p * nb + b]
      if (!wb) continue
      const m = follow[b]
      tx += wb * (m[0] * x + m[4] * y + m[8] * z + m[12])
      ty += wb * (m[1] * x + m[5] * y + m[9] * z + m[13])
      tz += wb * (m[2] * x + m[6] * y + m[10] * z + m[14])
    }
    out[3 * p] = tx; out[3 * p + 1] = ty; out[3 * p + 2] = tz
  }
}

// --- the angle limit ----------------------------------------------------------------------------------------------

const LIM = new Float64Array(3)

/** The angle limit of one segment into `LIM`: false when `cur` is within the limit (or degenerate). */
function limitInto(px: number, py: number, pz: number, cx: number, cy: number, cz: number,
  rx: number, ry: number, rz: number, cosLim: number): boolean {
  const rl = Math.hypot(rx, ry, rz) || 1e-9
  rx /= rl; ry /= rl; rz /= rl
  let dx = cx - px, dy = cy - py, dz = cz - pz
  const L = Math.hypot(dx, dy, dz)
  if (L < 1e-9) return false
  dx /= L; dy /= L; dz /= L
  const cs = dx * rx + dy * ry + dz * rz
  if (cs >= cosLim) return false
  let qx = dx - cs * rx, qy = dy - cs * ry, qz = dz - cs * rz
  const ql = Math.hypot(qx, qy, qz)
  if (ql < 1e-9) { qx = 0; qy = 0; qz = 0 } else { qx /= ql; qy /= ql; qz /= ql }
  const sl = Math.sqrt(Math.max(0, 1 - cosLim * cosLim))
  LIM[0] = px + L * (rx * cosLim + qx * sl)
  LIM[1] = py + L * (ry * cosLim + qy * sl)
  LIM[2] = pz + L * (rz * cosLim + qz * sl)
  return true
}

/** `cur` turned about `prev` towards `restDir` until the angle between `cur − prev` and `restDir` is at most
 *  `acos(cosLim)`, keeping the segment's length; `cur` itself when it is within. */
export function limitSegmentAngle(prev: Vec3, cur: Vec3, restDir: Vec3, cosLim: number): Vec3 {
  return limitInto(prev[0], prev[1], prev[2], cur[0], cur[1], cur[2], restDir[0], restDir[1], restDir[2], cosLim)
    ? [LIM[0], LIM[1], LIM[2]] : [cur[0], cur[1], cur[2]]
}

// --- the simulation -----------------------------------------------------------------------------------------------

/** One frame of the figure: the rows' targets (`strandTargets`, world), the head (world ← head-bind space) and
 *  the body capsules now (world; `capsuleNow` of `strandCapsules`, with `bind` = their bind-space ends as
 *  `bindCollision` gives them — the bind rule's reference). Keep each capsule's `bind` object the same from frame
 *  to frame: the per-row bind-rule factors are cached on it. */
export interface StrandFrame { targets: Float32Array; head: Mat4; capsules: readonly CollideCapsule[] }

/** The record's capsules the hair collides with (`HAIR_REGIONS`, at most `COLLIDE_MAX`), in record order — what
 *  `StrandFrame.capsules` carries now. */
export function strandCapsules(record: HairStrandRecord): CollisionCapsule[] {
  return (record.capsules?.capsules ?? []).filter(c => HAIR_REGIONS.includes(c.region)).slice(0, COLLIDE_MAX)
}

export class StrandSim {
  readonly binding: StrandBinding
  /** Rows (cards · 17). */
  readonly n: number
  /** The simulated rows (world) and their previous positions. */
  readonly X: Float32Array
  readonly Xp: Float32Array
  readonly pin: Uint8Array
  /** Free-arc fraction (0 at the last pin, 1 at the tip). */
  readonly f: Float32Array
  /** The head SDF and every row's rest value in it (m). */
  readonly sdf: StrandSdf
  readonly sdf0: Float32Array
  readonly faceBox: number[]
  private readonly k: Float32Array
  private readonly arcFree: Float32Array
  private readonly clr: Float32Array
  private readonly fly: Uint8Array
  private readonly onHead: Float32Array
  private readonly boxD0: Float32Array
  private readonly L1: Float32Array
  private readonly L2: Float32Array
  private readonly cosLim: Float32Array
  private readonly kb2: Float32Array
  private readonly kFly: Float32Array
  private limKey = ''
  private flyKey = NaN
  private readonly g = new Float32Array(3)
  private capKey: readonly unknown[] = []
  private capFactors = new Float32Array(0)
  private readonly frames = new Float64Array(R * 9)
  /** The targets of the previous step (carried with the rows). Ruling H-R10: the step is Verlet in the TARGET's
   *  frame — the damping works on a row's velocity relative to its target's (damped in world, a figure walking at
   *  3.4 m/s felt 0.04 × 3.4 m/s per 1/60 s = 8.2 m/s² of drag, a gale that blew every card horizontal), and the
   *  pull at step n is towards the target of step n (towards the next one, a row led its target by v·dt; with
   *  the angle limit pinning the root segment, the card then settled 10 cm BEHIND at 3.4 m/s). At rest Tp = T. */
  private readonly Tp: Float32Array
  private tpOk = false
  private readonly Cl: Float64Array

  constructor(binding: StrandBinding, record: HairStrandRecord) {
    const S = binding.S, n = S * R
    if (record.cards !== S) throw new StrandMismatch(`binding of ${S} cards for a record of ${record.cards}`)
    this.binding = binding
    this.n = n
    this.X = new Float32Array(3 * n); this.Xp = new Float32Array(3 * n); this.Tp = new Float32Array(3 * n)
    this.pin = new Uint8Array(n); this.f = Float32Array.from(record.free_frac)
    this.arcFree = Float32Array.from(record.free_arc)
    this.k = new Float32Array(n); this.clr = new Float32Array(n); this.fly = new Uint8Array(n)
    this.onHead = new Float32Array(n); this.boxD0 = new Float32Array(n); this.sdf0 = new Float32Array(n)
    this.L1 = new Float32Array(n); this.L2 = new Float32Array(n)
    this.cosLim = new Float32Array(n); this.kb2 = new Float32Array(n); this.kFly = new Float32Array(n)
    this.Cl = new Float64Array(3 * n)
    this.sdf = decodeStrandSdf(record.sdf)
    this.faceBox = record.face_box.slice(0, 5)
    const C0 = binding.C0, ear = record.ear_y
    for (let c = 0; c < S; c++) {
      const pins = Math.max(1, record.pins[c])
      for (let i = 0; i < R; i++) {
        const p = c * R + i, x = C0[3 * p], y = C0[3 * p + 1], z = C0[3 * p + 2]
        const pinned = i < pins
        this.pin[p] = pinned ? 1 : 0
        this.k[p] = G / Math.max(this.arcFree[p], MIN_ARC)
        const dr = strandSdfAt(this.sdf, x, y, z)
        this.sdf0[p] = dr
        this.clr[p] = Math.min(CLEARANCE, dr)
        this.fly[p] = !pinned && y > ear && dr > FLY_CLEAR ? 1 : 0
        this.onHead[p] = !pinned && y > ear ? Math.max(dr, 1e-4) : 0
        this.boxD0[p] = boxDepth(this.faceBox, x, y, z)[0]
      }
    }
    this.X.set(C0); this.Xp.set(C0)
  }

  /** Every row at its target, at rest. */
  reset(targets: Float32Array): void {
    this.X.set(targets.subarray(0, 3 * this.n)); this.Xp.set(targets.subarray(0, 3 * this.n))
    this.Tp.set(targets.subarray(0, 3 * this.n)); this.tpOk = true
  }

  /** Carry every simulated row and its previous position by the affine `m` (world → world): the rows move with
   *  it rigidly and keep their velocity relative to it (`RootInertia`). */
  carry(m: Mat4): void {
    for (const A of [this.X, this.Xp, this.Tp]) {
      for (let o = 0; o < A.length; o += 3) {
        const x = A[o], y = A[o + 1], z = A[o + 2]
        A[o] = m[0] * x + m[4] * y + m[8] * z + m[12]
        A[o + 1] = m[1] * x + m[5] * y + m[9] * z + m[13]
        A[o + 2] = m[2] * x + m[6] * y + m[10] * z + m[14]
      }
    }
  }

  step(dt: number, frame: StrandFrame, p: StrandParams): void {
    const { X, Xp, Tp, pin, k, L1, L2, n } = this, T = frame.targets
    if (!this.tpOk) { Tp.set(T.subarray(0, 3 * n)); this.tpOk = true }
    const damp = p.damping, dt2 = dt * dt, ks = p.stiffness, kb = p.bend, flySoft = p.flySoft
    if (flySoft && this.flyKey !== p.flyArc) {
      this.flyKey = p.flyArc
      for (let q = 0; q < n; q++) this.kFly[q] = G / Math.max(this.arcFree[q], p.flyArc)
    }
    // 1. pinned rows follow, free rows swing towards their target
    for (let q = 0; q < n; q++) {
      const o = 3 * q
      if (pin[q]) { X[o] = Xp[o] = T[o]; X[o + 1] = Xp[o + 1] = T[o + 1]; X[o + 2] = Xp[o + 2] = T[o + 2]; continue }
      const kk = (flySoft && this.fly[q] ? this.kFly[q] : k[q]) * ks * dt2
      for (let d = 0; d < 3; d++) {
        const xo = X[o + d], vr = T[o + d] - Tp[o + d]
        const nx = xo + (xo - Xp[o + d] - vr) * (1 - damp) + vr - kk * (xo - Tp[o + d])
        Xp[o + d] = xo; X[o + d] = nx
      }
    }
    // the rest lengths of the target chain
    for (let q = 0; q < n; q++) {
      const i = q % R, o = 3 * q
      L1[q] = i > 0 ? Math.hypot(T[o] - T[o - 3], T[o + 1] - T[o - 2], T[o + 2] - T[o - 1]) : 0
      L2[q] = i > 1 ? Math.hypot(T[o] - T[o - 6], T[o + 1] - T[o - 5], T[o + 2] - T[o - 4]) : 0
    }
    const grad = p.rootDeg > 0
    if (grad) this.limits(p)
    // 2. length and bend constraints
    for (let it = 0; it < p.iterations; it++) {
      for (let c = 0; c < n; c += R) {
        for (let i = 1; i < R; i++) {
          this.dist(c + i - 1, c + i, L1[c + i], 1)
          if (i > 1) {
            const s = grad && !(flySoft && this.fly[c + i]) ? this.kb2[c + i] : kb
            if (s > 0) this.dist(c + i - 2, c + i, L2[c + i], s)
          }
        }
      }
    }
    // 3. the angle limit
    if (grad) this.angleLimit(T, flySoft)
    // 4. head SDF, capsules, face box (head-bind space)
    this.collide(frame, p)
    // 5. the tether
    if (p.tether) this.tether(T, p, linearScale(frame.head))
    // 6. the length clamp
    this.clampLengths()
    Tp.set(T.subarray(0, 3 * n))
  }

  /** Ruling H-R10: root to tip, a free row whose segment to its parent is longer than `STRAND_STRETCH_MAX` × the
   *  target length is moved towards the parent onto that length (shortened only; follow-the-leader), then out of
   *  the colliders again (`pushRow`, whose capsule and face-box pushes reach no further than the length allows); a
   *  push that lengthened it again is followed by one more shortening and two head-SDF steps (the head keeps the
   *  last word, the capsules and the face box yield to the length). */
  private clampLengths(): void {
    const { X, pin, L1, n } = this
    for (let c = 0; c < n; c += R) {
      for (let i = 1; i < R; i++) {
        const q = c + i
        if (pin[q]) continue
        const o = 3 * q, b = o - 3, L = L1[q] * STRAND_STRETCH_MAX
        const dx = X[o] - X[b], dy = X[o + 1] - X[b + 1], dz = X[o + 2] - X[b + 2], l = Math.hypot(dx, dy, dz)
        if (l <= L) continue
        const s = L / l
        X[o] = X[b] + dx * s; X[o + 1] = X[b + 1] + dy * s; X[o + 2] = X[b + 2] + dz * s
        this.pushRow(q)
        // a push that threw the row far off again (a tip the head ran 5 cm deep into in one frame, out through the
        // nearest surface: Lirien celebrating 1.30×; a face-box push along its exit axis: 1.28×): once more onto
        // the length, then out of the head SDF alone — the length wins over the capsules and the face box here,
        // the segment may cut a capsule by its chord's sagitta
        const ex = X[o] - X[b], ey = X[o + 1] - X[b + 1], ez = X[o + 2] - X[b + 2], m = Math.hypot(ex, ey, ez)
        if (m <= L) continue
        const t = L / m
        X[o] = X[b] + ex * t; X[o + 1] = X[b + 1] + ey * t; X[o + 2] = X[b + 2] + ez * t
        this.pushRow(q, false, 2)
      }
    }
  }

  /** The simulated rows in head-bind space (`headInv` = bind ← world) into `Cl`, then every vertex of the hair
   *  primitive into `pos` / `nrm` (head-bind space; the rigid ones at rest). */
  rebuild(headInv: Mat4, pos: Float32Array, nrm: Float32Array): void {
    const H = this.binding, X = this.X, Cl = this.Cl, F = this.frames, off = H.off, noff = H.noff
    const m = headInv
    for (let q = 0; q < X.length; q += 3) {
      const x = X[q], y = X[q + 1], z = X[q + 2]
      Cl[q] = m[0] * x + m[4] * y + m[8] * z + m[12]
      Cl[q + 1] = m[1] * x + m[5] * y + m[9] * z + m[13]
      Cl[q + 2] = m[2] * x + m[6] * y + m[10] * z + m[14]
    }
    for (const v of H.rigid) {
      for (let d = 0; d < 3; d++) { pos[3 * v + d] = H.pos0[3 * v + d]; nrm[3 * v + d] = H.nrm0[3 * v + d] }
    }
    for (let c = 0; c < H.S; c++) {
      const b = c * R * 3
      frameAt(Cl, b, F, H.N00[3 * c], H.N00[3 * c + 1], H.N00[3 * c + 2])
      for (let q = H.cStart[c]; q < H.cStart[c + 1]; q++) {
        const v = H.cVerts[q], i = H.va[v], t = H.vt[v], cc = b + 3 * i, f = 9 * i, o = 6 * v
        for (let d = 0; d < 3; d++) {
          let pv = Cl[cc + d] + off[o] * F[f + d] + off[o + 1] * F[f + 3 + d] + off[o + 2] * F[f + 6 + d]
          let nv = noff[o] * F[f + d] + noff[o + 1] * F[f + 3 + d] + noff[o + 2] * F[f + 6 + d]
          if (t) {
            const c2 = cc + 3, f2 = f + 9, o2 = o + 3
            const p2 = Cl[c2 + d] + off[o2] * F[f2 + d] + off[o2 + 1] * F[f2 + 3 + d] + off[o2 + 2] * F[f2 + 6 + d]
            const n2 = noff[o2] * F[f2 + d] + noff[o2 + 1] * F[f2 + 3 + d] + noff[o2 + 2] * F[f2 + 6 + d]
            pv += t * (p2 - pv); nv += t * (n2 - nv)
          }
          pos[3 * v + d] = pv; nrm[3 * v + d] = nv
        }
      }
    }
  }

  /** Bend stiffness gradient and per-row cosine of the angle limit (cached per parameter set). */
  private limits(p: StrandParams): void {
    const key = `${p.rootDeg}:${p.rootFrac}:${p.bend}`
    if (key === this.limKey) return
    this.limKey = key
    for (let q = 0; q < this.n; q++) {
      const f = this.f[q]
      const a = f <= p.rootFrac ? p.rootDeg : p.rootDeg + (180 - p.rootDeg) * (f - p.rootFrac) / (1 - p.rootFrac)
      this.cosLim[q] = Math.cos(Math.min(180, a) * Math.PI / 180)
      const r = Math.max(0, 1 - f / 0.5)
      this.kb2[q] = p.bend + (1 - p.bend) * r * r
    }
  }

  private dist(a: number, b: number, L: number, stiff: number): void {
    const X = this.X, wa = this.pin[a] ? 0 : 1, wb = this.pin[b] ? 0 : 1, w = wa + wb
    if (!w) return
    const oa = 3 * a, ob = 3 * b
    const dx = X[ob] - X[oa], dy = X[ob + 1] - X[oa + 1], dz = X[ob + 2] - X[oa + 2]
    const l = Math.hypot(dx, dy, dz)
    if (l < 1e-9) return
    const s = stiff * (l - L) / (l * w)
    X[oa] += wa * s * dx; X[oa + 1] += wa * s * dy; X[oa + 2] += wa * s * dz
    X[ob] -= wb * s * dx; X[ob + 1] -= wb * s * dy; X[ob + 2] -= wb * s * dz
  }

  /** The angle of each free segment against its target segment, at most `acos(cosLim)`; the shift is carried
   *  down the strand (the lower segments keep their lengths). */
  private angleLimit(T: Float32Array, flySoft: boolean): void {
    const { X, pin, cosLim, n } = this
    for (let c = 0; c < n; c += R) {
      let sx = 0, sy = 0, sz = 0
      for (let i = 1; i < R; i++) {
        const q = c + i, o = 3 * q, b = o - 3
        if (pin[q]) continue
        X[o] += sx; X[o + 1] += sy; X[o + 2] += sz
        if (cosLim[q] <= -0.999 || (flySoft && this.fly[q])) continue
        if (!limitInto(X[b], X[b + 1], X[b + 2], X[o], X[o + 1], X[o + 2],
          T[o] - T[b], T[o + 1] - T[b + 1], T[o + 2] - T[b + 2], cosLim[q])) continue
        sx += LIM[0] - X[o]; sy += LIM[1] - X[o + 1]; sz += LIM[2] - X[o + 2]
        X[o] = LIM[0]; X[o + 1] = LIM[1]; X[o + 2] = LIM[2]
      }
    }
  }

  /** Per row and capsule the bind-rule factor (`tipBindFactors`), recomputed when the capsules' bind ends
   *  change. */
  private factors(caps: readonly CollideCapsule[], local: readonly { r: number }[]): Float32Array {
    const key = caps.map(c => c.bind)
    if (key.length === this.capKey.length && key.every((b, i) => b === this.capKey[i])) return this.capFactors
    const nc = caps.length, C0 = this.binding.C0, out = new Float32Array(this.n * nc).fill(1)
    const bound = caps.map((c, i) => (c.bind ? { a: c.bind.a, b: c.bind.b, r: local[i].r } : null))
    const withBind = bound.filter((c): c is { a: Vec3; b: Vec3; r: number } => c !== null)
    const slot = bound.map((c, i) => (c ? i : -1)).filter(i => i >= 0)
    if (withBind.length) {
      for (let q = 0; q < this.n; q++) {
        const fq = tipBindFactors([C0[3 * q], C0[3 * q + 1], C0[3 * q + 2]], withBind)
        for (let j = 0; j < slot.length; j++) out[q * nc + slot[j]] = fq[j]
      }
    }
    this.capKey = key
    this.capFactors = out
    return out
  }

  /** The colliders of this step in head-bind space (`collide` sets them, `pushRow` and the length clamp use them). */
  private col: { m: Mat4; inv: number[]; local: CollideCapsule[]; fac: Float32Array; scratch: CollideCapsule[];
    box: boolean } | null = null

  /** The head SDF, the capsules and the face keep-out box, in head-bind space; each push goes back to world
   *  through the head's linear part (a row nothing pushes is left untouched, bit for bit). */
  private collide(frame: StrandFrame, p: StrandParams): void {
    const { pin, n } = this, m = frame.head, inv = invertAffine(m)
    const caps = frame.capsules ?? []
    const local = caps.map(c => capsuleInFrame(c, inv))
    const fac = caps.length ? this.factors(caps, local) : this.capFactors
    const scratch: CollideCapsule[] = local.map(c => ({ a: c.a, b: c.b, r: c.r }))
    this.col = { m, inv, local, fac, scratch, box: p.faceBox }
    for (let q = 0; q < n; q++) if (!pin[q]) this.pushRow(q)
  }

  /** One free row out of the head SDF, the capsules (bind rule) and the face box (`collide`'s colliders). Ruling
   *  H-R10: a capsule or the face box pushes a row no further out than its length lets it be from its parent (the
   *  row before it, already pushed) — a parent inside a raised arm or deep in the face box left the first free row
   *  6 cm off it (Lirien celebrating: 1.27× its card); the head SDF pushes in full, `sdfSteps` gradient steps.
   *  `body` false: the head SDF alone. */
  private pushRow(q: number, body = true, sdfSteps = 1): void {
    const col = this.col
    if (!col) return
    const { X, clr, g, sdf, L1 } = this, { m, inv, local, fac, scratch } = col
    const nc = local.length, fb = this.faceBox, d0 = this.boxD0
    const toLocal = (o: number): Vec3 => {
      const wx = X[o], wy = X[o + 1], wz = X[o + 2]
      return [inv[0] * wx + inv[4] * wy + inv[8] * wz + inv[12], inv[1] * wx + inv[5] * wy + inv[9] * wz + inv[13],
        inv[2] * wx + inv[6] * wy + inv[10] * wz + inv[14]]
    }
    const o = 3 * q
    const [lx, ly, lz] = toLocal(o)
    const par = toLocal(o - 3), reach = L1[q] * STRAND_STRETCH_MAX
    let x = lx, y = ly, z = lz
    // the head SDF: a row keeps its own rest clearance (at most 3 mm)
    const sdfPush = (): void => {
      const s = strandSdfAt(sdf, x, y, z, g)
      if (s >= clr[q]) return
      const gl = Math.hypot(g[0], g[1], g[2])
      if (gl < 1e-9) return
      const f = (clr[q] - s) / gl
      x += g[0] * f; y += g[1] * f; z += g[2] * f
    }
    for (let k = 0; k < sdfSteps; k++) sdfPush()
    const hx = x, hy = y, hz = z
    // the capsules, each radius capped at the row's bind distance to it
    if (nc && body) {
      let inside = false
      const here: Vec3 = [x, y, z]
      for (let c = 0; c < nc; c++) {
        const r = local[c].r * fac[q * nc + c]
        if (segDist(here, local[c].a, local[c].b) < r) {
          inside = true
          scratch[c].r = Math.min(r, segDist(par, local[c].a, local[c].b) + reach)
        } else scratch[c].r = r
      }
      if (inside) {
        const pushed = pushOutOfCapsules(here, scratch, 1)
        x = pushed[0]; y = pushed[1]; z = pushed[2]
      }
    }
    // the face keep-out box: out by −x, +x or +y, as deep as at rest at most
    if (col.box && body) {
      const [d, e] = boxDepth(fb, x, y, z)
      const allowed = e >= 0 && d > d0[q] ? Math.max(d0[q], boxDepth(fb, par[0], par[1], par[2])[0] - reach) : d0[q]
      if (e >= 0 && d > allowed) {
        const mm = d - allowed
        if (e === 0) x -= mm; else if (e === 1) x += mm; else y += mm
      }
    }
    // Ruling H-R10: the head has the last word — a capsule (a raised arm) or the face box that pushed the row
    // back into the head (a row caught between arm and head) does not leave it there
    if (x !== hx || y !== hy || z !== hz) sdfPush()
    if (x === lx && y === ly && z === lz) return
    const dx = x - lx, dy = y - ly, dz = z - lz
    X[o] += m[0] * dx + m[4] * dy + m[8] * dz
    X[o + 1] += m[1] * dx + m[5] * dy + m[9] * dz
    X[o + 2] += m[2] * dx + m[6] * dy + m[10] * dz
  }

  /** A row at free fraction `f ≤ 1/3` stays within `r(f) = r0 + (r1 − r0)·3f` of its target; a row resting on
   *  the head (above the ear line, rest clearance < `headClr`) within `tetherHead` — only in the run of such rows
   *  from the last pin on (Ruling H-R10: a row resting on the head again after free rows, a card looping back onto
   *  the scalp, held alone pinned the middle of a swinging card). Radii × the head's scale. */
  private tether(T: Float32Array, p: StrandParams, scale: number): void {
    const { X, pin, f, onHead, n } = this, r0 = p.tetherR0, r1 = p.tetherR1
    for (let c = 0; c < n; c += R) {
      let run = p.tetherHead > 0
      for (let i = 1; i < R; i++) {
        const q = c + i
        if (pin[q]) continue
        run = run && onHead[q] > 0 && onHead[q] < p.headClr
        if (p.flySoft && this.fly[q]) continue
        const upper = f[q] <= 1 / 3, head = run
        if (!upper && !head) continue
        const o = 3 * q, tx = T[o], ty = T[o + 1], tz = T[o + 2]
        const dx = X[o] - tx, dy = X[o + 1] - ty, dz = X[o + 2] - tz, d = Math.hypot(dx, dy, dz)
        const r = Math.min(upper ? r0 + (r1 - r0) * 3 * f[q] : Infinity, head ? p.tetherHead : Infinity) * scale
        if (d <= r) continue
        const s = r / d
        X[o] = tx + dx * s; X[o + 1] = ty + dy * s; X[o + 2] = tz + dz * s
      }
    }
  }
}

// --- the root's motion (Ruling H-R10) ----------------------------------------------------------------------------

/** The rigid part of an affine column-major matrix (its rotation columns normalised, its translation). */
function rigidOf(m: Mat4): number[] {
  const out = new Array<number>(16).fill(0)
  for (let c = 0; c < 3; c++) {
    const l = Math.hypot(m[4 * c], m[4 * c + 1], m[4 * c + 2]) || 1
    out[4 * c] = m[4 * c] / l; out[4 * c + 1] = m[4 * c + 1] / l; out[4 * c + 2] = m[4 * c + 2] / l
  }
  out[12] = m[12]; out[13] = m[13]; out[14] = m[14]; out[15] = 1
  return out
}

/** `a · b`, column-major 4×4. */
function mul(a: ArrayLike<number>, b: ArrayLike<number>): number[] {
  const out = new Array<number>(16)
  for (let c = 0; c < 4; c++) {
    for (let r = 0; r < 4; r++) {
      out[4 * c + r] = a[r] * b[4 * c] + a[4 + r] * b[4 * c + 1] + a[8 + r] * b[4 * c + 2] + a[12 + r] * b[4 * c + 3]
    }
  }
  return out
}

/** The rotation vector (axis × angle, rad) of a rotation matrix's 3×3 (column-major). */
function rotationVector(m: ArrayLike<number>): Vec3 {
  const tr = m[0] + m[5] + m[10]
  const angle = Math.acos(Math.max(-1, Math.min(1, (tr - 1) / 2)))
  if (angle < 1e-9) return [0, 0, 0]
  let x = m[6] - m[9], y = m[8] - m[2], z = m[1] - m[4]
  const l = Math.hypot(x, y, z)
  if (l < 1e-6) {      // about 180°: the axis from the diagonal, signs from the largest component
    x = Math.sqrt(Math.max(0, (m[0] + 1) / 2)); y = Math.sqrt(Math.max(0, (m[5] + 1) / 2))
    z = Math.sqrt(Math.max(0, (m[10] + 1) / 2))
    if (x >= y && x >= z) { y = Math.sign(m[1] + m[4]) * y || y; z = Math.sign(m[2] + m[8]) * z || z } else if (y >= z) {
      x = Math.sign(m[1] + m[4]) * x || x; z = Math.sign(m[6] + m[9]) * z || z
    } else { x = Math.sign(m[2] + m[8]) * x || x; y = Math.sign(m[6] + m[9]) * y || y }
    const k = Math.hypot(x, y, z) || 1
    return [x / k * angle, y / k * angle, z / k * angle]
  }
  return [x / l * angle, y / l * angle, z / l * angle]
}

/** The rigid motion of a rotation vector `w` (rad) and a translation `t` (column-major; Rodrigues). */
function rigidFrom(w: Vec3, t: Vec3): number[] {
  const a = Math.hypot(w[0], w[1], w[2])
  const out = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, t[0], t[1], t[2], 1]
  if (a < 1e-12) return out
  const x = w[0] / a, y = w[1] / a, z = w[2] / a, c = Math.cos(a), s = Math.sin(a), k = 1 - c
  out[0] = c + x * x * k; out[1] = y * x * k + z * s; out[2] = z * x * k - y * s
  out[4] = x * y * k - z * s; out[5] = c + y * y * k; out[6] = z * y * k + x * s
  out[8] = x * z * k + y * s; out[9] = y * z * k - x * s; out[10] = c + z * z * k
  return out
}

/** The inverse of a rigid column-major matrix. */
function rigidInverse(m: ArrayLike<number>): number[] {
  const out = [m[0], m[4], m[8], 0, m[1], m[5], m[9], 0, m[2], m[6], m[10], 0, 0, 0, 0, 1]
  out[12] = -(out[0] * m[12] + out[4] * m[13] + out[8] * m[14])
  out[13] = -(out[1] * m[12] + out[5] * m[13] + out[9] * m[14])
  out[14] = -(out[2] * m[12] + out[6] * m[13] + out[10] * m[14])
  return out
}

const clampTowards = (cur: Vec3, want: Vec3, max: number): Vec3 => {
  const dx = want[0] - cur[0], dy = want[1] - cur[1], dz = want[2] - cur[2], l = Math.hypot(dx, dy, dz)
  const s = l > max ? max / l : 1
  return [cur[0] + dx * s, cur[1] + dy * s, cur[2] + dz * s]
}

/**
 * How much of the figure root's motion the strands feel (Ruling H-R10), pure. The sim lives in a world that follows
 * the root's motion with bounded accelerations: per frame the root's rigid move (in its own frame of the last frame:
 * rotation vector and translation, i.e. its velocities) is tracked by a FELT velocity that changes by at most
 * `limits.accel` · dt (linear) and `limits.angAccel` · dt (angular); the root moves by the felt part in the sim's
 * world, and `update` returns the rest as the world → world carry of this frame (`StrandSim.carry`):
 * `root_now · felt⁻¹ · root_prev⁻¹`. A motion within the limits is felt whole (the carry is the identity); a snap
 * or a 90° turn at the game's 10/s ease is carried nearly whole, so the rows turn with the body instead of flying
 * out. Scale in the root matrix is ignored (its rigid part).
 */
export class RootInertia {
  private prev: number[] | null = null
  private v: Vec3 = [0, 0, 0]
  private w: Vec3 = [0, 0, 0]
  private fresh = true
  constructor(readonly limits: { accel: number; angAccel: number } = STRAND_ROOT_LIMITS) {}

  /** Forget the root (the sim was reset): the next frame only records it, the one after starts the felt linear
   *  velocity at the root's own, the angular at rest. */
  reset(): void { this.prev = null; this.fresh = true; this.v = [0, 0, 0]; this.w = [0, 0, 0] }

  /** The carry of this frame (world → world) for the root's world matrix `root` after `dt` seconds; null for the
   *  identity (the first frame, or `dt` ≤ 0). */
  update(root: Mat4, dt: number): number[] | null {
    const now = rigidOf(root)
    const prev = this.prev
    this.prev = now
    if (!prev || !(dt > 0)) return null
    const local = mul(rigidInverse(prev), now)
    const rv = rotationVector(local)
    const vReal: Vec3 = [local[12] / dt, local[13] / dt, local[14] / dt]
    const wReal: Vec3 = [rv[0] / dt, rv[1] / dt, rv[2] / dt]
    if (this.fresh) {
      this.fresh = false
      this.v = vReal
    } else {
      this.v = clampTowards(this.v, vReal, this.limits.accel * dt)
    }
    this.w = clampTowards(this.w, wReal, this.limits.angAccel * dt)
    const felt = rigidFrom([this.w[0] * dt, this.w[1] * dt, this.w[2] * dt], [this.v[0] * dt, this.v[1] * dt, this.v[2] * dt])
    return mul(mul(now, rigidInverse(felt)), rigidInverse(prev))
  }
}

// --- metrics (the spike's `measure` and scalp exposure) ----------------------------------------------------------

/** Per row: 1 where its REST position lies inside `box` (`[x0, x1, y0, y1, z0]`, open to the front). */
export function restInsideBox(sim: StrandSim, box: ArrayLike<number>): Uint8Array {
  const C0 = sim.binding.C0, out = new Uint8Array(sim.n)
  for (let q = 0; q < sim.n; q++) out[q] = inBox(box, C0[3 * q], C0[3 * q + 1], C0[3 * q + 2]) ? 1 : 0
  return out
}

/** Rows inside the eye box now (head-bind space, `head` = world ← head-bind) that were not inside at rest. */
export function eyePointsEntered(sim: StrandSim, head: Mat4, eyeBox: ArrayLike<number>, restInside: Uint8Array): number {
  const inv = invertAffine(head), X = sim.X
  let count = 0
  for (let q = 0; q < sim.n; q++) {
    if (restInside[q]) continue
    const x = X[3 * q], y = X[3 * q + 1], z = X[3 * q + 2]
    if (inBox(eyeBox, inv[0] * x + inv[4] * y + inv[8] * z + inv[12], inv[1] * x + inv[5] * y + inv[9] * z + inv[13],
      inv[2] * x + inv[6] * y + inv[10] * z + inv[14])) count++
  }
  return count
}

/** The deepest a free row now lies inside the head SDF BEYOND its own rest depth (mm; the spike's `deepMm`:
 *  `max(0, min(0, sdf(rest)) − sdf(now))`). */
export function maxSdfDepthMm(sim: StrandSim, head: Mat4, sdf: StrandSdf): number {
  const inv = invertAffine(head), X = sim.X, C0 = sim.binding.C0
  let deep = 0
  for (let q = 0; q < sim.n; q++) {
    if (sim.pin[q]) continue
    const x = X[3 * q], y = X[3 * q + 1], z = X[3 * q + 2]
    const now = strandSdfAt(sdf, inv[0] * x + inv[4] * y + inv[8] * z + inv[12],
      inv[1] * x + inv[5] * y + inv[9] * z + inv[13], inv[2] * x + inv[6] * y + inv[10] * z + inv[14])
    const rest = strandSdfAt(sdf, C0[3 * q], C0[3 * q + 1], C0[3 * q + 2])
    deep = Math.max(deep, Math.min(0, rest) - now)
  }
  return deep * 1000
}

/** The scalp-exposure cameras' vertical field of view (the spike's `mcam`, aspect 1). */
export const SCALP_CAMERA_FOV_DEG = 30

/**
 * The spike's head-fixed scalp cameras: per yaw, eye = target + (sin a · dist, lift, cos a · dist) looking at
 * `target` with +y up — camera → space matrices (three's `camera.matrixWorld`; the camera looks down −z).
 */
export function scalpCameras(target: Vec3, yawsDeg: readonly number[] = [180, 135, 225], dist = 0.85,
  lift = 0.05): number[][] {
  return yawsDeg.map(deg => {
    const a = deg * Math.PI / 180
    const eye: Vec3 = [target[0] + Math.sin(a) * dist, target[1] + lift, target[2] + Math.cos(a) * dist]
    let zx = eye[0] - target[0], zy = eye[1] - target[1], zz = eye[2] - target[2]
    const zl = Math.hypot(zx, zy, zz); zx /= zl; zy /= zl; zz /= zl
    let xx = zz, xz = -zx                                // up (0,1,0) × z
    const xl = Math.hypot(xx, xz); xx /= xl; xz /= xl
    const yx = zy * xz, yy = zz * xx - zx * xz, yz = -zy * xx   // z × x
    return [xx, 0, xz, 0, yx, yy, yz, 0, zx, zy, zz, 0, eye[0], eye[1], eye[2], 1]
  })
}

/** Rasterise triangles (9 numbers each) into the depth buffer `depth` (1/w, larger = nearer) and `id`. */
function raster(tris: Float32Array, view: number[], size: number, depth: Float32Array, id: Uint8Array,
  label: number): void {
  const f = 1 / Math.tan(SCALP_CAMERA_FOV_DEG * Math.PI / 360), near = 0.01, h = size / 2
  const sx = [0, 0, 0], sy = [0, 0, 0], iw = [0, 0, 0]
  for (let t = 0; t + 8 < tris.length; t += 9) {
    let behind = false
    for (let k = 0; k < 3; k++) {
      const x = tris[t + 3 * k], y = tris[t + 3 * k + 1], z = tris[t + 3 * k + 2]
      const vx = view[0] * x + view[4] * y + view[8] * z + view[12]
      const vy = view[1] * x + view[5] * y + view[9] * z + view[13]
      const vz = view[2] * x + view[6] * y + view[10] * z + view[14]
      if (-vz < near) { behind = true; break }
      const w = 1 / -vz
      iw[k] = w; sx[k] = h + h * f * vx * w; sy[k] = h - h * f * vy * w
    }
    if (behind) continue
    const area = (sx[1] - sx[0]) * (sy[2] - sy[0]) - (sx[2] - sx[0]) * (sy[1] - sy[0])
    if (Math.abs(area) < 1e-12) continue
    const x0 = Math.max(0, Math.floor(Math.min(sx[0], sx[1], sx[2]))), x1 = Math.min(size - 1, Math.ceil(Math.max(sx[0], sx[1], sx[2])))
    const y0 = Math.max(0, Math.floor(Math.min(sy[0], sy[1], sy[2]))), y1 = Math.min(size - 1, Math.ceil(Math.max(sy[0], sy[1], sy[2])))
    for (let py = y0; py <= y1; py++) {
      const cy = py + 0.5
      for (let px = x0; px <= x1; px++) {
        const cx = px + 0.5
        const b0 = ((sx[1] - cx) * (sy[2] - cy) - (sx[2] - cx) * (sy[1] - cy)) / area
        const b1 = ((sx[2] - cx) * (sy[0] - cy) - (sx[0] - cx) * (sy[2] - cy)) / area
        const b2 = 1 - b0 - b1
        if (b0 < 0 || b1 < 0 || b2 < 0) continue
        const w = b0 * iw[0] + b1 * iw[1] + b2 * iw[2], i = py * size + px
        if (w > depth[i]) { depth[i] = w; id[i] = label }
      }
    }
  }
}

/**
 * Share of the scalp each camera sees (CPU z-buffer, `size`², the cards opaque): per camera (`cams`, camera →
 * space as `scalpCameras`), the scalp pixels visible with the occluding triangles `tris` drawn / the scalp
 * pixels without them. `scalp` and `tris` are triangle soups (9 numbers each) in the cameras' space.
 */
export function scalpExposure(tris: Float32Array, scalp: Float32Array, cams: readonly Mat4[], size = 256): number[] {
  const depth = new Float32Array(size * size), id = new Uint8Array(size * size)
  return cams.map(cam => {
    const view = invertAffine(cam)
    depth.fill(0); id.fill(0)
    raster(scalp, view, size, depth, id, 1)
    let total = 0
    for (let i = 0; i < id.length; i++) total += id[i]
    raster(tris, view, size, depth, id, 2)
    let seen = 0
    for (let i = 0; i < id.length; i++) if (id[i] === 1) seen++
    return total ? seen / total : 0
  })
}

// --- the figure budget (spec § 6.2.2) ----------------------------------------------------------------------------

/** Who runs per strand: at most `maxFigures`, within `cutoffM` of the camera (a running one leaves only beyond
 *  `leaveM`), admitted while the measured cost sum stays ≤ `budgetMs` (spec § 6.2.2). */
export const STRAND_LIMITS = { maxFigures: 2, cutoffM: 8, leaveM: 9, budgetMs: 8 } as const
export type StrandLimits = { maxFigures: number; cutoffM: number; leaveM: number; budgetMs: number }

/** One full-tier figure with a strand record: its camera distance (m), its sim + rebuild cost per frame (ms, the
 *  EMA of `StrandHair.costMs`) and whether it runs per strand now. */
export interface StrandCandidate { name: string; distance: number; costMs: number; running: boolean }

/**
 * The figures that run per strand this frame (spec § 6.2.2), pure: nearest first (ties by name); a candidate is in
 * range within `leaveM` when it is running, else within `cutoffM`. The nearest in range is always admitted, whatever
 * its cost; the next only while the cost sum stays ≤ `budgetMs` and the count ≤ `maxFigures`; the first that does
 * not fit ends the list (no farther, cheaper figure jumps it).
 */
export function pickStrandFigures(c: readonly StrandCandidate[], limits: StrandLimits = STRAND_LIMITS): Set<string> {
  const inRange = c.filter(x => x.distance <= (x.running ? limits.leaveM : limits.cutoffM))
    .sort((a, b) => a.distance - b.distance || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
  const out = new Set<string>()
  let sum = 0
  for (const x of inRange) {
    if (out.size && (out.size + 1 > limits.maxFigures || sum + x.costMs > limits.budgetMs)) break
    out.add(x.name)
    sum += x.costMs
  }
  return out
}
