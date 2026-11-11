#!/usr/bin/env node
/**
 * Motion check for a FITTED SHOE — how a shod figure stands, walks and sits on
 * the real library clips (spec `docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`
 * § 6.5 / § 8, contract `docs/schnittstellen-3d.md` "Footwear (`foot_pose`, garment kind `footwear`)").
 * A measurement, not a smoke: it prints numbers and judges nothing (exit 0 unless it cannot run).
 *
 * Usage:
 *   node scripts/check_footwear.mjs MODEL.glb META.json
 *        [--clips idle,walk,sit]      clip kinds (default idle,walk,sit; a kind without a file is skipped)
 *        [--set female]               clip set tried before the root set
 *        [--groups sit=seat,…]        height group per kind (default: a kind containing "sit"/"seat" is
 *                                     `seat`, "lie"/"sleep" `lie`, everything else `ground`)
 *        [--samples 4]                penetration samples per clip at t = k/N · duration
 *        [--bare BARE.glb]            the UNCUT bare outfit model the assembly was built from (`{sig}.glb`):
 *                                     decides stance on a served body that is cut under the shoe (below)
 *        [--clip-json KIND=FILE]      a three.js AnimationClip JSON (`AnimationClip.toJSON`: name, duration,
 *                                     tracks) played as the library clip KIND, in donor space like an FBX;
 *                                     repeatable, taken before the `--clips` kinds (a fixture clip, e.g. one key)
 *        [--json FILE]                write the numbers as JSON
 *   MODEL.glb = the served (assembled) model: body + the shoe nodes `garment_footwear_<item>_<side>` — a BOOT adds
 *   per side the shaft node `garment_footwear_<item>_<side>_shaft` (extras `part: "shaft"`; contract
 *   `docs/schnittstellen-3d.md` "Footwear", Boots), four nodes in all.
 *   META.json = anything carrying the `foot_pose` record: the assembled sidecar or `/model/meta`
 *   (`foot_pose`), the `/model3d` response (`model.foot_pose`), or the bare record. A record without
 *   `source` (a raw `footwear_fit.fit_pair` result) takes item and fsig from the GLB's shoe nodes.
 *   Clips come from ANIMATION_CLIPS_DIR (default shared/models/clips), the retarget reference from
 *   ANIMATION_RIG_FILE (default shared/models/rig/reference.fbx) — read only. Self-bundling via esbuild;
 *   runs without the server and without a world.
 *
 * THE POSE is the 3D client's, through the SAME functions: `adaptExternalClips` of client3d with the
 * `shoes` option (rest corrections against the reference rig, hips height against the rig's hips;
 * inside it `prepareShoes` → scene-render's `applyFootPose` with the transplanted rest + `plantFootPose`),
 * then scene-render's `measureClipGround` on a `SkeletonUtils` clone with `rootY = footPoseLiftM(fp, group)`.
 * The figure root stands at `footPoseLiftM(fp, group) − groundOffset` — the offset only for the ground
 * group, the client's terrain placement (`Figure.play` applies it to a terrain clip only; an ACTIVITY clip
 * stands `groundOffset` lower, printed beside it). A three AnimationMixer plays the clip, every skinned
 * mesh is skinned on the CPU with three's skinning math (cross-checked against
 * `SkinnedMesh.applyBoneTransform`). The BARE figure is the same GLB with the clip adapted WITHOUT shoes
 * and the root at 0 (the shoe meshes ignored) — it decides stance, as the plant does.
 *
 * FLOOR = `figureBox(figure).min.y` of the SERVED model (garment subtrees excluded, § A3a) — the plane
 * every renderer anchors the figure on and the plant and the ground measure aim at. On an uncut body it
 * is the bare bind soles. On the served file the body is cut under the shoe (§ 7.1), its plantar foot is
 * gone and the box's lowest point is whatever the cut left: `--bare` prints how far that raised the
 * floor over the bare soles (`bind_floor_raise_mm`) and decides stance on the uncut feet. Without
 * `--bare` a cut body (a long boundary loop near the floor) is reported and its stance is read on the
 * cut foot, which no longer reaches the floor (few or no stance frames).
 *
 * NUMBERS (mm over the floor, negative = through it; frames at 30 fps, every frame of the clip)
 *  - still: the shod still pose (`applyFootPoseToPose`, root at `root_lift_m`) — the fit's `stand_floor`
 *    reproduced by the renderer's turn; plus its penetration and Foot pitch (the reference row).
 *  - sole: per frame and side the lowest SHOE vertex. Ground clips: `lower` = the lower side per frame
 *    (what the figure stands on — the stand number, target ±3 mm), and per side the STANCE frames — the
 *    bare foot's lowest point within 10 mm of the floor (Task 13's definition; with `--bare` the uncut
 *    bare model's foot over ITS floor) — with their runs on the
 *    loop: `strike` = the first 3 stance frames of a run, `off` = the last 3 (walk target −3 … +13 mm).
 *    Seat clips: `seatFootLift` runs per frame against the bind sole plane (the shipped rest — the figure's
 *    floor), as both renderers do; then the lowest contact of `foot_pose.contacts` per frame (the spec's
 *    `seat_floor`, target −3 … +10 mm, P3b), the hips' height shod − bare (must be 0), the ankle raise and the
 *    knee's rise (its world y after − before the IK, max over the clip — the table-top risk). Lie clips: the
 *    contacts and hips as they come.
 *  - pitch: the total Foot pitch per side = how far the Foot joint → ToeBase joint line pitches down
 *    (ankle above the ball = positive, degrees, world) BEYOND the same line in the bare bind pose — the
 *    plantarflexion over the bare standing foot. Shod = the fit's extension plus the clip's own
 *    plantarflexion (spec § 6.2: no clamp in v1); the max over the clip, with the still pose (≈ the
 *    record's Foot `deg`, a self-check of the definition) and the bare clip's max beside it. The bind
 *    line's own pitch is printed once (`bind_joint_line_pitch_deg`; the joints are not the sole).
 *  - penetration: the share of SHOE vertices deeper than 5 mm inside the BODY, at `--samples` times per
 *    clip and in the still pose, per side. The metric of `check_garment_collision.mjs` (the S1 spike's
 *    `motion_pen.py`): the body's triangles sampled into a 4 mm voxel grid over the posed figure, dilated
 *    once, hole-filled from the grid border = the body volume, the exact EDT gives each inside voxel its
 *    depth, each shoe vertex reads it trilinearly. THE CUT: the served body is cut open under the shoe
 *    (§ 7.1), so its leg ends in an open rim and the border flood would run up the leg into the whole
 *    body. Every boundary loop of the body (edges with no twin after welding the vertices by bind
 *    position — glTF splits them at UV seams) is therefore closed by a fan from its posed centroid
 *    before voxelising; `cap_loops` lists them. A sample whose volume still leaks is marked `!`
 *    (`body_volume_closed: false`) and its share is meaningless. On an UNCUT body (the P2 preview model)
 *    the share counts the shoe surface the bare foot pokes through (toes through the vamp), not a
 *    defect of the served file. Every footwear node of a side counts — a boot's shaft as well as its foot part.
 *
 * BOOTS (spec `docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md` § 6.3, § 6.4, § 7, § 9; a side with
 * a shaft node). The record of the fit is not read: everything comes from the GLB. Per side, in BIND space:
 * `band_top` = the lowest shaft-node vertex without Foot / ToeBase weight (≤ `NO_FOOT_W`) — above the band the
 * shaft carries Leg / UpLeg only (fit ruling 8a), so this is the first vertex row above `y_split + SPLIT_BAND_M`;
 * `shaft_top` = the shaft node's highest vertex; the seam pairs = every shaft-node vertex with a foot-node vertex
 * at the same bind position (the band faces straddle the node boundary with shared positions and weights).
 * Measured in the still pose and in EVERY clip frame (`per_frame`, the clip's `boot` block; the worse side):
 *  - `seam_gap_mm`: the largest distance between the two vertices of a seam pair after skinning — 0 up to float
 *    rounding when the two nodes carry the same weights (a crack at the split shows here).
 *  - `shaft_leg_follow_deg`: the turn of the shaft's ring against the side's Leg bone — the ring's posed points
 *    against the same bind points moved by the Leg bone's skin matrix alone, best-fit rotation (Kabsch) angle.
 *    The ring as the fit reads it: the shaft above `band_top + RING_ABOVE_BAND_M` (= `y_split + 0.06`), with fewer
 *    than `FOLLOW_RING_MIN` vertices the shaft's upper half (from the middle of `band_top` and `shaft_top` up),
 *    else null (never a vacuous 0).
 *  - `shaft_poke`: the share of the side's body vertices whose dominant bone is the side's Leg / UpLeg, with bind
 *    height in [`band_top`, `shaft_top`], that lie OUTSIDE the boot — the side's footwear nodes posed, every
 *    boundary loop of them (welded by bind position across both nodes — the collar) closed by a fan from its
 *    centroid, voxelised like the body (`VOX`, dilated once, flood-filled from the grid border): a vertex in the
 *    flood (or off the grid) pokes through. Null without such a vertex.
 *  - `seat_thigh_in_shaft` (seat clips only, after `seatFootLift`): the share of the side's UpLeg-dominant body
 *    vertices inside that boot volume (not in the flood) AND within the shaft's top 5 cm — along the posed axis
 *    from the centroid of the shaft vertices `TOP_BAND_LOW_M` below the top (± 5 mm) to the centroid of its top
 *    5 mm, between 5 cm below the top plane and 5 mm above it. Null without an UpLeg bone.
 * Once, in the bind pose: `open_loops_above_split` = the body boundary loops (THE CUT above) whose centroid lies
 * in (`band_top`, `shaft_top`] and whose every vertex is dominated by that side's Foot / ToeBase / Leg / UpLeg —
 * a hole in the leg shell under the shaft (the anti-goal of spec § 4: the shin is never cut under a shaft). 0 on
 * a served boot. The sole numbers read the foot part only.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
// The bundled copy runs from /tmp with cwd = the repo (set by the self-bundling step below).
const REPO = process.env.SMOKE_BUNDLED ? process.cwd() : path.join(__dirname, '..')

const FPS = 30
const STANCE_MM = 10
const VOX = 0.004
const DEPTH = 0.005
// boots (module docstring, BOOTS)
const NO_FOOT_W = 1e-3
const RING_ABOVE_BAND_M = 0.04          // footwear_fit SHAFT_RING_ABOVE_M 0.06 − SPLIT_BAND_M 0.02
const FOLLOW_RING_MIN = 3               // footwear_fit FOLLOW_RING_MIN
const THIGH_TOP_M = 0.05                // spec § 6.4 step 4: the shaft's top 5 cm
const TOP_BAND_LOW_M = 0.05
const BAND_TOL_M = 0.005

function parseArgs(argv) {
  const opts = { files: [], clips: ['idle', 'walk', 'sit'], set: '', samples: 4, groups: {}, clipJson: [] }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--clips') opts.clips = argv[++i].split(',').filter(Boolean)
    else if (a === '--set') opts.set = argv[++i]
    else if (a === '--samples') opts.samples = Math.max(1, Number(argv[++i]))
    else if (a === '--json') opts.json = argv[++i]
    else if (a === '--bare') opts.bare = argv[++i]
    else if (a === '--clip-json') {
      const [kind, file] = argv[++i].split('=')
      if (!kind || !file) throw new Error('--clip-json KIND=FILE')
      opts.clipJson.push([kind, file])
    }
    else if (a === '--groups') {
      for (const pair of argv[++i].split(',').filter(Boolean)) {
        const [k, g] = pair.split('=')
        opts.groups[k] = g
      }
    } else if (a.startsWith('--')) throw new Error(`unknown option ${a}`)
    else opts.files.push(a)
  }
  if (opts.files.length !== 2) throw new Error('usage: check_footwear.mjs MODEL.glb META.json [options] (see the docstring)')
  return opts
}

const groupOf = (kind, opts) => opts.groups[kind]
  ?? (/sit|seat/i.test(kind) ? 'seat' : /lie|lying|sleep/i.test(kind) ? 'lie' : 'ground')

// three is a browser library; the globals the client modules touch at load time.
function stubBrowser() {
  globalThis.self = globalThis
  if (!globalThis.window) globalThis.window = globalThis
  if (!globalThis.document) {
    const el = () => ({ style: {}, getContext: () => null, setAttribute() {}, addEventListener() {} })
    globalThis.document = { createElement: el, createElementNS: el, addEventListener() {}, body: el() }
  }
  if (!globalThis.location) globalThis.location = { href: 'http://localhost/', origin: 'http://localhost' }
}

/** Strip images/textures from a GLB (node cannot decode them); geometry, skins, nodes untouched. */
function stripGlbImages(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength)
  if (dv.getUint32(0, true) !== 0x46546c67) throw new Error('not a GLB')
  let off = 12, json = null, bin = null
  while (off < buf.byteLength) {
    const len = dv.getUint32(off, true), type = dv.getUint32(off + 4, true)
    const chunk = buf.subarray(off + 8, off + 8 + len)
    if (type === 0x4e4f534a) json = JSON.parse(new TextDecoder().decode(chunk))
    else if (type === 0x004e4942) bin = chunk
    off += 8 + len
  }
  delete json.images; delete json.textures; delete json.samplers
  for (const m of json.materials ?? []) {
    const pbr = m.pbrMetallicRoughness
    if (pbr) { delete pbr.baseColorTexture; delete pbr.metallicRoughnessTexture }
    delete m.normalTexture; delete m.occlusionTexture; delete m.emissiveTexture
    for (const e of Object.values(m.extensions ?? {})) for (const k of Object.keys(e)) if (/Texture$/.test(k)) delete e[k]
  }
  const jsonBytes = new TextEncoder().encode(JSON.stringify(json))
  const pad = (n) => (4 - (n % 4)) % 4
  const jlen = jsonBytes.length + pad(jsonBytes.length)
  const blen = bin ? bin.length + pad(bin.length) : 0
  const total = 12 + 8 + jlen + (bin ? 8 + blen : 0)
  const out = new Uint8Array(total)
  const o = new DataView(out.buffer)
  o.setUint32(0, 0x46546c67, true); o.setUint32(4, 2, true); o.setUint32(8, total, true)
  o.setUint32(12, jlen, true); o.setUint32(16, 0x4e4f534a, true)
  out.set(jsonBytes, 20)
  for (let i = jsonBytes.length; i < jlen; i++) out[20 + i] = 0x20
  if (bin) {
    const b = 20 + jlen
    o.setUint32(b, blen, true); o.setUint32(b + 4, 0x004e4942, true)
    out.set(bin, b + 8)
  }
  return out
}

// ---------------------------------------------------------------- the body volume (check_garment_collision.mjs)
/**
 * A closed surface `bodyFaces` (indices into the posed positions `pos`) voxelised at `VOX` over its bounds + 3 cm:
 * the triangles sampled into the grid, dilated once, flood-filled from the grid border. `outside[i]` = reached
 * by the flood; `isOutside(x, y, z)` the same for a point (off the grid = outside).
 */
function voxelSolid(pos, bodyFaces) {
  let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
  for (let f = 0; f < bodyFaces.length; f++) {
    const i = bodyFaces[f] * 3
    for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], pos[i + k]); hi[k] = Math.max(hi[k], pos[i + k]) }
  }
  lo = lo.map((v) => v - 0.03)
  const shape = hi.map((v, k) => Math.ceil((v + 0.03 - lo[k]) / VOX) + 1)
  const [nx, ny, nz] = shape
  const N = nx * ny * nz
  const at = (x, y, z) => (x * ny + y) * nz + z
  const surf = new Uint8Array(N)
  const baryOf = []
  const grid = (n) => {
    if (baryOf[n]) return baryOf[n]
    const out = []
    for (let i = 0; i <= n; i++) for (let j = 0; i + j <= n; j++) out.push([1 - (i + j) / n, i / n, j / n])
    return (baryOf[n] = out)
  }
  const len = (p, q) => Math.hypot(pos[p] - pos[q], pos[p + 1] - pos[q + 1], pos[p + 2] - pos[q + 2])
  for (let f = 0; f < bodyFaces.length; f += 3) {
    const a = bodyFaces[f] * 3, b = bodyFaces[f + 1] * 3, c = bodyFaces[f + 2] * 3
    const n = Math.max(3, Math.ceil(Math.max(len(a, b), len(b, c), len(c, a)) / (0.5 * VOX)))
    for (const [w0, w1, w2] of grid(n)) {
      const x = Math.round((pos[a] * w0 + pos[b] * w1 + pos[c] * w2 - lo[0]) / VOX)
      const y = Math.round((pos[a + 1] * w0 + pos[b + 1] * w1 + pos[c + 1] * w2 - lo[1]) / VOX)
      const z = Math.round((pos[a + 2] * w0 + pos[b + 2] * w1 + pos[c + 2] * w2 - lo[2]) / VOX)
      surf[at(x, y, z)] = 1
    }
  }
  const dil = new Uint8Array(N)
  for (let x = 0; x < nx; x++) for (let y = 0; y < ny; y++) for (let z = 0; z < nz; z++) {
    const i = at(x, y, z)
    if (surf[i] || (x > 0 && surf[i - ny * nz]) || (x < nx - 1 && surf[i + ny * nz])
      || (y > 0 && surf[i - nz]) || (y < ny - 1 && surf[i + nz]) || (z > 0 && surf[i - 1]) || (z < nz - 1 && surf[i + 1])) dil[i] = 1
  }
  const outside = new Uint8Array(N)
  const stack = new Int32Array(N)
  let sp = 0
  const seed = (i) => { if (!dil[i] && !outside[i]) { outside[i] = 1; stack[sp++] = i } }
  for (let x = 0; x < nx; x++) for (let y = 0; y < ny; y++) for (let z = 0; z < nz; z++) {
    if (x === 0 || y === 0 || z === 0 || x === nx - 1 || y === ny - 1 || z === nz - 1) seed(at(x, y, z))
  }
  while (sp) {
    const i = stack[--sp]
    const z = i % nz, y = ((i - z) / nz) % ny, x = (i - z - y * nz) / (ny * nz)
    if (x > 0) seed(i - ny * nz); if (x < nx - 1) seed(i + ny * nz)
    if (y > 0) seed(i - nz); if (y < ny - 1) seed(i + nz)
    if (z > 0) seed(i - 1); if (z < nz - 1) seed(i + 1)
  }
  const isOutside = (px, py, pz) => {
    const x = Math.round((px - lo[0]) / VOX), y = Math.round((py - lo[1]) / VOX), z = Math.round((pz - lo[2]) / VOX)
    if (x < 0 || y < 0 || z < 0 || x >= nx || y >= ny || z >= nz) return true
    return outside[at(x, y, z)] === 1
  }
  return { lo, nx, ny, nz, N, at, dil, outside, isOutside }
}

/** Body volume + depth field for posed positions `pos` and body faces `bodyFaces` (indices into `pos`). */
function depthField(pos, bodyFaces) {
  const { lo, nx, ny, nz, N, at, dil, outside } = voxelSolid(pos, bodyFaces)
  let shell = 0, inside = 0
  for (let i = 0; i < N; i++) { if (dil[i]) shell++; if (!outside[i]) inside++ }
  const closed = inside - shell > 0.05 * shell
  const INF = 1e20
  const d2 = new Float32Array(N)
  for (let i = 0; i < N; i++) d2[i] = outside[i] ? 0 : INF
  const maxn = Math.max(nx, ny, nz)
  const f = new Float64Array(maxn), out = new Float64Array(maxn), v = new Int32Array(maxn), zz = new Float64Array(maxn + 1)
  const pass1d = (n) => {
    let k = 0
    v[0] = 0; zz[0] = -Infinity; zz[1] = Infinity
    for (let q = 1; q < n; q++) {
      let s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
      while (s <= zz[k]) { k--; s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]) }
      k++; v[k] = q; zz[k] = s; zz[k + 1] = Infinity
    }
    k = 0
    for (let q = 0; q < n; q++) {
      while (zz[k + 1] < q) k++
      out[q] = (q - v[k]) * (q - v[k]) + f[v[k]]
    }
  }
  const axis = (n, count, base, stride) => {
    for (let c = 0; c < count; c++) {
      const b = base(c)
      let any = false
      for (let q = 0; q < n; q++) { f[q] = d2[b + q * stride]; if (f[q] !== 0) any = true }
      if (!any) continue
      pass1d(n)
      for (let q = 0; q < n; q++) d2[b + q * stride] = out[q]
    }
  }
  axis(nz, nx * ny, (c) => c * nz, 1)
  axis(ny, nx * nz, (c) => Math.floor(c / nz) * ny * nz + (c % nz), nz)
  axis(nx, ny * nz, (c) => c, ny * nz)
  const depthAt = (px, py, pz) => {
    const gx = (px - lo[0]) / VOX, gy = (py - lo[1]) / VOX, gz = (pz - lo[2]) / VOX
    const x0 = Math.floor(gx), y0 = Math.floor(gy), z0 = Math.floor(gz)
    let sum = 0
    for (let dx = 0; dx <= 1; dx++) for (let dy = 0; dy <= 1; dy++) for (let dz = 0; dz <= 1; dz++) {
      const x = x0 + dx, y = y0 + dy, z = z0 + dz
      const w = (dx ? gx - x0 : 1 - (gx - x0)) * (dy ? gy - y0 : 1 - (gy - y0)) * (dz ? gz - z0 : 1 - (gz - z0))
      if (!w || x < 0 || y < 0 || z < 0 || x >= nx || y >= ny || z >= nz) continue
      sum += w * Math.sqrt(d2[at(x, y, z)]) * VOX
    }
    return sum
  }
  return { depthAt, closed }
}

/**
 * The body's boundary loops (module docstring, THE CUT): vertices welded by bind position, a directed
 * edge without its reverse twin is a boundary edge, chained into loops. Returns arrays of vertex
 * indices (one representative per welded position), loops of fewer than 3 vertices dropped.
 */
function boundaryLoops(bindPos, faces, isBody) {
  const weld = new Map()
  const rep = new Int32Array(bindPos.length / 3).fill(-1)
  for (let i = 0; i < rep.length; i++) {
    if (!isBody[i]) continue
    const key = `${Math.round(bindPos[i * 3] * 1e6)},${Math.round(bindPos[i * 3 + 1] * 1e6)},${Math.round(bindPos[i * 3 + 2] * 1e6)}`
    if (!weld.has(key)) weld.set(key, i)
    rep[i] = weld.get(key)
  }
  const edges = new Map()
  const ek = (a, b) => `${a},${b}`
  for (let f = 0; f < faces.length; f += 3) {
    if (!isBody[faces[f]]) continue
    const t = [rep[faces[f]], rep[faces[f + 1]], rep[faces[f + 2]]]
    if (t[0] === t[1] || t[1] === t[2] || t[0] === t[2]) continue
    for (let k = 0; k < 3; k++) {
      const key = ek(t[k], t[(k + 1) % 3])
      edges.set(key, (edges.get(key) ?? 0) + 1)
    }
  }
  const next = new Map()
  for (const key of edges.keys()) {
    const [a, b] = key.split(',').map(Number)
    if (edges.has(ek(b, a))) continue
    if (!next.has(a)) next.set(a, [])
    next.get(a).push(b)
  }
  const loops = []
  for (const start of [...next.keys()]) {
    while (next.get(start)?.length) {
      const loop = [start]
      let cur = next.get(start).pop()
      while (cur !== start && cur !== undefined && loop.length < 1e6) {
        loop.push(cur)
        const out = next.get(cur)
        cur = out?.length ? out.pop() : undefined
      }
      if (loop.length >= 3) loops.push(loop)
    }
  }
  return loops
}

/** The eigenvector of the largest eigenvalue of a symmetric 4×4 matrix (cyclic Jacobi). */
function topEigen4(A) {
  const a = A.map((r) => r.slice())
  const V = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
  for (let sweep = 0; sweep < 50; sweep++) {
    let off = 0
    for (let p = 0; p < 4; p++) for (let q = p + 1; q < 4; q++) off += a[p][q] * a[p][q]
    if (off < 1e-30) break
    for (let p = 0; p < 4; p++) for (let q = p + 1; q < 4; q++) {
      if (Math.abs(a[p][q]) < 1e-300) continue
      const theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
      const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1))
      const c = 1 / Math.sqrt(t * t + 1), sn = t * c
      for (let k = 0; k < 4; k++) {
        const akp = a[k][p], akq = a[k][q]
        a[k][p] = c * akp - sn * akq; a[k][q] = sn * akp + c * akq
      }
      for (let k = 0; k < 4; k++) {
        const apk = a[p][k], aqk = a[q][k]
        a[p][k] = c * apk - sn * aqk; a[q][k] = sn * apk + c * aqk
      }
      for (let k = 0; k < 4; k++) {
        const vkp = V[k][p], vkq = V[k][q]
        V[k][p] = c * vkp - sn * vkq; V[k][q] = sn * vkp + c * vkq
      }
    }
  }
  let best = 0
  for (let k = 1; k < 4; k++) if (a[k][k] > a[best][best]) best = k
  return [V[0][best], V[1][best], V[2][best], V[3][best]]
}

/** The angle (deg) of the best-fit rotation taking the point set `Q` onto `P` (Horn's quaternion method). */
function bestFitTurnDeg(Q, P) {
  const n = Q.length
  const cq = [0, 0, 0], cp = [0, 0, 0]
  for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) { cq[k] += Q[i][k] / n; cp[k] += P[i][k] / n }
  const S = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
  for (let i = 0; i < n; i++) {
    for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) S[a][b] += (Q[i][a] - cq[a]) * (P[i][b] - cp[b])
  }
  const [[xx, xy, xz], [yx, yy, yz], [zx, zy, zz]] = S
  const q = topEigen4([
    [xx + yy + zz, yz - zy, zx - xz, xy - yx],
    [yz - zy, xx - yy - zz, xy + yx, zx + xz],
    [zx - xz, xy + yx, -xx + yy - zz, yz + zy],
    [xy - yx, zx + xz, yz + zy, -xx - yy + zz],
  ])
  const w = Math.min(1, Math.abs(q[0]) / Math.hypot(...q))
  return 2 * Math.acos(w) * 180 / Math.PI
}

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/check_footwear_bundled.mjs'
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(REPO, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm', `--outfile=${bundlePath}`, '--log-level=error',
    ], { cwd: REPO, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    // paths absolute (the bundle runs with cwd = the repo); `KIND=FILE` (--clip-json) resolves its file part
    const args = process.argv.slice(2).map((a) => {
      const kv = /^([^=/]+)=(.+)$/.exec(a)
      if (kv) return `${kv[1]}=${path.resolve(kv[2])}`
      return /\.(glb|json)$/.test(a) || a.includes('/') ? path.resolve(a) : a
    })
    const run = spawnSync('node', ['--max-old-space-size=8192', bundlePath, ...args], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: REPO,
    })
    process.exit(run.status ?? 1)
  }
  const opts = parseArgs(process.argv.slice(2))
  const [modelPath, metaPath] = opts.files
  stubBrowser()
  const THREE = await import('three')
  const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
  const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
  const { MeshoptDecoder } = await import('three/examples/jsm/libs/meshopt_decoder.module.js')
  const { clone: skclone } = await import('three/examples/jsm/utils/SkeletonUtils.js')
  const SR = await import('../packages/scene-render/src/index.ts')
  const { adaptExternalClips } = await import('../client3d/src/scene/figures.ts')
  const { restPoseOf, restCorrections, rigHipsHeight, normBoneName, inGarment, figureBox, measureClipGround,
    clipGroundOffset, applyFootPoseToPose, footPoseLiftM, footPoseMatches, footContactsNow, seatFootLift } = SR

  const arrayBufferOf = (buf) => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)
  const loadFbx = (file) => new FBXLoader().parse(arrayBufferOf(fs.readFileSync(file)), '')
  const clipDir = process.env.ANIMATION_CLIPS_DIR || path.join(REPO, 'shared/models/clips')
  const rigFile = process.env.ANIMATION_RIG_FILE || path.join(REPO, 'shared/models/rig/reference.fbx')

  // ---- figure
  const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder)
    .parseAsync(arrayBufferOf(stripGlbImages(fs.readFileSync(modelPath))), '')
  const fig = gltf.scene
  const s0 = new THREE.Box3().setFromObject(fig).getSize(new THREE.Vector3())
  if (s0.z > s0.y * 1.5) fig.rotation.x = -Math.PI / 2
  fig.updateMatrixWorld(true)

  // ---- foot pose
  const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'))
  let fp = meta?.foot_pose ?? meta?.model?.foot_pose ?? (meta?.bones && meta?.contacts ? meta : null)
  if (!fp) throw new Error(`${metaPath}: no foot_pose (a served bare model carries none — nothing to check)`)
  let shoeTag = null
  fig.traverse((o) => { const g = o.userData?.garment; if (!shoeTag && g?.kind === 'footwear') shoeTag = g })
  if (!shoeTag) throw new Error(`${modelPath}: no footwear garment node — nothing to check`)
  let sourceNote = ''
  if (!fp.source) {
    fp = { ...fp, source: { item_id: shoeTag.item_id, fsig: shoeTag.fsig, glb_sha256: '' } }
    sourceNote = ' (record had no source: item/fsig taken from the GLB)'
  }
  if (!footPoseMatches(fig, fp)) {
    throw new Error(`foot pose ${fp.source.item_id}/${fp.source.fsig} does not match the shoes of the GLB `
      + `(${shoeTag.item_id}/${shoeTag.fsig}) — a renderer would not apply it`)
  }

  // ---- clips + donor (read only)
  const library = []
  const clipFiles = {}
  for (const [kind, file] of opts.clipJson) {
    const clip = THREE.AnimationClip.parse(JSON.parse(fs.readFileSync(file, 'utf8')))
    clip.name = kind
    library.push(clip)
    clipFiles[kind] = path.relative(REPO, file)
  }
  for (const kind of opts.clips) {
    if (clipFiles[kind]) continue
    const file = [opts.set && path.join(clipDir, opts.set, `${kind}.fbx`), path.join(clipDir, `${kind}.fbx`)]
      .find((p) => p && fs.existsSync(p))
    if (!file) { console.log(`(no clip for ${kind} in ${clipDir} — skipped)`); continue }
    const clip = loadFbx(file).animations[0].clone()
    clip.name = kind
    library.push(clip)
    clipFiles[kind] = path.relative(REPO, file)
  }
  if (!library.length) throw new Error('no clip to play')
  const rig = loadFbx(rigFile)
  const donorRest = restPoseOf(THREE, rig)
  const donorHipsY = rigHipsHeight(THREE, rig)

  // ---- the client's chain: bare (stance) and shod (extension + plant inside `adaptExternalClips`)
  // the record's shipped rest (Task 20b): the bare body's box and soles — the served body is cut
  const floor = figureBox(THREE, fig, fp).min.y
  const corrections = restCorrections(THREE, donorRest, fig, undefined, fp)
  const bareClip = Object.fromEntries(adaptExternalClips(library.map((c) => c.clone()), fig, corrections, donorHipsY)
    .map((c) => [c.name, c]))
  const t0 = Date.now()
  const shodClip = Object.fromEntries(adaptExternalClips(library.map((c) => c.clone()), fig, corrections, donorHipsY,
    { footPose: fp, donorRest, unitsPerCm: 0.01 }).map((c) => [c.name, c]))
  const chainMs = Date.now() - t0
  const kinds = library.map((c) => c.name).filter((k) => shodClip[k] && bareClip[k])
  for (const k of kinds) {
    if (!shodClip[k].userData.footPosed) throw new Error(`${k}: the client chain did not pose the clip`)
  }
  const groups = Object.fromEntries(kinds.map((k) => [k, groupOf(k, opts)]))
  const ground = {}
  for (const k of kinds) {
    const probe = skclone(fig)
    probe.updateMatrixWorld(true)
    measureClipGround(THREE, [shodClip[k]], probe, { footPose: fp, rootY: footPoseLiftM(fp, groups[k]) })
    ground[k] = groups[k] === 'ground' ? clipGroundOffset(shodClip[k]) : 0
  }
  const rootY = (k) => footPoseLiftM(fp, groups[k]) - ground[k]

  // ---- `--bare`: the uncut bare model, its own clips (same skeleton), its foot vertices over its own floor
  let bareProbe = null
  if (opts.bare) {
    const tpl = (await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder)
      .parseAsync(arrayBufferOf(stripGlbImages(fs.readFileSync(opts.bare))), '')).scene
    const sb = new THREE.Box3().setFromObject(tpl).getSize(new THREE.Vector3())
    if (sb.z > sb.y * 1.5) tpl.rotation.x = -Math.PI / 2
    tpl.updateMatrixWorld(true)
    const bFloor = figureBox(THREE, tpl).min.y
    const bClips = Object.fromEntries(adaptExternalClips(library.map((c) => c.clone()), tpl,
      restCorrections(THREE, donorRest, tpl), donorHipsY).map((c) => [c.name, c]))
    const feet = { left: [], right: [] }
    tpl.traverse((o) => {
      if (!o.isSkinnedMesh || inGarment(o)) return
      const g = o.geometry, P = g.attributes.position, SI = g.attributes.skinIndex, SW = g.attributes.skinWeight
      const names = o.skeleton.bones.map((b) => normBoneName(b.name))
      for (let i = 0; i < P.count; i++) {
        if (P.getY(i) > bFloor + 0.2) continue
        let best = 0
        for (let j = 1; j < 4; j++) if (SW.getComponent(i, j) > SW.getComponent(i, best)) best = j
        const m = /^(left|right)(foot|toebase|toe_?end|leg)$/.exec(names[SI.getComponent(i, best)])
        if (m) feet[m[1]].push([o, i])
      }
    })
    const bMixer = new THREE.AnimationMixer(tpl)
    let bPlaying = null
    const v = new THREE.Vector3()
    bareProbe = {
      floor: bFloor,
      /** per side the lowest bare foot vertex over the bare floor (mm) at `t` of the bare clip `kind` */
      lowestAt(kind, t) {
        if (bPlaying !== kind) {
          bMixer.stopAllAction(); bMixer.uncacheRoot(tpl)
          bMixer.clipAction(bClips[kind]).play()
          bPlaying = kind
        }
        bMixer.setTime(t)
        tpl.updateMatrixWorld(true)
        const out = {}
        for (const side of ['left', 'right']) {
          let lo = Infinity
          for (const [mesh, i] of feet[side]) {
            v.fromBufferAttribute(mesh.geometry.attributes.position, i)
            mesh.applyBoneTransform(i, v)
            v.applyMatrix4(mesh.matrixWorld)
            lo = Math.min(lo, v.y)
          }
          out[side] = (lo - bFloor) * 1000
        }
        return out
      },
    }
  }

  // ---- parts, faces, the body's boundary loops
  const parts = []
  let total = 0
  fig.traverse((o) => {
    if (!o.isSkinnedMesh) return
    const g = o.geometry
    const garment = inGarment(o)
    let side = null, part = null
    if (garment) {
      for (let n = o; n && !side; n = n.parent) {
        const tag = n.userData?.garment
        const m = /_(left|right)(_shaft)?$/.exec(n.name)
        side = tag?.side ?? m?.[1] ?? null
        if (side) part = tag?.part ?? (m?.[2] ? 'shaft' : 'foot')
      }
    }
    parts.push({ mesh: o, garment, side, part, pos: g.attributes.position, si: g.attributes.skinIndex,
      sw: g.attributes.skinWeight, offset: total, count: g.attributes.position.count })
    total += g.attributes.position.count
  })
  const SIDES = ['left', 'right']
  // a shoe: one foot node per side; a boot: a foot node and a shaft node per side (four)
  const shoes = parts.filter((p) => p.garment && p.side)
  const body = parts.filter((p) => !p.garment)
  const footParts = shoes.filter((p) => p.part !== 'shaft')
  const shaftParts = shoes.filter((p) => p.part === 'shaft')
  if (footParts.length !== 2 || new Set(footParts.map((p) => p.side)).size !== 2 || shaftParts.length > 2
    || new Set(shaftParts.map((p) => p.side)).size !== shaftParts.length) {
    throw new Error(`expected one foot node per side (and at most one shaft node per side), got `
      + shoes.map((p) => `${p.mesh.name} (${p.side}/${p.part})`).join(', '))
  }
  const faceList = []
  for (const p of parts) {
    const idx = p.mesh.geometry.index
    if (idx) for (let i = 0; i < idx.count; i++) faceList.push(idx.getX(i) + p.offset)
    else for (let i = 0; i < p.count; i++) faceList.push(i + p.offset)
  }
  const faces = Uint32Array.from(faceList)
  const isBody = new Uint8Array(total)
  for (const p of body) isBody.fill(1, p.offset, p.offset + p.count)
  const bindRaw = new Float32Array(total * 3)
  for (const p of parts) for (let i = 0; i < p.count; i++) {
    bindRaw[(p.offset + i) * 3] = p.pos.getX(i); bindRaw[(p.offset + i) * 3 + 1] = p.pos.getY(i)
    bindRaw[(p.offset + i) * 3 + 2] = p.pos.getZ(i)
  }
  const loops = boundaryLoops(bindRaw, faces, isBody)
  // a long boundary loop near the floor = the body is cut open under the shoe (module docstring, FLOOR)
  const cutLoops = loops.filter((l) => l.length >= 50
    && l.reduce((a, v) => a + bindRaw[v * 3 + 1], 0) / l.length < floor + 0.25).length
  // the body faces + one fan per loop around an extra centroid vertex (appended after the mesh vertices)
  const capFaces = []
  loops.forEach((loop, li) => {
    for (let k = 0; k < loop.length; k++) capFaces.push(total + li, loop[k], loop[(k + 1) % loop.length])
  })
  const bodyFaces = Uint32Array.from([...faces.filter((_, k) => isBody[faces[k - (k % 3)]]), ...capFaces])
  // every footwear node of a side (penetration); the foot part alone (the sole numbers)
  const shoeIdx = { left: [], right: [] }
  for (const p of shoes) for (let i = 0; i < p.count; i++) shoeIdx[p.side].push(p.offset + i)
  const soleIdx = { left: [], right: [] }
  for (const p of footParts) for (let i = 0; i < p.count; i++) soleIdx[p.side].push(p.offset + i)
  // the bare foot vertices per side (Task 13): bind height < floor + 0.2, dominant bone of that side's foot/leg
  const footVerts = { left: [], right: [] }
  for (const p of body) {
    const names = p.mesh.skeleton.bones.map((b) => normBoneName(b.name))
    for (let i = 0; i < p.count; i++) {
      if (p.pos.getY(i) > floor + 0.2) continue
      let best = 0
      for (let j = 1; j < 4; j++) if (p.sw.getComponent(i, j) > p.sw.getComponent(i, best)) best = j
      const m = /^(left|right)(foot|toebase|toe_?end|leg)$/.exec(names[p.si.getComponent(i, best)])
      if (m) footVerts[m[1]].push(p.offset + i)
    }
  }
  const partOf = new Array(total)
  for (const p of parts) for (let i = 0; i < p.count; i++) partOf[p.offset + i] = p
  const bones = new Map()
  for (const p of body) for (const b of p.mesh.skeleton.bones) if (!bones.has(normBoneName(b.name))) bones.set(normBoneName(b.name), b)
  const hipsBone = bones.get('hips')

  // ---- the CPU skinner
  const mats = new Map()
  const updateMats = () => {
    fig.updateMatrixWorld(true)
    for (const p of parts) {
      const m = p.mesh
      mats.set(p, m.skeleton.bones.map((b, i) => new THREE.Matrix4().multiplyMatrices(m.matrixWorld, m.bindMatrixInverse)
        .multiply(b.matrixWorld).multiply(m.skeleton.boneInverses[i]).multiply(m.bindMatrix).elements))
    }
  }
  const pos = new Float32Array((total + loops.length) * 3)
  const skinV = (g) => {
    const p = partOf[g], i = g - p.offset
    const x = p.pos.getX(i), y = p.pos.getY(i), z = p.pos.getZ(i)
    let ox = 0, oy = 0, oz = 0
    const M = mats.get(p)
    for (let j = 0; j < 4; j++) {
      const w = p.sw.getComponent(i, j)
      if (!w) continue
      const e = M[p.si.getComponent(i, j)]
      ox += w * (e[0] * x + e[4] * y + e[8] * z + e[12])
      oy += w * (e[1] * x + e[5] * y + e[9] * z + e[13])
      oz += w * (e[2] * x + e[6] * y + e[10] * z + e[14])
    }
    pos[g * 3] = ox; pos[g * 3 + 1] = oy; pos[g * 3 + 2] = oz
  }
  const skinAll = () => {
    for (let g = 0; g < total; g++) skinV(g)
    loops.forEach((loop, li) => {
      let x = 0, y = 0, z = 0
      for (const v of loop) { x += pos[v * 3]; y += pos[v * 3 + 1]; z += pos[v * 3 + 2] }
      const o = (total + li) * 3
      pos[o] = x / loop.length; pos[o + 1] = y / loop.length; pos[o + 2] = z / loop.length
    })
  }
  const lowest = (idx) => {
    let lo = Infinity
    for (const g of idx) { skinV(g); lo = Math.min(lo, pos[g * 3 + 1]) }
    return (lo - floor) * 1000
  }
  const jointWorld = (key) => bones.get(key)?.getWorldPosition(new THREE.Vector3()) ?? null
  /** the Foot joint → ToeBase joint line under the horizontal (deg, world; ankle above = positive) */
  const jointLinePitch = (side) => {
    const a = jointWorld(`${side}foot`), b = jointWorld(`${side}toebase`)
    if (!a || !b) return null
    return Math.atan2(a.y - b.y, Math.hypot(a.x - b.x, a.z - b.z)) * 180 / Math.PI
  }
  // the bare BIND attitude of that line (the figure is in its bind pose here, root at 0)
  fig.updateMatrixWorld(true)
  const bindPitch = { left: jointLinePitch('left'), right: jointLinePitch('right') }
  /** total Foot pitch (deg): the joint line's pitch beyond the bare bind foot's (module docstring) */
  const footPitch = (side) => (bindPitch[side] === null ? null : jointLinePitch(side) - bindPitch[side])
  const penetration = () => {
    skinAll()
    const field = depthField(pos, bodyFaces)
    const share = (idx) => idx.filter((g) => field.depthAt(pos[g * 3], pos[g * 3 + 1], pos[g * 3 + 2]) > DEPTH).length
      / Math.max(1, idx.length)
    return { left: share(shoeIdx.left), right: share(shoeIdx.right), closed: field.closed }
  }

  // ---- boots (module docstring, BOOTS): per side the seam pairs, band top, ring, the poke / thigh sets, the collar
  const boneNamesOf = new Map()
  for (const p of parts) boneNamesOf.set(p, p.mesh.skeleton.bones.map((b) => normBoneName(b.name)))
  const dominantBone = (g) => {
    const p = partOf[g], i = g - p.offset
    let best = 0
    for (let j = 1; j < 4; j++) if (p.sw.getComponent(i, j) > p.sw.getComponent(i, best)) best = j
    return boneNamesOf.get(p)[p.si.getComponent(i, best)]
  }
  const footShare = (g, side) => {
    const p = partOf[g], i = g - p.offset, names = boneNamesOf.get(p)
    let w = 0
    for (let j = 0; j < 4; j++) {
      if (names[p.si.getComponent(i, j)]?.startsWith(`${side}foot`) || names[p.si.getComponent(i, j)]?.startsWith(`${side}toe`)) {
        w += p.sw.getComponent(i, j)
      }
    }
    return w
  }
  const bindKey = (g) => `${Math.round(bindRaw[g * 3] * 1e6)},${Math.round(bindRaw[g * 3 + 1] * 1e6)},${Math.round(bindRaw[g * 3 + 2] * 1e6)}`
  const bindY = (g) => bindRaw[g * 3 + 1]
  const boot = {}
  for (const side of SIDES) {
    const shaft = shaftParts.find((p) => p.side === side)
    if (!shaft) continue
    const foot = footParts.find((p) => p.side === side)
    const footAt = new Map()
    for (let i = 0; i < foot.count; i++) if (!footAt.has(bindKey(foot.offset + i))) footAt.set(bindKey(foot.offset + i), foot.offset + i)
    const pairs = [], shaftG = []
    let bandTop = Infinity, shaftTop = -Infinity
    for (let i = 0; i < shaft.count; i++) {
      const g = shaft.offset + i
      shaftG.push(g)
      shaftTop = Math.max(shaftTop, bindY(g))
      if (footShare(g, side) <= NO_FOOT_W) bandTop = Math.min(bandTop, bindY(g))
      const f = footAt.get(bindKey(g))
      if (f !== undefined) pairs.push([f, g])
    }
    if (!Number.isFinite(bandTop)) bandTop = null
    let ring = bandTop === null ? [] : shaftG.filter((g) => bindY(g) > bandTop + RING_ABOVE_BAND_M)
    let ringKind = 'top'
    if (ring.length < FOLLOW_RING_MIN) {
      ring = bandTop === null ? [] : shaftG.filter((g) => bindY(g) >= 0.5 * (bandTop + shaftTop))
      ringKind = 'upper_half'
    }
    if (ring.length < FOLLOW_RING_MIN) { ring = []; ringKind = null }
    // the boot's volume: both nodes, every boundary loop (welded across the nodes — the collar) closed by a fan
    const sideMask = new Uint8Array(total)
    for (const p of [foot, shaft]) sideMask.fill(1, p.offset, p.offset + p.count)
    const sideFaces = faces.filter((_, k) => sideMask[faces[k - (k % 3)]])
    const collar = boundaryLoops(bindRaw, sideFaces, sideMask)
    const verts = []
    const localOf = new Int32Array(total).fill(-1)
    for (const p of [foot, shaft]) for (let i = 0; i < p.count; i++) { localOf[p.offset + i] = verts.length; verts.push(p.offset + i) }
    const volFaces = Array.from(sideFaces, (g) => localOf[g])
    collar.forEach((loop, li) => {
      for (let k = 0; k < loop.length; k++) volFaces.push(verts.length + li, localOf[loop[k]], localOf[loop[(k + 1) % loop.length]])
    })
    const legRe = new RegExp(`^${side}(up)?leg$`)
    const sideRe = new RegExp(`^${side}(foot|toe.*|leg|upleg)$`)
    const poke = [], thigh = []
    for (const p of body) for (let i = 0; i < p.count; i++) {
      const g = p.offset + i, d = dominantBone(g)
      if (bandTop !== null && legRe.test(d) && bindY(g) >= bandTop && bindY(g) <= shaftTop) poke.push(g)
      if (d === `${side}upleg`) thigh.push(g)
    }
    // the body's boundary loops under the shaft: a hole in the leg shell (spec § 4 anti-goal)
    const openLoops = bandTop === null ? 0 : loops.filter((loop) => {
      const cy = loop.reduce((a, v) => a + bindY(v), 0) / loop.length
      return cy > bandTop && cy <= shaftTop && loop.every((v) => sideRe.test(dominantBone(v)))
    }).length
    boot[side] = {
      shaft, foot, pairs, bandTop, shaftTop, ring, ringKind, verts, collar: collar.map((l) => l.map((g) => localOf[g])),
      volFaces: Uint32Array.from(volFaces), poke, thigh: bones.has(`${side}upleg`) ? thigh : null, openLoops,
      legBone: boneNamesOf.get(shaft).indexOf(`${side}leg`),
      topRim: shaftG.filter((g) => bindY(g) >= shaftTop - BAND_TOL_M),
      topLow: shaftG.filter((g) => Math.abs(bindY(g) - (shaftTop - TOP_BAND_LOW_M)) <= BAND_TOL_M),
    }
  }
  const isBoot = Object.keys(boot).length > 0
  const centroidOf = (idx) => {
    const c = [0, 0, 0]
    for (const g of idx) for (let k = 0; k < 3; k++) c[k] += pos[g * 3 + k] / idx.length
    return c
  }
  /** The boot measures of the current pose (after `updateMats`): per side seam gap (mm), follow (deg), poke and,
   *  with `seat`, the thigh share inside the shaft's top 5 cm. */
  const bootFrame = (seat) => {
    const out = {}
    for (const side of SIDES) {
      const b = boot[side]
      if (!b) continue
      for (const g of b.verts) skinV(g)
      let gap = 0
      for (const [f, g] of b.pairs) {
        gap = Math.max(gap, Math.hypot(pos[f * 3] - pos[g * 3], pos[f * 3 + 1] - pos[g * 3 + 1], pos[f * 3 + 2] - pos[g * 3 + 2]))
      }
      let follow = null
      if (b.ring.length && b.legBone >= 0) {
        const E = mats.get(b.shaft)[b.legBone]
        const Q = [], P = []
        for (const g of b.ring) {
          const x = bindRaw[g * 3], y = bindRaw[g * 3 + 1], z = bindRaw[g * 3 + 2]
          Q.push([E[0] * x + E[4] * y + E[8] * z + E[12], E[1] * x + E[5] * y + E[9] * z + E[13], E[2] * x + E[6] * y + E[10] * z + E[14]])
          P.push([pos[g * 3], pos[g * 3 + 1], pos[g * 3 + 2]])
        }
        follow = bestFitTurnDeg(Q, P)
      }
      // the boot volume of this pose
      const local = new Float32Array((b.verts.length + b.collar.length) * 3)
      b.verts.forEach((g, i) => { local[i * 3] = pos[g * 3]; local[i * 3 + 1] = pos[g * 3 + 1]; local[i * 3 + 2] = pos[g * 3 + 2] })
      b.collar.forEach((loop, li) => {
        const o = (b.verts.length + li) * 3
        for (const v of loop) for (let k = 0; k < 3; k++) local[o + k] += local[v * 3 + k] / loop.length
      })
      const vol = voxelSolid(local, b.volFaces)
      let poke = null
      if (b.poke.length) {
        let n = 0
        for (const g of b.poke) { skinV(g); if (vol.isOutside(pos[g * 3], pos[g * 3 + 1], pos[g * 3 + 2])) n++ }
        poke = n / b.poke.length
      }
      let thigh = null
      if (seat && b.thigh && b.thigh.length && b.topRim.length && b.topLow.length) {
        const top = centroidOf(b.topRim), low = centroidOf(b.topLow)
        const ax = [top[0] - low[0], top[1] - low[1], top[2] - low[2]]
        const len = Math.hypot(...ax) || 1
        let n = 0
        for (const g of b.thigh) {
          skinV(g)
          const h = ((pos[g * 3] - top[0]) * ax[0] + (pos[g * 3 + 1] - top[1]) * ax[1] + (pos[g * 3 + 2] - top[2]) * ax[2]) / len
          if (h >= -THIGH_TOP_M && h <= BAND_TOL_M && !vol.isOutside(pos[g * 3], pos[g * 3 + 1], pos[g * 3 + 2])) n++
        }
        thigh = n / b.thigh.length
      }
      out[side] = { seam_gap_mm: gap * 1000, shaft_leg_follow_deg: follow, shaft_poke: poke, seat_thigh_in_shaft: thigh }
    }
    return out
  }

  // skin cross-check against three's own skinning
  updateMats()
  let worst = 0
  for (const p of parts) for (let k = 0; k < 30; k++) {
    const i = Math.floor((k / 30) * p.count)
    const v = new THREE.Vector3().fromBufferAttribute(p.pos, i)
    p.mesh.applyBoneTransform(i, v); v.applyMatrix4(p.mesh.matrixWorld)
    skinV(p.offset + i)
    const o = (p.offset + i) * 3
    worst = Math.max(worst, Math.hypot(v.x - pos[o], v.y - pos[o + 1], v.z - pos[o + 2]))
  }

  const r1 = (x) => (x === null || x === undefined ? null : +x.toFixed(1))
  const pc = (x) => `${(x * 100).toFixed(2)}%`
  const stats = (a) => (a.length ? { min: r1(Math.min(...a)), max: r1(Math.max(...a)), n: a.length } : null)
  const span = (s) => (s ? `${s.min} … ${s.max}` : '—')
  const report = {
    model: path.relative(REPO, modelPath), meta: path.relative(REPO, metaPath), clip_files: clipFiles,
    rig: path.relative(REPO, rigFile), foot_pose_source: fp.source, root_lift_m: fp.root_lift_m,
    extension_deg: Object.fromEntries(Object.entries(fp.bones ?? {}).map(([k, v]) => [k, r1(v.deg)])),
    floor_bind_y: floor, skin_crosscheck_m: worst, cap_loops: loops.map((l) => l.length),
    bind_joint_line_pitch_deg: { left: r1(bindPitch.left), right: r1(bindPitch.right) },
    body_cut_loops: cutLoops, bare: opts.bare ? path.relative(REPO, opts.bare) : null,
    bind_floor_raise_mm: bareProbe ? r1((floor - bareProbe.floor) * 1000) : null,
    groups, ground_offset_mm: Object.fromEntries(kinds.map((k) => [k, r1(ground[k] * 1000)])),
    chain_ms: chainMs, still: null, clips: {},
    boot: isBoot ? {
      sides: Object.fromEntries(Object.entries(boot).map(([side, b]) => [side, {
        band_top_bind_y: b.bandTop, shaft_top_bind_y: b.shaftTop, seam_pairs: b.pairs.length, ring: b.ringKind,
        ring_vertices: b.ring.length, poke_vertices: b.poke.length, thigh_vertices: b.thigh ? b.thigh.length : null,
        collar_loops: b.collar.length, open_loops_above_split: b.openLoops,
      }])),
      open_loops_above_split: Object.values(boot).reduce((a, b) => a + b.openLoops, 0),
    } : null,
  }
  console.log(`== ${path.basename(modelPath)}: ${total} verts (shoes ${shoeIdx.left.length}+${shoeIdx.right.length}), `
    + `foot pose ${fp.source.item_id}/${fp.source.fsig}${sourceNote}, lift ${(fp.root_lift_m * 1000).toFixed(1)} mm, `
    + `skin check ${worst.toExponential(2)} m, body boundary loops ${loops.length} [${loops.map((l) => l.length).join(' ')}], `
    + `client chain ${chainMs} ms, bind Foot→ToeBase line ${r1(bindPitch.left)}° / ${r1(bindPitch.right)}° (pitch 0)`)
  if (isBoot) {
    console.log(`  boot: ` + Object.entries(report.boot.sides).map(([side, b]) => `${side} band top ${r1(b.band_top_bind_y * 1000)} mm, `
      + `shaft top ${r1(b.shaft_top_bind_y * 1000)} mm, ${b.seam_pairs} seam pairs, ring ${b.ring ?? '—'} (${b.ring_vertices}), `
      + `${b.poke_vertices} shin / ${b.thigh_vertices ?? '—'} thigh vertices, ${b.collar_loops} collar loops`).join(' | ')
      + ` | open body loops above the split ${report.boot.open_loops_above_split}`)
  }
  if (bareProbe) {
    console.log(`  --bare ${path.basename(opts.bare)}: stance on its uncut feet; the served bind floor lies `
      + `${report.bind_floor_raise_mm} mm over the bare soles${cutLoops ? ` (body cut under the shoe: ${cutLoops} loops)` : ''}`)
  } else if (cutLoops) {
    console.log(`  NOTE the body is cut open under the shoe (${cutLoops} long boundary loops near the floor): the floor is `
      + "the cut body's lowest point and the bare stance is read on the cut foot — pass --bare BARE.glb")
  }

  // ---- the still pose (no clip)
  {
    const saved = new Map()
    fig.traverse((o) => { if (o.isBone) saved.set(o, o.quaternion.clone()) })
    applyFootPoseToPose(THREE, fig, fp)
    fig.position.y = footPoseLiftM(fp, 'ground')
    updateMats()
    const sole = Object.fromEntries(SIDES.map((s) => [s, r1(lowest(soleIdx[s]))]))
    const pen = penetration()
    const pitch = Object.fromEntries(SIDES.map((s) => [s, r1(footPitch(s))]))
    report.still = { sole_mm: sole, penetration: pen, pitch_deg: pitch }
    if (isBoot) {
      report.still.boot = bootFrame(false)
      console.log(`  still boot     ${bootLine(report.still.boot)}`)
    }
    console.log(`  still          sole L/R ${sole.left} / ${sole.right} mm | pitch L/R ${pitch.left}° / ${pitch.right}° `
      + `| penetration L/R ${pc(pen.left)} / ${pc(pen.right)}${pen.closed ? '' : ' !'}`)
    fig.traverse((o) => { if (saved.has(o)) o.quaternion.copy(saved.get(o)) })
    delete fig.userData.footPosed
    fig.position.y = 0
  }

  // ---- the clips
  const mixer = new THREE.AnimationMixer(fig)
  let playing = null
  const play = (clip, t, y) => {
    if (playing !== clip) {
      mixer.stopAllAction(); mixer.uncacheRoot(fig)
      mixer.clipAction(clip).play()
      playing = clip
    }
    mixer.setTime(t)
    fig.position.y = y
    updateMats()
  }
  const contacts = { left: [], right: [] }
  for (const k of kinds) {
    const group = groups[k]
    const n = Math.max(1, Math.round(shodClip[k].duration * FPS))
    const rows = []
    // two passes over the frames (bare, then shod): one action per pass, `setTime` per frame
    for (let f = 0; f < n; f++) {
      play(bareClip[k], f / FPS, 0)
      rows.push({ t: f / FPS,
        bare: bareProbe ? bareProbe.lowestAt(k, f / FPS) : Object.fromEntries(SIDES.map((s) => [s, lowest(footVerts[s])])),
        bare_pitch: Object.fromEntries(SIDES.map((s) => [s, footPitch(s)])),
        bare_hips: hipsBone ? hipsBone.getWorldPosition(new THREE.Vector3()).y : null })
    }
    for (let f = 0; f < n; f++) {
      play(shodClip[k], f / FPS, rootY(k))
      const row = rows[f]
      if (group === 'seat') {
        const kneeBefore = Object.fromEntries(SIDES.map((s) => [s, bones.get(`${s}leg`)?.getWorldPosition(new THREE.Vector3()).y ?? null]))
        const raise = seatFootLift(THREE, fig, fp, floor)
        updateMats()
        row.raise = Math.max(raise.left, raise.right) * 1000
        row.knee_rise = Math.max(...SIDES.map((s) => kneeBefore[s] === null ? 0
          : (bones.get(`${s}leg`).getWorldPosition(new THREE.Vector3()).y - kneeBefore[s]) * 1000))
      }
      row.shoe = Object.fromEntries(SIDES.map((s) => [s, lowest(soleIdx[s])]))
      row.pitch = Object.fromEntries(SIDES.map((s) => [s, footPitch(s)]))
      footContactsNow(THREE, fig, fp, contacts)
      row.contact = Math.min(...SIDES.flatMap((s) => contacts[s].map((v) => (v.y - floor) * 1000)))
      row.hips = hipsBone ? hipsBone.getWorldPosition(new THREE.Vector3()).y : null
      if (isBoot) row.boot = bootFrame(group === 'seat')
    }
    const out = { group, frames: n, duration_s: +shodClip[k].duration.toFixed(3), ground_offset_mm: r1(ground[k] * 1000),
      root_y_mm: r1(rootY(k) * 1000) }
    out.lower_sole_mm = stats(rows.map((r) => Math.min(r.shoe.left, r.shoe.right)))
    out.lower_bare_mm = stats(rows.map((r) => Math.min(r.bare.left, r.bare.right)))
    out.pitch_max_deg = Object.fromEntries(SIDES.map((s) => [s, r1(Math.max(...rows.map((r) => r.pitch[s])))]))
    out.bare_pitch_max_deg = Object.fromEntries(SIDES.map((s) => [s, r1(Math.max(...rows.map((r) => r.bare_pitch[s])))]))
    if (group === 'ground') {
      out.stance = {}
      for (const s of SIDES) {
        const st = rows.map((r) => r.bare[s] <= STANCE_MM)
        // runs of stance frames on the loop (a run may wrap over the clip end)
        let start = 0
        while (start < n && st[start]) start++
        if (start === n) start = 0
        const runs = []
        let cur = null
        for (let j = 0; j < n; j++) {
          const i = (start + j) % n
          if (st[i]) { if (!cur) cur = []; cur.push(i) } else if (cur) { runs.push(cur); cur = null }
        }
        if (cur) runs.push(cur)
        out.stance[s] = {
          frames: st.filter(Boolean).length,
          sole_mm: stats(rows.filter((_, i) => st[i]).map((r) => r.shoe[s])),
          runs: runs.map((run) => ({ frames: run.length, t0: +rows[run[0]].t.toFixed(3),
            strike: run.slice(0, 3).map((i) => r1(rows[i].shoe[s])), off: run.slice(-3).map((i) => r1(rows[i].shoe[s])) })),
        }
      }
      out.stance_sole_mm = stats(SIDES.flatMap((s) => rows.filter((r) => r.bare[s] <= STANCE_MM).map((r) => r.shoe[s])))
    } else {
      out.lowest_contact_mm = stats(rows.map((r) => r.contact))
      out.hips_delta_mm = hipsBone ? r1(Math.max(...rows.map((r) => Math.abs(r.hips - r.bare_hips))) * 1000) : null
      if (group === 'seat') {
        out.seat_floor_mm = out.lowest_contact_mm
        out.ankle_raise_max_mm = r1(Math.max(...rows.map((r) => r.raise)))
        out.knee_rise_max_mm = r1(Math.max(...rows.map((r) => r.knee_rise)))
      }
    }
    // penetration at --samples times
    out.penetration = []
    for (let s = 0; s < opts.samples; s++) {
      const t = (s / opts.samples) * shodClip[k].duration
      play(shodClip[k], t, rootY(k))
      const pen = penetration()
      out.penetration.push({ t: +t.toFixed(3), left: pen.left, right: pen.right, closed: pen.closed })
    }
    out.penetration_max = { left: Math.max(...out.penetration.map((p) => p.left)),
      right: Math.max(...out.penetration.map((p) => p.right)) }
    out.per_frame = rows.map((r) => ({ t: +r.t.toFixed(3), shoe_L: r1(r.shoe.left), shoe_R: r1(r.shoe.right),
      bare_L: r1(r.bare.left), bare_R: r1(r.bare.right), pitch_L: r1(r.pitch.left), pitch_R: r1(r.pitch.right),
      contact: r1(r.contact), ...(r.boot ? { boot: r.boot } : {}) }))
    if (isBoot) {
      // the worse frame per side and measure (null when a measure has no value in any frame)
      const worst = (key) => Object.fromEntries(Object.keys(boot).map((side) => {
        const vals = rows.map((r) => r.boot[side][key]).filter((v) => v !== null && v !== undefined)
        return [side, vals.length ? Math.max(...vals) : null]
      }))
      out.boot = { seam_gap_mm: worst('seam_gap_mm'), shaft_leg_follow_deg: worst('shaft_leg_follow_deg'),
        shaft_poke: worst('shaft_poke'), ...(group === 'seat' ? { seat_thigh_in_shaft: worst('seat_thigh_in_shaft') } : {}) }
    }
    report.clips[k] = out

    const g = r1(ground[k] * 1000)
    const head = `  ${k.padEnd(6)} ${group.padEnd(6)} ${n} fr`
    if (group === 'ground') {
      const act = out.lower_sole_mm ? `${r1(out.lower_sole_mm.min + g)} … ${r1(out.lower_sole_mm.max + g)}` : '—'
      console.log(`${head} | lower sole ${span(out.lower_sole_mm)} mm (activity clip, ground ${g} mm not applied: ${act}) `
        + `| bare ${span(out.lower_bare_mm)}`)
      console.log(`  ${''.padEnd(22)}stance sole ${span(out.stance_sole_mm)} mm `
        + SIDES.map((s) => `${s[0].toUpperCase()} ${span(out.stance[s].sole_mm)} over ${out.stance[s].frames}`).join(', '))
      for (const s of SIDES) {
        for (const run of out.stance[s].runs) {
          console.log(`  ${''.padEnd(22)}${s} run @${run.t0}s ${run.frames} fr: strike ${run.strike.join(' ')} | off ${run.off.join(' ')}`)
        }
      }
    } else {
      console.log(`${head} | lowest shoe ${span(out.lower_sole_mm)} mm | lowest contact ${span(out.lowest_contact_mm)} mm `
        + `| hips shod − bare max ${out.hips_delta_mm} mm | bare ${span(out.lower_bare_mm)}`
        + (group === 'seat' ? ` | seat floor ${span(out.seat_floor_mm)} mm, ankle raise max ${out.ankle_raise_max_mm} mm, knee rise max ${out.knee_rise_max_mm} mm` : ''))
    }
    console.log(`  ${''.padEnd(22)}Foot pitch max L/R ${out.pitch_max_deg.left}° / ${out.pitch_max_deg.right}° `
      + `(bare ${out.bare_pitch_max_deg.left}° / ${out.bare_pitch_max_deg.right}°) `
      + `| penetration L ${out.penetration.map((p) => pc(p.left) + (p.closed ? '' : '!')).join(' ')} `
      + `R ${out.penetration.map((p) => pc(p.right) + (p.closed ? '' : '!')).join(' ')}`)
    if (isBoot) console.log(`  ${''.padEnd(22)}boot max over ${n} fr: ${bootLine(Object.fromEntries(Object.keys(boot).map((side) => [side,
      Object.fromEntries(Object.entries(out.boot).map(([key, v]) => [key, v[side]]))])))}`)
  }
  if (opts.json) fs.writeFileSync(opts.json, JSON.stringify(report, null, 1))

  /** One printed line of boot measures ({side: {…}}): seam gap, follow, poke, thigh (seat). */
  function bootLine(m) {
    const f = (v, d = 3) => (v === null || v === undefined ? '—' : (+v).toFixed(d))
    return Object.entries(m).map(([side, b]) => `${side[0].toUpperCase()} seam gap ${f(b.seam_gap_mm, 4)} mm, `
      + `leg follow ${f(b.shaft_leg_follow_deg, 2)}°, poke ${b.shaft_poke === null ? '—' : pc(b.shaft_poke)}`
      + (b.seat_thigh_in_shaft !== undefined && b.seat_thigh_in_shaft !== null ? `, thigh in shaft ${pc(b.seat_thigh_in_shaft)}` : '')).join(' | ')
  }
}

main().catch((e) => { console.error(e); process.exit(1) })
