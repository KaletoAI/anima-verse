/**
 * THE OPENING of a declared channel (Ruling A102): while an attached part of another figure — or the admin viewer's
 * test rod — occupies a channel, the receiving body's surface around the channel opens to the occupant's radius,
 * as a stretched, rounded lip (never a cut). The channel's frame is `channels.ts`'s (`channelCoords`); this module
 * adds the one rule that moves the receiving mesh, and a three binding that applies it to skinned meshes.
 *
 * - THE OCCUPANT is a list of segments a → b with radius r (world metres; a chain's links, the rod's links).
 * - THE RADIAL MAP (`openedDistance`). d = the distance of a vertex P from the axis of its NEAREST segment (nearest by
 *   surface, d − r; Q the closest point on a → b). T = r + m (m = `margin`, default `OPENING_MARGIN_M`), the band
 *   B = max(`band` (default `OPENING_BAND_M`), 0.6·r), the band's outer end b = T + B and its inner end
 *   d0 = max(0, T − B), L = b − d0. Then f(d) = T for d ≤ d0 (the inner wall ends EXACTLY at T), f(d) = d for d ≥ b,
 *   and between them the cubic Hermite with f(d0) = T, f'(d0) = 0, f(b) = b, f'(b) = 1: with t = (d − d0)/L,
 *   f = T(2t³ − 3t² + 1) + b(−2t³ + 3t²) + L(t³ − t²). The secant slope B/L is ½ (T ≥ B) or B/(T + B) ≥ ½ (T < B), within
 *   the Fritsch–Carlson bound for end slopes 0 and 1, so f is MONOTONE and C1: no vertex passes another, no fold, no
 *   step at the rim.
 * - THE AXIAL WEIGHT `openingWeight`: z = 1 for −F ≤ s ≤ D (the channel's funnel and cylinder along its axis),
 *   1 − smoothstep(e / f) for a distance e before −F or past D, f = `falloff` (default `OPENING_FALLOFF_M`), 0 from
 *   e ≥ f on. Across the axis the radial map alone bounds the opening (a hard radial zone edge is what made a rod
 *   wider than the channel tear the rim). The displacement is z · (f(d) − d) along (P − Q)/d (on the axis itself:
 *   radially from the channel axis, else a fixed perpendicular of u).
 * - THE CANDIDATES (`openingCandidates`): the vertices with −F − f ≤ s ≤ D + f and ρ ≤ R + f + `slack` (default
 *   `OPENING_SLACK_M`) in the pose they were bound in — ONCE per channel. Per frame the binding narrows them to the
 *   occupant's reach (bind-time s, ρ against the segments' extent + the largest b + `OPENING_POSE_SLACK_M`).
 * - THE THREE BINDING (`bindChannelOpening`): the displacement acts on the SKINNED world positions (after the pose)
 *   and is written back into the bind-space `position` attribute through the inverse of each vertex's blended skin
 *   matrix, so the GPU skinning lands it exactly. The normals of the candidates are recomputed from their triangles
 *   (bind space; the GPU skins them). It owns a clone of each touched geometry (a figure shares its buffers with its
 *   template); `restore()` puts the original geometry back, `dispose()` frees the clone.
 *
 * A push of at most 1 µm counts as none (float noise).
 *
 * `three` is injected, never imported; the rule itself is pure.
 */
import type { BufferAttribute, BufferGeometry, Object3D, SkinnedMesh } from 'three'
import { channelCoords } from './channels'
import type { ChannelNow } from './channels'
import type { Vec3 } from './collision'
import { inGarment } from './figure'

type Three = typeof import('three')

/** m: the skin margin between the occupant's surface and the opened wall (metres). */
export const OPENING_MARGIN_M = 0.002
/** f: the band before the opening and past the bottom over which the opening fades along the axis (metres). */
export const OPENING_FALLOFF_M = 0.02
/** The radial band's floor (metres); B = max(this, 0.6·r). */
export const OPENING_BAND_M = 0.015
/** How far across the axis beyond R + f a vertex may be and still be a candidate (metres) — a wide occupant's lip. */
export const OPENING_SLACK_M = 0.06
/** The pose drift allowed between bind-time and current channel coordinates in the per-frame narrowing (metres). */
export const OPENING_POSE_SLACK_M = 0.01

/** One segment of the occupant: the axis a → b and its radius r (world). */
export interface OpeningSegment { a: Vec3; b: Vec3; r: number }
export interface OpeningOptions { margin?: number; falloff?: number; band?: number }

/** A102b: an opening is recomputed only when its inputs moved more than this (metres) … */
export const OPENING_SKIP_M = 0.001
/** … or turned more than this (degrees) since the last apply (`ChannelOpeningBinding.changed`). */
export const OPENING_SKIP_DEG = 0.5

/** A push at or below this (metres) does not move the point. */
const OPENING_EPS_M = 1e-6

/** The band B of a segment of radius r: max(`band`, 0.6·r). */
export function openingBand(r: number, band = OPENING_BAND_M): number {
  return Math.max(band, 0.6 * r)
}

/** f(d): where a vertex at distance d from the occupant's axis ends (module docstring, THE RADIAL MAP). */
export function openedDistance(d: number, r: number, options: OpeningOptions = {}): number {
  const T = r + (options.margin ?? OPENING_MARGIN_M)
  const B = openingBand(r, options.band)
  const b = T + B
  if (d >= b) return d
  const d0 = Math.max(0, T - B)
  if (d <= d0) return T
  const L = b - d0
  const t = (d - d0) / L, t2 = t * t, t3 = t2 * t
  return T * (2 * t3 - 3 * t2 + 1) + b * (-2 * t3 + 3 * t2) + L * (t3 - t2)
}

/** z: 1 for −F ≤ s ≤ D, 1 − smoothstep(e / f) for e = the distance before −F or past D, 0 from e ≥ f. */
export function openingWeight(s: number, ch: ChannelNow, falloff = OPENING_FALLOFF_M): number {
  const e = s > ch.depth ? s - ch.depth : s < -ch.funnel ? -ch.funnel - s : 0
  if (e <= 0) return 1
  if (!(falloff > 0) || e >= falloff) return 0
  const t = e / falloff
  return 1 - t * t * (3 - 2 * t)
}

/** The indices of the flat `[x, y, z, …]` points with −F − f ≤ s ≤ D + f and ρ ≤ R + f + slack. */
export function openingCandidates(positions: ArrayLike<number>, ch: ChannelNow, falloff = OPENING_FALLOFF_M,
  slack = OPENING_SLACK_M): number[] {
  const out: number[] = []
  for (let i = 0, n = Math.floor(positions.length / 3); i < n; i++) {
    const { s, rho } = channelCoords([positions[3 * i], positions[3 * i + 1], positions[3 * i + 2]], ch)
    if (s >= -ch.funnel - falloff && s <= ch.depth + falloff && rho <= ch.r + falloff + slack) out.push(i)
  }
  return out
}

/** The displacement of one point P (world), or null when it stays: module docstring, RADIAL MAP × AXIAL WEIGHT. */
export function openingDisplacement(p: Vec3, ch: ChannelNow, segments: readonly OpeningSegment[],
  options: OpeningOptions = {}): Vec3 | null {
  if (!segments.length) return null
  const { s } = channelCoords(p, ch)
  const z = openingWeight(s, ch, options.falloff ?? OPENING_FALLOFF_M)
  if (!(z > 0)) return null
  let best = Infinity, q: Vec3 = p, r = 0
  for (const seg of segments) {
    const ab: Vec3 = [seg.b[0] - seg.a[0], seg.b[1] - seg.a[1], seg.b[2] - seg.a[2]]
    const l2 = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2]
    const t = l2 > 0 ? Math.max(0, Math.min(1, ((p[0] - seg.a[0]) * ab[0] + (p[1] - seg.a[1]) * ab[1]
      + (p[2] - seg.a[2]) * ab[2]) / l2)) : 0
    const c: Vec3 = [seg.a[0] + ab[0] * t, seg.a[1] + ab[1] * t, seg.a[2] + ab[2] * t]
    const d = Math.hypot(p[0] - c[0], p[1] - c[1], p[2] - c[2])
    // The nearest segment by its SURFACE (d − r), so a thick link wins over a thin one at equal axis distance.
    if (d - seg.r < best) { best = d - seg.r; q = c; r = seg.r }
  }
  let dir: Vec3 = [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
  const d = Math.hypot(dir[0], dir[1], dir[2])
  const push = z * (openedDistance(d, r, options) - d)
  if (!(push > OPENING_EPS_M)) return null
  if (d > 1e-9) dir = [dir[0] / d, dir[1] / d, dir[2] / d]
  else {
    // On the occupant's axis: radially away from the channel axis, else a fixed perpendicular of u.
    const rel: Vec3 = [p[0] - ch.o[0] - ch.u[0] * s, p[1] - ch.o[1] - ch.u[1] * s, p[2] - ch.o[2] - ch.u[2] * s]
    const n = Math.hypot(rel[0], rel[1], rel[2])
    if (n > 1e-9) dir = [rel[0] / n, rel[1] / n, rel[2] / n]
    else {
      const ref: Vec3 = Math.abs(ch.u[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0]
      const c: Vec3 = [ch.u[1] * ref[2] - ch.u[2] * ref[1], ch.u[2] * ref[0] - ch.u[0] * ref[2], ch.u[0] * ref[1] - ch.u[1] * ref[0]]
      const cn = Math.hypot(c[0], c[1], c[2])
      dir = [c[0] / cn, c[1] / cn, c[2] / cn]
    }
  }
  return [dir[0] * push, dir[1] * push, dir[2] * push]
}

/**
 * The displacements of the `candidates` of flat world `positions` into `out` (3 per candidate, candidate order; 0 for
 * a point that stays). Returns the largest displacement length and how many points moved.
 */
export function channelOpening(positions: ArrayLike<number>, candidates: readonly number[], ch: ChannelNow,
  segments: readonly OpeningSegment[], out: Float32Array | number[], options: OpeningOptions = {}): { maxPush: number; moved: number } {
  let maxPush = 0, moved = 0
  candidates.forEach((i, k) => {
    const d = openingDisplacement([positions[3 * i], positions[3 * i + 1], positions[3 * i + 2]], ch, segments, options)
    out[3 * k] = d ? d[0] : 0; out[3 * k + 1] = d ? d[1] : 0; out[3 * k + 2] = d ? d[2] : 0
    if (d) { moved++; maxPush = Math.max(maxPush, Math.hypot(d[0], d[1], d[2])) }
  })
  return { maxPush, moved }
}

/**
 * The per-frame narrowing (`bindChannelOpening`): may a candidate at bind-time channel coordinates (s, ρ) move under
 * `segments`? Only when s lies within the segments' axial extent ± (largest b + `poseSlack`) and ρ ≤ the segments'
 * largest ρ + largest b + `poseSlack` (b = T + B of a segment, beyond which nothing moves).
 */
export function openingReach(segments: readonly OpeningSegment[], ch: ChannelNow, options: OpeningOptions = {},
  poseSlack = OPENING_POSE_SLACK_M): { sMin: number; sMax: number; rhoMax: number } {
  let sMin = Infinity, sMax = -Infinity, rhoSeg = 0, reach = 0
  for (const seg of segments) {
    for (const p of [seg.a, seg.b]) {
      const { s, rho } = channelCoords(p, ch)
      sMin = Math.min(sMin, s); sMax = Math.max(sMax, s); rhoSeg = Math.max(rhoSeg, rho)
    }
    reach = Math.max(reach, seg.r + (options.margin ?? OPENING_MARGIN_M) + openingBand(seg.r, options.band))
  }
  return { sMin: sMin - reach - poseSlack, sMax: sMax + reach + poseSlack, rhoMax: rhoSeg + reach + poseSlack }
}

/**
 * `openingDisplacement` without allocation (the binding's per-vertex path): the displacement of (px, py, pz) into
 * `out`, returning its length (0 = stays).
 */
export function displaceInto(px: number, py: number, pz: number, ch: ChannelNow, segments: readonly OpeningSegment[],
  options: OpeningOptions, out: Float64Array): number {
  const rx = px - ch.o[0], ry = py - ch.o[1], rz = pz - ch.o[2]
  const s = rx * ch.u[0] + ry * ch.u[1] + rz * ch.u[2]
  const z = openingWeight(s, ch, options.falloff ?? OPENING_FALLOFF_M)
  if (!(z > 0)) return 0
  let best = Infinity, qx = 0, qy = 0, qz = 0, r = 0
  for (const seg of segments) {
    const ax = seg.a[0], ay = seg.a[1], az = seg.a[2]
    const abx = seg.b[0] - ax, aby = seg.b[1] - ay, abz = seg.b[2] - az
    const l2 = abx * abx + aby * aby + abz * abz
    let t = l2 > 0 ? ((px - ax) * abx + (py - ay) * aby + (pz - az) * abz) / l2 : 0
    t = t < 0 ? 0 : t > 1 ? 1 : t
    const cx = ax + abx * t, cy = ay + aby * t, cz = az + abz * t
    const d = Math.hypot(px - cx, py - cy, pz - cz)
    if (d - seg.r < best) { best = d - seg.r; qx = cx; qy = cy; qz = cz; r = seg.r }
  }
  const dx = px - qx, dy = py - qy, dz = pz - qz
  const d = Math.hypot(dx, dy, dz)
  const push = z * (openedDistance(d, r, options) - d)
  if (!(push > OPENING_EPS_M)) return 0
  if (d > 1e-9) { out[0] = dx / d * push; out[1] = dy / d * push; out[2] = dz / d * push; return push }
  const full = openingDisplacement([px, py, pz], ch, segments, options)
  if (!full) return 0
  out[0] = full[0]; out[1] = full[1]; out[2] = full[2]
  return push
}

/** The candidates' skin indices / weights as typed arrays, and the bones they use. */
function skinOf(mesh: SkinnedMesh, idx: readonly number[]): { skinI: Uint16Array; skinW: Float32Array; usedBones: number[] } {
  const si = mesh.geometry.attributes.skinIndex, sw = mesh.geometry.attributes.skinWeight
  const skinI = new Uint16Array(idx.length * 4), skinW = new Float32Array(idx.length * 4)
  const used = new Set<number>()
  idx.forEach((i, k) => {
    for (let j = 0; j < 4; j++) {
      const w = sw ? sw.getComponent(i, j) : 0
      const b = si ? si.getComponent(i, j) : 0
      skinI[4 * k + j] = b; skinW[4 * k + j] = w
      if (w > 0) used.add(b)
    }
  })
  return { skinI, skinW, usedBones: [...used] }
}

// --- three binding ------------------------------------------------------------------------------------------------

export interface ChannelOpeningBinding {
  /** The channel id the candidates were taken for. */
  readonly channel: string
  /** How many vertices the binding may visit per frame. */
  readonly candidates: number
  /** Open the surface for `ch` (this frame's) and `segments` (world): every candidate first back to its rest, then
   *  displaced and its normal recomputed; no segments = `restore()`. Call after the pose is final. `visited`: the
   *  candidates the per-frame narrowing kept. */
  apply(ch: ChannelNow, segments: readonly OpeningSegment[], options?: OpeningOptions): { maxPush: number; moved: number;
    visited: number }
  /** Has anything the last `apply` read moved beyond the tolerance since (A102b)? True before the first apply, after
   *  `restore()`, when the segment count changed, when a segment end moved more than `tolM` or its radius more than
   *  `tolM`, when the channel's opening moved more than `tolM` or its axis turned more than `tolDeg`, or when a bone the
   *  candidates are skinned to moved more than `tolM` or turned more than `tolDeg` (world). False = the last result
   *  still holds; the caller may skip the apply. */
  changed(ch: ChannelNow, segments: readonly OpeningSegment[], tolM?: number, tolDeg?: number): boolean
  /** Every candidate back to its rest and the original geometry back on its mesh (exactly as before). */
  restore(): void
  /** `restore()` and free the cloned geometries. */
  dispose(): void
}

interface MeshEntry {
  mesh: SkinnedMesh
  original: BufferGeometry
  clone: BufferGeometry | null
  idx: number[]
  /** Bind-time channel coordinates of each candidate (the per-frame narrowing). */
  sBind: Float32Array
  rhoBind: Float32Array
  rest: Float32Array
  restNormal: Float32Array | null
  /** The triangles (vertex index triples) touching a candidate, and the candidate slot of a vertex (−1 none). */
  tris: Uint32Array
  slot: Int32Array
  /** Candidates sharing one rest position (a seam's split vertices) share a group: their normals are accumulated
   *  together, so a seam shades as one surface. */
  group: Int32Array
  groups: number
  /** This frame: the candidate moved (1), was moved last frame and is back at rest (2), else 0. */
  moved: Uint8Array
  /** The candidates' skin indices and weights (4 each), the bones they use, and scratch space. */
  skinI: Uint16Array
  skinW: Float32Array
  usedBones: number[]
  m: Float64Array
  accN: Float64Array
  touched: Uint8Array
}

/**
 * Bind the opening of `ch` to the BODY meshes under `root` (skinned, never a garment's, `inGarment`): per mesh the
 * candidates in the current pose. Null when no body vertex is a candidate.
 */
export function bindChannelOpening(three: Three, root: Object3D, ch: ChannelNow,
  options: OpeningOptions & { slack?: number } = {}): ChannelOpeningBinding | null {
  root.updateMatrixWorld(true)
  const falloff = options.falloff ?? OPENING_FALLOFF_M
  const meshes: SkinnedMesh[] = []
  root.traverse(o => {
    const mesh = o as SkinnedMesh
    if (mesh.isSkinnedMesh && mesh.skeleton && !inGarment(mesh) && mesh.geometry?.attributes?.position) meshes.push(mesh)
  })
  const v = new three.Vector3()
  const entries: MeshEntry[] = []
  for (const mesh of meshes) {
    const pos = mesh.geometry.attributes.position
    const world = new Float32Array(pos.count * 3)
    for (let i = 0; i < pos.count; i++) {
      mesh.getVertexPosition(i, v).applyMatrix4(mesh.matrixWorld)
      world[3 * i] = v.x; world[3 * i + 1] = v.y; world[3 * i + 2] = v.z
    }
    const idx = openingCandidates(world, ch, falloff, options.slack ?? OPENING_SLACK_M)
    if (!idx.length) continue
    const slot = new Int32Array(pos.count).fill(-1)
    idx.forEach((i, k) => { slot[i] = k })
    const sBind = new Float32Array(idx.length), rhoBind = new Float32Array(idx.length)
    idx.forEach((i, k) => {
      const c = channelCoords([world[3 * i], world[3 * i + 1], world[3 * i + 2]], ch)
      sBind[k] = c.s; rhoBind[k] = c.rho
    })
    const index = mesh.geometry.index
    const tri: number[] = []
    const triCount = Math.floor((index ? index.count : pos.count) / 3)
    for (let f = 0; f < triCount; f++) {
      const a = index ? index.getX(3 * f) : 3 * f, b = index ? index.getX(3 * f + 1) : 3 * f + 1
      const c = index ? index.getX(3 * f + 2) : 3 * f + 2
      if (slot[a] >= 0 || slot[b] >= 0 || slot[c] >= 0) tri.push(a, b, c)
    }
    const groupOf = new Map<string, number>()
    const group = new Int32Array(idx.length)
    idx.forEach((i, k) => {
      const key = `${pos.getX(i).toFixed(6)},${pos.getY(i).toFixed(6)},${pos.getZ(i).toFixed(6)}`
      let g = groupOf.get(key)
      if (g === undefined) { g = groupOf.size; groupOf.set(key, g) }
      group[k] = g
    })
    entries.push({ mesh, original: mesh.geometry, clone: null, idx, sBind, rhoBind, rest: new Float32Array(idx.length * 3),
      restNormal: null, tris: new Uint32Array(tri), slot, group, groups: groupOf.size, moved: new Uint8Array(idx.length),
      ...skinOf(mesh, idx), m: new Float64Array(16), accN: new Float64Array(groupOf.size * 3),
      touched: new Uint8Array(groupOf.size) })
  }
  if (!entries.length) return null
  const boneM = new three.Matrix4(), meshM = new three.Matrix4()
  /** Per mesh this frame: the matrix bind position → world of each bone the candidates use
   *  (meshWorld · bindMatrixInverse · boneWorld · boneInverse · bindMatrix, column-major, 16 per bone). */
  const boneCache = new Map<SkinnedMesh, Float64Array>()
  const frameBones = (e: MeshEntry): Float64Array => {
    const bones = e.mesh.skeleton.bones, inv = e.mesh.skeleton.boneInverses
    let out = boneCache.get(e.mesh)
    if (!out) { out = new Float64Array(bones.length * 16); boneCache.set(e.mesh, out) }
    meshM.multiplyMatrices(e.mesh.matrixWorld, e.mesh.bindMatrixInverse)
    for (const b of e.usedBones) {
      if (!bones[b]) continue
      boneM.multiplyMatrices(bones[b].matrixWorld, inv[b]).premultiply(meshM).multiply(e.mesh.bindMatrix)
      for (let k = 0; k < 16; k++) out[16 * b + k] = boneM.elements[k]
    }
    return out
  }
  const disp = new Float64Array(3)
  // --- A102b: what the last apply read, to skip unchanged frames ---
  /** The segments (a, b, r: 7 per segment) and the channel (o, u) of the last apply; null = none yet. */
  let lastSegs: Float64Array | null = null
  const lastCh = new Float64Array(6)
  /** Per mesh: the world matrices of its used bones at the last apply (16 per used bone, usedBones order). */
  const lastBones = new Map<MeshEntry, Float64Array>()
  const snapshot = (now: ChannelNow, segments: readonly OpeningSegment[]) => {
    lastSegs = new Float64Array(segments.length * 7)
    segments.forEach((seg, k) => { lastSegs!.set([...seg.a, ...seg.b, seg.r], 7 * k) })
    lastCh.set([...now.o, ...now.u])
    for (const e of entries) {
      const bones = e.mesh.skeleton.bones
      let arr = lastBones.get(e)
      if (!arr) { arr = new Float64Array(e.usedBones.length * 16); lastBones.set(e, arr) }
      e.usedBones.forEach((b, k) => { if (bones[b]) arr!.set(bones[b].matrixWorld.elements, 16 * k) })
    }
  }
  /** Did a world matrix move more than tolM or turn more than tolDeg against `prev` (16 at `off`)? The turn is read off
   *  the largest change of a unit basis column (|Δcolumn| ≈ angle for small angles). */
  const matrixMoved = (m: ArrayLike<number>, prev: Float64Array, off: number, tolM: number, tolRad: number) => {
    if (Math.hypot(m[12] - prev[off + 12], m[13] - prev[off + 13], m[14] - prev[off + 14]) > tolM) return true
    for (let c = 0; c < 3; c++) {
      const len = Math.hypot(m[4 * c], m[4 * c + 1], m[4 * c + 2]) || 1
      const d = Math.hypot(m[4 * c] - prev[off + 4 * c], m[4 * c + 1] - prev[off + 4 * c + 1], m[4 * c + 2] - prev[off + 4 * c + 2])
      if (d / len > tolRad) return true
    }
    return false
  }
  const changed = (now: ChannelNow, segments: readonly OpeningSegment[], tolM: number, tolDeg: number): boolean => {
    if (!active || !lastSegs || lastSegs.length !== segments.length * 7) return true
    const tolRad = 2 * Math.sin((tolDeg * Math.PI) / 360)
    for (let k = 0; k < segments.length; k++) {
      const seg = segments[k], o = 7 * k
      if (Math.hypot(seg.a[0] - lastSegs[o], seg.a[1] - lastSegs[o + 1], seg.a[2] - lastSegs[o + 2]) > tolM) return true
      if (Math.hypot(seg.b[0] - lastSegs[o + 3], seg.b[1] - lastSegs[o + 4], seg.b[2] - lastSegs[o + 5]) > tolM) return true
      if (Math.abs(seg.r - lastSegs[o + 6]) > tolM) return true
    }
    if (Math.hypot(now.o[0] - lastCh[0], now.o[1] - lastCh[1], now.o[2] - lastCh[2]) > tolM) return true
    if (Math.hypot(now.u[0] - lastCh[3], now.u[1] - lastCh[4], now.u[2] - lastCh[5]) > tolRad) return true
    for (const e of entries) {
      const prev = lastBones.get(e)
      if (!prev) return true
      const bones = e.mesh.skeleton.bones
      for (let k = 0; k < e.usedBones.length; k++) {
        const bone = bones[e.usedBones[k]]
        if (bone && matrixMoved(bone.matrixWorld.elements, prev, 16 * k, tolM, tolRad)) return true
      }
    }
    return false
  }
  let active = false
  const putBack = () => {
    for (const e of entries) {
      if (!e.clone) continue
      const pos = e.clone.attributes.position as BufferAttribute
      const nrm = e.clone.attributes.normal as BufferAttribute | undefined
      e.idx.forEach((i, k) => {
        pos.setXYZ(i, e.rest[3 * k], e.rest[3 * k + 1], e.rest[3 * k + 2])
        if (nrm && e.restNormal) nrm.setXYZ(i, e.restNormal[3 * k], e.restNormal[3 * k + 1], e.restNormal[3 * k + 2])
      })
      pos.needsUpdate = true
      if (nrm) nrm.needsUpdate = true
      e.mesh.geometry = e.original
    }
    active = false
  }
  /** The normals of the candidates a moved candidate's triangle touches, from their triangles (area-weighted face
   *  normals, bind space, accumulated per rest-position group so a seam stays one surface). Every other vertex
   *  keeps its own normal. */
  const renormal = (e: MeshEntry, pos: BufferAttribute, nrm: BufferAttribute) => {
    const acc = e.accN.fill(0)
    const touched = e.touched.fill(0)
    const P = pos.array as ArrayLike<number>
    const direct = !(pos as { isInterleavedBufferAttribute?: boolean }).isInterleavedBufferAttribute && pos.itemSize === 3
    const gx = (i: number) => direct ? P[3 * i] : pos.getX(i), gy = (i: number) => direct ? P[3 * i + 1] : pos.getY(i)
    const gz = (i: number) => direct ? P[3 * i + 2] : pos.getZ(i)
    const tris = e.tris, slot = e.slot, mv = e.moved, grp = e.group
    for (let t = 0; t < tris.length; t += 3) {
      const a = tris[t], b = tris[t + 1], c = tris[t + 2]
      const ka = slot[a], kb = slot[b], kc = slot[c]
      const hot = (ka >= 0 && mv[ka] === 1) || (kb >= 0 && mv[kb] === 1) || (kc >= 0 && mv[kc] === 1)
      if (!hot && !(ka >= 0 && mv[ka] === 2) && !(kb >= 0 && mv[kb] === 2) && !(kc >= 0 && mv[kc] === 2)) continue
      const ax = gx(a), ay = gy(a), az = gz(a)
      const ux = gx(b) - ax, uy = gy(b) - ay, uz = gz(b) - az
      const vx = gx(c) - ax, vy = gy(c) - ay, vz = gz(c) - az
      const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx
      if (ka >= 0) { const g = grp[ka]; acc[3 * g] += nx; acc[3 * g + 1] += ny; acc[3 * g + 2] += nz; if (hot) touched[g] = 1 }
      if (kb >= 0) { const g = grp[kb]; acc[3 * g] += nx; acc[3 * g + 1] += ny; acc[3 * g + 2] += nz; if (hot) touched[g] = 1 }
      if (kc >= 0) { const g = grp[kc]; acc[3 * g] += nx; acc[3 * g + 1] += ny; acc[3 * g + 2] += nz; if (hot) touched[g] = 1 }
    }
    for (let k = 0; k < e.idx.length; k++) {
      const g = grp[k]
      if (!touched[g]) continue
      const n = Math.hypot(acc[3 * g], acc[3 * g + 1], acc[3 * g + 2])
      if (n > 0) nrm.setXYZ(e.idx[k], acc[3 * g] / n, acc[3 * g + 1] / n, acc[3 * g + 2] / n)
    }
    nrm.needsUpdate = true
  }
  return {
    channel: ch.id,
    candidates: entries.reduce((n, e) => n + e.idx.length, 0),
    apply(now, segments, opts = options) {
      if (!segments.length) { if (active) putBack(); return { maxPush: 0, moved: 0, visited: 0 } }
      const reach = openingReach(segments, now, opts)
      let maxPush = 0, moved = 0, visited = 0
      for (const e of entries) {
        if (!e.clone) e.clone = e.original.clone()
        const pos = e.clone.attributes.position as BufferAttribute
        const nrm = e.clone.attributes.normal as BufferAttribute | undefined
        if (!active) {
          e.idx.forEach((i, k) => { e.rest[3 * k] = pos.getX(i); e.rest[3 * k + 1] = pos.getY(i); e.rest[3 * k + 2] = pos.getZ(i) })
          if (nrm) {
            e.restNormal ??= new Float32Array(e.idx.length * 3)
            e.idx.forEach((i, k) => { e.restNormal![3 * k] = nrm.getX(i); e.restNormal![3 * k + 1] = nrm.getY(i); e.restNormal![3 * k + 2] = nrm.getZ(i) })
          }
        }
        e.mesh.geometry = e.clone
        let any = false
        const M = frameBones(e)
        const m = e.m
        for (let k = 0; k < e.idx.length; k++) {
          const i = e.idx[k]
          const rx = e.rest[3 * k], ry = e.rest[3 * k + 1], rz = e.rest[3 * k + 2]
          // Every candidate at rest first: the skinned world positions this frame are then the body's own.
          // A candidate moved last frame (mark 1) is reset; its triangles are renormalled once more (mark 2).
          if (e.moved[k] === 1) {
            pos.setXYZ(i, rx, ry, rz)
            if (nrm && e.restNormal) nrm.setXYZ(i, e.restNormal[3 * k], e.restNormal[3 * k + 1], e.restNormal[3 * k + 2])
            e.moved[k] = 2
          } else e.moved[k] = 0
          if (e.sBind[k] < reach.sMin || e.sBind[k] > reach.sMax || e.rhoBind[k] > reach.rhoMax) continue
          visited++
          // The blended skin matrix (12 used elements), then the skinned world position.
          m.fill(0)
          for (let j = 0; j < 4; j++) {
            const w = e.skinW[4 * k + j]
            if (!(w > 0)) continue
            const o = 16 * e.skinI[4 * k + j]
            for (let q = 0; q < 16; q++) m[q] += M[o + q] * w
          }
          const px = m[0] * rx + m[4] * ry + m[8] * rz + m[12]
          const py = m[1] * rx + m[5] * ry + m[9] * rz + m[13]
          const pz = m[2] * rx + m[6] * ry + m[10] * rz + m[14]
          const push = displaceInto(px, py, pz, now, segments, opts, disp)
          if (!(push > 0)) continue
          moved++
          e.moved[k] = 1
          if (push > maxPush) maxPush = push
          // World displacement → bind space through the inverse of the linear part (3×3, column-major).
          const a = m[0], b = m[4], c = m[8], d = m[1], f = m[5], g = m[9], h = m[2], ii = m[6], jj = m[10]
          const A = f * jj - g * ii, B = -(d * jj - g * h), C = d * ii - f * h
          const det = a * A + b * B + c * C
          if (!(Math.abs(det) > 1e-20)) continue
          const x = disp[0], y = disp[1], z = disp[2]
          const bx = (A * x + (c * ii - b * jj) * y + (b * g - c * f) * z) / det
          const by = (B * x + (a * jj - c * h) * y + (c * d - a * g) * z) / det
          const bz = (C * x + (b * h - a * ii) * y + (a * f - b * d) * z) / det
          pos.setXYZ(i, rx + bx, ry + by, rz + bz)
          any = true
        }
        pos.needsUpdate = true
        if (nrm) {
          if (any || e.moved.includes(2)) renormal(e, pos, nrm)
          else nrm.needsUpdate = true
        }
      }
      active = true
      snapshot(now, segments)
      return { maxPush, moved, visited }
    },
    changed(now, segments, tolM = OPENING_SKIP_M, tolDeg = OPENING_SKIP_DEG) { return changed(now, segments, tolM, tolDeg) },
    restore() { if (active) putBack() },
    dispose() {
      putBack()
      for (const e of entries) { e.clone?.dispose(); e.clone = null }
    },
  }
}
