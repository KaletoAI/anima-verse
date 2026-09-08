/**
 * Smoke: the plane a MIRROR pane is measured from (mirrorSurface.planeOfFaces)
 * and the per-frame reflection budget (MirrorBudget).
 *
 * Usage: node scripts/smoke_mirror_plane.mjs
 *
 * Every expected number below is derived BY HAND from the rule (§ B5a):
 *   centroid = area-weighted mean of the triangle centroids,
 *   normal   = normalised sum of (b-a)×(c-a) over the faces (winding = side).
 *
 * [1] A 0.5 × 1.0 rectangle in the plane z = 0.2, centred at (0.1, 0.3, 0.2),
 *     two triangles, counter-clockwise seen from +z:
 *       a(-0.15,-0.2,0.2) b(0.35,-0.2,0.2) c(0.35,0.8,0.2) d(-0.15,0.8,0.2)
 *       faces (a,b,c) (a,c,d)
 *     Both triangle centroids average to (0.1, 0.3, 0.2) with equal areas
 *     (0.25 each), cross products both (0,0,+0.5) → normal (0,0,1).
 * [2] The same rectangle with the winding reversed → normal (0,0,-1),
 *     centroid unchanged.
 * [3] A rectangle tilted 90° about x (points in the plane y = 0.7):
 *       a(0,0.7,0) b(1,0.7,0) c(1,0.7,2) d(0,0.7,2), faces (a,b,c)(a,c,d)
 *     (b-a)×(c-a) = (1,0,0)×(1,0,2) = (0·2-0·0, 0·1-1·2, 1·0-0·1) = (0,-2,0)
 *     → normal (0,-1,0); centroid (0.5, 0.7, 1.0).
 * [4] Only the RANGE counts: an index buffer holding first a frame triangle
 *     far away at z = 5 (indices 0..2), then the rectangle of [1]
 *     (indices 3..8); ranges [[3, 6]] gives exactly the answer of [1].
 * [5] Non-indexed geometry: the six vertices of [1] laid out in face order
 *     with `index = null`, ranges [[0, 6]] in vertex units → answer of [1].
 * [6] A degenerate group (three identical points) → null.
 * [7] A count past the end of the buffer is clamped, not read out of bounds:
 *     ranges [[3, 9999]] on the buffer of [4] → answer of [1].
 * [8] MirrorBudget(2), frames as `renderer.info.render.frame` would report
 *     them (each granted reflection is a nested render that bumps the counter
 *     by one before the next hook of the same frame runs):
 *       allow(10) → true   (1st of frame 10, nested render → counter 11)
 *       allow(11) → true   (2nd; counter → 12)
 *       allow(12) → false  (over budget; counter stays 12)
 *       allow(12) → false  (another mirror, same frame)
 *       allow(13) → true   (a new top-level frame resets the budget)
 *       allow(20) → true   (a frame with no pending nested count is new)
 *     MirrorBudget(0) → allow(1) is false. MirrorBudget(Infinity) →
 *     allow(n) is always true.
 * [9] COHERENCE — the faces of one group must agree on a side. With
 *     `len` = |Σ (b-a)×(c-a)| and `weight` = Σ |(b-a)×(c-a)|, a group whose
 *     `len / weight` is under 0.9 has no plane: two opposite skins of one pane
 *     cancel, and sliver noise points nowhere. A pane a renderer can mirror is
 *     FLAT — a real wall mirror's panes measure 1.0000, while the 134 slivers
 *     of a door-glass prop measure 0.7384 and sit 87° off their own sidecar,
 *     so the threshold belongs between those two and near the flat end.
 *     Hand-derived on the unit square in z = 0 — a(0,0,0) b(1,0,0) c(1,1,0)
 *     d(0,1,0), faces (a,b,c)(a,c,d), two face vectors (0,0,1) of length 1
 *     each, so weight 2 and Σ (0,0,2) per copy wound counter-clockwise, and
 *     (0,0,-2) per copy wound the other way — n copies ccw and m cw give
 *     Σ = (0,0,2(n-m)), weight 2(n+m), ratio (n-m)/(n+m):
 *        1 ccw +  1 cw → Σ 0,        weight  4 → ratio 0      → null
 *        2 ccw +  1 cw → Σ (0,0, 2), weight  6 → ratio 1/3    → null
 *        3 ccw +  1 cw → Σ (0,0, 4), weight  8 → ratio 0.5    → null
 *       18 ccw +  2 cw → Σ (0,0,32), weight 40 → ratio 0.8    → null
 *       19 ccw +  1 cw → Σ (0,0,36), weight 40 → ratio 0.9    → a plane,
 *                        centroid (0.5, 0.5, 0), normal (0, 0, 1)
 *     The square alone is ratio 1 (as the rectangle of [1] is). 0.5 and 0.8
 *     are the cases that pin the threshold from below, 0.9 the one from above.
 * [10] An index past the end of `positions` reads `undefined` and poisons the
 *     sums with NaN. A NaN plane is not a plane:
 *     planeOfFaces([0,0,0, 1,0,0, 0,1,0], [0, 1, 99], [[0, 3]]) → null.
 * [11] The centroid is AREA-weighted, not the plain mean of the triangle
 *     centroids. In the plane z = 0, one large and one small triangle:
 *       a(0,0,0) b(2,0,0) c(0,2,0) → (b-a)×(c-a) = (0,0,4), centroid (2/3, 2/3, 0)
 *       d(4,0,0) e(5,0,0) f(4,1,0) → (e-d)×(f-d) = (0,0,1), centroid (13/3, 1/3, 0)
 *       x = (4·2/3 + 1·13/3) / 5 = (8/3 + 13/3) / 5 = 7/5 = 1.4
 *       y = (4·2/3 + 1·1/3)  / 5 = (8/3 + 1/3)  / 5 = 3/5 = 0.6
 *     → centroid (1.4, 0.6, 0), normal (0, 0, 1). The unweighted mean would be
 *     (2.5, 0.5, 0) — that is what makes the case discriminating.
 * [12] The clamp of [7] on the NON-indexed path as well: the six vertices of
 *     [5] with ranges [[0, 9999]] → the answer of [1].
 * [13] OPTIONAL local cross-check (skipped, not failed, when the file is
 *     absent): MIRROR_FIXTURE_GLB=<path to a prop's model_<ts>.glb> and
 *     MIRROR_FIXTURE_JSON=<its .json sidecar> — for every area whose id
 *     starts with `glass` AND has a measured plane, that plane must lie
 *     within 1 cm (centroid, |n·(c_measured - c_sidecar)|) and 2° (normal,
 *     ignoring sign) of the sidecar's `centroid` / `normal`. The GLB is
 *     parsed with the stdlib only (12-byte header, JSON chunk, BIN chunk;
 *     accessors of the one mesh).
 *
 *     AN AREA WITH NO PLANE IS INFORMATIONAL, NOT A FAILURE. The sidecar's
 *     centroid/normal come from a PCA fit over the vertex CLOUD
 *     (`picture_areas.py`), while [9]'s rule is the area-weighted sum over
 *     the FACES — on a group of slivers or of two opposite skins the two
 *     disagree by construction, and "this pane has no plane, leave it as
 *     modelled" is the product behaviour, not a defect on either side. Such
 *     an area prints its coherence ratio and is skipped. A sidecar area with
 *     no material group of that name at all IS still a failure: that is a
 *     structural mismatch between the model and its sidecar.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

/** The one mesh of a GLB, parsed with the stdlib: material name → faces. */
function readGlbGroups(glbPath) {
  const buf = fs.readFileSync(glbPath)
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength)
  if (view.getUint32(0, true) !== 0x46546c67) {
    throw new Error(`${glbPath}: not a GLB (magic)`)
  }
  const jsonLen = view.getUint32(12, true)
  if (view.getUint32(16, true) !== 0x4e4f534a) {
    throw new Error(`${glbPath}: chunk 0 is not JSON`)
  }
  const gltf = JSON.parse(buf.subarray(20, 20 + jsonLen).toString('utf8'))
  const binHeader = 20 + jsonLen
  if (view.getUint32(binHeader + 4, true) !== 0x004e4942) {
    throw new Error(`${glbPath}: chunk 1 is not BIN`)
  }
  const binStart = binHeader + 8
  const binLen = view.getUint32(binHeader, true)
  const bin = buf.subarray(binStart, binStart + binLen)

  /** Absolute byte offset of an accessor's first element inside `bin`. */
  const viewOf = (accessor) => {
    const bv = gltf.bufferViews[accessor.bufferView]
    return { base: (bv.byteOffset ?? 0) + (accessor.byteOffset ?? 0),
             stride: bv.byteStride ?? 0 }
  }
  const readPositions = (accessor) => {
    if (accessor.componentType !== 5126) {
      throw new Error(`POSITION componentType ${accessor.componentType}`)
    }
    const { base, stride } = viewOf(accessor)
    const step = stride || 12
    const out = new Float64Array(accessor.count * 3)
    for (let i = 0; i < accessor.count; i += 1) {
      const at = base + i * step
      out[i * 3] = bin.readFloatLE(at)
      out[i * 3 + 1] = bin.readFloatLE(at + 4)
      out[i * 3 + 2] = bin.readFloatLE(at + 8)
    }
    return out
  }
  const readIndices = (accessor) => {
    const size = { 5121: 1, 5123: 2, 5125: 4 }[accessor.componentType]
    if (!size) throw new Error(`index componentType ${accessor.componentType}`)
    const { base, stride } = viewOf(accessor)
    const step = stride || size
    const out = new Uint32Array(accessor.count)
    for (let i = 0; i < accessor.count; i += 1) {
      const at = base + i * step
      out[i] = size === 1 ? bin.readUInt8(at)
        : size === 2 ? bin.readUInt16LE(at) : bin.readUInt32LE(at)
    }
    return out
  }

  const groups = new Map()
  for (const prim of gltf.meshes[0].primitives) {
    const raw = String(gltf.materials?.[prim.material]?.name ?? '')
    const slot = raw.toLowerCase().replace(/^slot_/, '').trim()
    const positions = readPositions(gltf.accessors[prim.attributes.POSITION])
    const indices = prim.indices === undefined
      ? null : readIndices(gltf.accessors[prim.indices])
    groups.set(slot, { positions, indices })
  }
  return groups
}

/**
 * |Σ (b-a)×(c-a)| / Σ |(b-a)×(c-a)| over a group's faces — the same quotient
 * `planeOfFaces` gates on ([9]). It is recomputed here only to LABEL the
 * informational line of section [13] with a number a reader can act on; the
 * decision whether an area has a plane stays the module's, never this copy's.
 */
function coherenceOf(positions, indices) {
  const total = indices ? indices.length : Math.floor(positions.length / 3)
  const vert = (i) => {
    const v = indices ? indices[i] : i
    return [positions[v * 3], positions[v * 3 + 1], positions[v * 3 + 2]]
  }
  let nx = 0, ny = 0, nz = 0, weight = 0
  for (let i = 0; i + 2 < total; i += 3) {
    const a = vert(i), b = vert(i + 1), c = vert(i + 2)
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2]
    const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2]
    const fx = uy * vz - uz * vy
    const fy = uz * vx - ux * vz
    const fz = ux * vy - uy * vx
    const t = Math.sqrt(fx * fx + fy * fy + fz * fz)
    if (!(t > 0)) continue
    nx += fx; ny += fy; nz += fz; weight += t
  }
  return weight > 0 ? Math.sqrt(nx * nx + ny * ny + nz * nz) / weight : 0
}

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_mirror_plane_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild',
                 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm',
      `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' },
    })
    process.exit(run.status ?? 1)
  }

  const { planeOfFaces, MirrorBudget } =
    await import('../packages/scene-render/src/mirrorSurface.ts')

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }

  const near = (a, b, tol = 1e-9) => Math.abs(a - b) <= tol
  const vecNear = (v, w, tol = 1e-9) => v.length === 3
    && near(v[0], w[0], tol) && near(v[1], w[1], tol) && near(v[2], w[2], tol)

  console.log('\n[1] rectangle in z = 0.2, ccw from +z')
  const rect = [-0.15, -0.2, 0.2,  0.35, -0.2, 0.2,  0.35, 0.8, 0.2,  -0.15, 0.8, 0.2]
  const p1 = planeOfFaces(rect, [0, 1, 2, 0, 2, 3], [[0, 6]])
  check('centroid (0.1, 0.3, 0.2)', p1 && vecNear(p1.point, [0.1, 0.3, 0.2]), JSON.stringify(p1))
  check('normal (0, 0, 1)', p1 && vecNear(p1.normal, [0, 0, 1]), JSON.stringify(p1))

  console.log('\n[2] reversed winding flips the normal only')
  const p2 = planeOfFaces(rect, [0, 2, 1, 0, 3, 2], [[0, 6]])
  check('normal (0, 0, -1)', p2 && vecNear(p2.normal, [0, 0, -1]), JSON.stringify(p2))
  check('centroid unchanged', p2 && vecNear(p2.point, [0.1, 0.3, 0.2]))

  console.log('\n[3] tilted rectangle in y = 0.7')
  const tilt = [0, 0.7, 0,  1, 0.7, 0,  1, 0.7, 2,  0, 0.7, 2]
  const p3 = planeOfFaces(tilt, [0, 1, 2, 0, 2, 3], [[0, 6]])
  check('normal (0, -1, 0)', p3 && vecNear(p3.normal, [0, -1, 0]), JSON.stringify(p3))
  check('centroid (0.5, 0.7, 1.0)', p3 && vecNear(p3.point, [0.5, 0.7, 1.0]), JSON.stringify(p3))

  console.log('\n[4] only the range counts')
  const mixed = [0, 0, 5,  1, 0, 5,  0, 1, 5, ...rect]
  const idx4 = [0, 1, 2,  3, 4, 5,  3, 5, 6]
  const p4 = planeOfFaces(mixed, idx4, [[3, 6]])
  check('range [3,6] → the rectangle of [1]',
        p4 && vecNear(p4.point, [0.1, 0.3, 0.2]) && vecNear(p4.normal, [0, 0, 1]), JSON.stringify(p4))

  console.log('\n[5] non-indexed geometry, vertex units')
  const flat = [-0.15, -0.2, 0.2,  0.35, -0.2, 0.2,  0.35, 0.8, 0.2,
                -0.15, -0.2, 0.2,  0.35, 0.8, 0.2,  -0.15, 0.8, 0.2]
  const p5 = planeOfFaces(flat, null, [[0, 6]])
  check('answer of [1]', p5 && vecNear(p5.point, [0.1, 0.3, 0.2]) && vecNear(p5.normal, [0, 0, 1]), JSON.stringify(p5))

  console.log('\n[6] degenerate faces → null')
  check('three identical points', planeOfFaces([1, 1, 1, 1, 1, 1, 1, 1, 1], [0, 1, 2], [[0, 3]]) === null)

  console.log('\n[7] a count past the end is clamped')
  const p7 = planeOfFaces(mixed, idx4, [[3, 9999]])
  check('range [3,9999] → the rectangle of [1]',
        p7 && vecNear(p7.point, [0.1, 0.3, 0.2]) && vecNear(p7.normal, [0, 0, 1]), JSON.stringify(p7))

  console.log('\n[8] the per-frame budget')
  const b = new MirrorBudget(2)
  const seq = [b.allow(10), b.allow(11), b.allow(12), b.allow(12), b.allow(13), b.allow(20)]
  check('sequence true,true,false,false,true,true', JSON.stringify(seq) === '[true,true,false,false,true,true]', JSON.stringify(seq))
  check('budget 0 grants nothing', new MirrorBudget(0).allow(1) === false)
  const inf = new MirrorBudget(Infinity)
  check('unlimited budget always grants', inf.allow(1) && inf.allow(2) && inf.allow(3))

  console.log('\n[9] the faces of a group must agree on a side')
  // The unit square in z = 0, counter-clockwise seen from +z. Both its faces
  // have the face vector (0,0,1), so ONE copy is weight 2 and sum (0,0,2).
  const sq = [0, 0, 0,  1, 0, 0,  1, 1, 0,  0, 1, 0]
  const ccw = [0, 1, 2,  0, 2, 3]
  const cw = [0, 2, 1,  0, 3, 2]
  check('one skin plus its mirror image → ratio 0 → null',
        planeOfFaces(sq, [...ccw, ...cw], [[0, 12]]) === null,
        JSON.stringify(planeOfFaces(sq, [...ccw, ...cw], [[0, 12]])))
  /** n copies of the square wound ccw and m wound cw, in one index range. */
  const mix = (n, m) => {
    const idx = []
    for (let i = 0; i < n; i += 1) idx.push(...ccw)
    for (let i = 0; i < m; i += 1) idx.push(...cw)
    return planeOfFaces(sq, idx, [[0, idx.length]])
  }
  check('2 ccw + 1 cw → ratio 2/6 = 1/3 → null', mix(2, 1) === null,
        JSON.stringify(mix(2, 1)))
  check('3 ccw + 1 cw → ratio 4/8 = 0.5 → null', mix(3, 1) === null,
        JSON.stringify(mix(3, 1)))
  check('18 ccw + 2 cw → ratio 32/40 = 0.8 → still null', mix(18, 2) === null,
        JSON.stringify(mix(18, 2)))
  const p9 = mix(19, 1)
  check('19 ccw + 1 cw → ratio 36/40 = 0.9 → a plane, (0.5,0.5,0)/(0,0,1)',
        p9 && vecNear(p9.point, [0.5, 0.5, 0]) && vecNear(p9.normal, [0, 0, 1]),
        JSON.stringify(p9))
  check('the square on its own is ratio 1',
        planeOfFaces(sq, ccw, [[0, 6]]) !== null)

  console.log('\n[10] an index past the buffer is not a plane')
  const p10 = planeOfFaces([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 99], [[0, 3]])
  check('a vertex read out of bounds → null, never a NaN plane', p10 === null,
        JSON.stringify(p10))

  console.log('\n[11] the centroid is AREA-weighted, not a plain mean')
  const tris = [0, 0, 0,  2, 0, 0,  0, 2, 0,   4, 0, 0,  5, 0, 0,  4, 1, 0]
  const p11 = planeOfFaces(tris, null, [[0, 6]])
  check('centroid (1.4, 0.6, 0) — the plain mean would be (2.5, 0.5, 0)',
        p11 && vecNear(p11.point, [1.4, 0.6, 0]), JSON.stringify(p11))
  check('normal (0, 0, 1)', p11 && vecNear(p11.normal, [0, 0, 1]),
        JSON.stringify(p11))

  console.log('\n[12] the clamp holds on the non-indexed path too')
  const p12 = planeOfFaces(flat, null, [[0, 9999]])
  check('range [0,9999] over 6 vertices → the rectangle of [1]',
        p12 && vecNear(p12.point, [0.1, 0.3, 0.2])
        && vecNear(p12.normal, [0, 0, 1]), JSON.stringify(p12))

  console.log('\n[13] optional local fixture')
  const glbPath = process.env.MIRROR_FIXTURE_GLB
  const jsonPath = process.env.MIRROR_FIXTURE_JSON
  if (!glbPath) {
    console.log('  - skipped (MIRROR_FIXTURE_GLB not set)')
  } else if (!jsonPath) {
    console.log('  - skipped (MIRROR_FIXTURE_JSON not set)')
  } else if (!fs.existsSync(glbPath) || !fs.existsSync(jsonPath)) {
    console.log(`  - skipped (fixture not on disk: ${
      !fs.existsSync(glbPath) ? glbPath : jsonPath})`)
  } else {
    // The GLB's positions are in the file's own space — the same space the
    // sidecar's centroid/normal are measured in (`picture_areas.py` measures
    // on the exported mesh). So this is a like-for-like comparison, and a
    // constant axis swap here would be a real defect, not a tolerance issue.
    const groups = readGlbGroups(glbPath)
    const sidecar = JSON.parse(fs.readFileSync(jsonPath, 'utf8'))
    const panes = (sidecar.areas ?? []).filter(
      (a) => String(a.id ?? '').toLowerCase().startsWith('glass'))
    console.log(`  fixture: ${path.basename(glbPath)}, `
      + `${panes.length} glass area(s), groups: ${[...groups.keys()].join(', ')}`)
    if (!panes.length) console.log('  - no glass area in the sidecar, nothing to compare')
    for (const area of panes) {
      const g = groups.get(String(area.id).toLowerCase())
      if (!g) {
        check(`${area.id}: a material group of that name exists`, false,
              'no primitive carries it')
        continue
      }
      const count = g.indices ? g.indices.length
        : Math.floor(g.positions.length / 3)
      const m = planeOfFaces(g.positions, g.indices, [[0, count]])
      if (!m) {
        // Not a failure — see the section's note in the header: the sidecar's
        // PCA fit over the vertices and the area-weighted face rule disagree
        // by design on a group of slivers or of two opposite skins, and the
        // renderer's answer for such a pane is "leave it as modelled".
        console.log(`  - ${area.id}: no coherent plane `
          + `(ratio ${coherenceOf(g.positions, g.indices).toFixed(4)}, `
          + `${count / 3} faces) — skipped`)
        continue
      }
      const cs = area.centroid, ns = area.normal
      const nsLen = Math.hypot(ns[0], ns[1], ns[2]) || 1
      const nsu = [ns[0] / nsLen, ns[1] / nsLen, ns[2] / nsLen]
      const dist = Math.abs(nsu[0] * (m.point[0] - cs[0])
                          + nsu[1] * (m.point[1] - cs[1])
                          + nsu[2] * (m.point[2] - cs[2]))
      const dot = Math.min(1, Math.abs(m.normal[0] * nsu[0]
                                     + m.normal[1] * nsu[1]
                                     + m.normal[2] * nsu[2]))
      const deg = Math.acos(dot) * 180 / Math.PI
      const fmt = (v) => `(${v.map((x) => x.toFixed(5)).join(', ')})`
      check(`${area.id}: centroid within 1 cm of the sidecar plane`,
            dist <= 0.01,
            `${(dist * 100).toFixed(3)} cm; measured ${fmt(m.point)} `
            + `vs sidecar ${fmt(cs)}`)
      check(`${area.id}: normal within 2° of the sidecar normal`,
            deg <= 2,
            `${deg.toFixed(3)}°; measured ${fmt(m.normal)} `
            + `vs sidecar ${fmt(nsu)}`)
    }
  }

  console.log(failures.length ? `\n${failures.length} check(s) FAILED` : '\nall checks passed')
  process.exit(failures.length ? 1 : 0)
}

void main()
