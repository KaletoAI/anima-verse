/**
 * Smoke: a floor plate with a HOLE in it — the opening a staircase cuts into
 * the floor it arrives on (`plates[].holes`, contract addendum "Treppen v2").
 *
 * Usage (the package is TypeScript, so it is bundled first; esbuild lives in
 * the client3d workspace, three has to resolve from a path inside it — hence
 * the bundle step rather than a bare `node`):
 *     client3d/node_modules/.bin/esbuild client3d/scripts/smoke_plate_hole.mjs \
 *         --bundle --platform=node --format=esm --outfile=/tmp/ph.mjs \
 *         && node /tmp/ph.mjs
 *
 * Runs headless against the SHARED `buildPlate` — the one routine both
 * renderers build a floor with — using the real three from node_modules, so
 * what is measured is the geometry that actually ships.
 *
 * WHY IT EXISTS. Before v2 a `ScenePlate` was a single ring, and the floor of
 * the storey a flight arrives on was closed: the stairs ended under a lid.
 * The server now states the opening, and both renderers have to take it out of
 * the shape. Two things can go wrong and neither shows up in a bounding box:
 * the hole is dropped (the lid is back), or it is placed with the WRONG SIGN
 * on its second coordinate — `buildPlate` mirrors z for the flat plate variant
 * (`sy = −pz`) and must mirror the hole with it, or the opening lands in the
 * other half of the room.
 *
 * ============================================================================
 * THE FIXTURE, and every expected number derived from it BY HAND
 * ============================================================================
 * Outline (local metres, x/z, straddling z = 0 on purpose — a sign error is
 * invisible on a plate that lies entirely on one side of the pin):
 *
 *     [[0, −3], [8, −3], [8, 3], [0, 3]]        8 × 6 m  =  48 m²
 *
 * Hole, deliberately NOT symmetric about z = 0:
 *
 *     [[2, 0.5], [5, 0.5], [5, 2.5], [2, 2.5]]  3 × 2 m  =   6 m²
 *
 *   A. Top-face area with the hole:      48 − 6      = 42 m²
 *      Top-face area without it:                       48 m²
 *   B. Triangle count of the top face. A simple polygon with n vertices and
 *      h holes triangulates into n + 2h − 2 triangles (the two bridge edges
 *      per hole add one vertex each to the ring):
 *        no hole:  n = 4, h = 0  ->  4 + 0 − 2 =  2 triangles
 *        one hole: n = 8, h = 1  ->  8 + 2 − 2 =  8 triangles
 *   C. Coverage in WORLD xz. The hole's centre is (3.5, 1.5); its MIRROR
 *      about z = 0 is (3.5, −1.5), which lies inside the outline as well —
 *      that pair is the sign probe:
 *        (3.5,  1.5)  covered by NO top-face triangle   (the opening)
 *        (3.5, −1.5)  covered by exactly ONE            (the red probe)
 *        (1.0,  1.5) / (6.5, 1.5) / (3.5, 2.9) / (3.5, 0.1)  covered
 *          (west, east, north and south of the opening, all still floor)
 *   D. The bounding box is the OUTLINE's, hole or no hole (`plateTargets`
 *      stays as it is): x 0…8, z −3…3, top face on `top_y`, and for a body
 *      the bottom face one `thickness` below it.
 *        solid: top_y 3.08, thickness 0.10  ->  y 2.98 … 3.08
 *        flat:  top_y 0.00, thickness 0     ->  y 0.00 … 0.00
 *   E. The extrusion CAPS THE OPENING. Side triangles (the ones spanning both
 *      y levels) are 2 per ring edge: 4 edges outer = 8 without a hole, plus
 *      4 edges of the hole = 16 with one.
 *
 * Both plate kinds are measured with the same numbers, because the two
 * branches of `buildPlate` differ only in how they get there:
 *   solid  shape (x, z),  extruded downward, rotated +90° about x
 *   flat   shape (x, −z), a bare ShapeGeometry, rotated −90° about x
 * Both must put the point (px, pz) of the payload at world (px, ·, pz).
 */
import * as THREE from 'three'
// '../../' = the repo root: this file lives in client3d/scripts/, the shared
// package at packages/scene-render. esbuild resolves it relative to THIS file.
import { buildPlate, plateTargets } from '../../packages/scene-render/src/primitives.ts'

const FAILED = []

function check(label, got, want, tol = 1e-6) {
  const ok = Array.isArray(want)
    ? Array.isArray(got) && got.length === want.length
      && got.every((v, i) => Math.abs(v - want[i]) <= tol)
    : typeof want === 'boolean' || typeof want === 'string'
      ? got === want
      : Math.abs(got - want) <= tol
  const show = Array.isArray(got) ? `[${got.map((v) => fmt(v)).join(', ')}]` : fmt(got)
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: ${show}`
    + (ok ? '' : `  (expected ${Array.isArray(want) ? `[${want.join(', ')}]` : want})`))
  if (!ok) FAILED.push(label)
}

const fmt = (v) => (typeof v === 'number' ? v.toFixed(4) : String(v))

const OUTLINE = [[0, -3], [8, -3], [8, 3], [0, 3]]
const HOLE = [[2, 0.5], [5, 0.5], [5, 2.5], [2, 2.5]]

/** The plate as the payload states it. */
const plate = (holes, thickness, topY) => ({
  level: 1, outline: OUTLINE, holes, top_y: topY, thickness,
  opacity_role: 'upper', room_id: 'hall',
})

/** Every triangle of a built mesh in WORLD coordinates. */
function triangles(mesh) {
  mesh.updateMatrixWorld(true)
  const geo = mesh.geometry
  const pos = geo.getAttribute('position')
  const index = geo.getIndex()
  const count = index ? index.count : pos.count
  const out = []
  for (let i = 0; i < count; i += 3) {
    const tri = []
    for (let k = 0; k < 3; k++) {
      const j = index ? index.getX(i + k) : i + k
      tri.push(new THREE.Vector3(pos.getX(j), pos.getY(j), pos.getZ(j))
        .applyMatrix4(mesh.matrixWorld))
    }
    out.push(tri)
  }
  return out
}

/** The triangles of the TOP FACE — all three corners on `top_y`. On a flat
 *  plate that is every triangle; on a body it separates the cap from the
 *  bottom and from the walls of the opening. */
const topFace = (tris, topY) =>
  tris.filter((t) => t.every((p) => Math.abs(p.y - topY) < 1e-6))

/** Triangles that span BOTH y levels — the extruded walls, the outer ring's
 *  and the hole's. */
const sideFaces = (tris, topY, bottomY) =>
  tris.filter((t) => t.some((p) => Math.abs(p.y - topY) < 1e-6)
    && t.some((p) => Math.abs(p.y - bottomY) < 1e-6))

/** Area of a triangle PROJECTED onto the xz plane. */
const areaXZ = ([a, b, c]) => Math.abs(
  (b.x - a.x) * (c.z - a.z) - (c.x - a.x) * (b.z - a.z)) / 2

/** Is the point inside the triangle, seen from above? Barycentric signs; a
 *  point on an edge counts as inside for both neighbours, which is why the
 *  probe points below sit well clear of every edge. */
function insideXZ([a, b, c], x, z) {
  const d = (p, q) => (q.x - p.x) * (z - p.z) - (x - p.x) * (q.z - p.z)
  const s1 = d(a, b)
  const s2 = d(b, c)
  const s3 = d(c, a)
  const neg = s1 < -1e-12 || s2 < -1e-12 || s3 < -1e-12
  const pos = s1 > 1e-12 || s2 > 1e-12 || s3 > 1e-12
  return !(neg && pos)
}

const covers = (tris, x, z) => tris.filter((t) => insideXZ(t, x, z)).length

const MAT = new THREE.MeshBasicMaterial()

function measure(label, spec) {
  const mesh = buildPlate(THREE, spec, MAT)
  const tris = triangles(mesh)
  const top = topFace(tris, spec.top_y)
  console.log(`\n${label}`)
  return { mesh, tris, top }
}

// ── 1. A BODY with a hole (the storey plate a flight arrives on) ───────────
{
  const spec = plate([HOLE], 0.10, 3.08)
  const { mesh, tris, top } = measure(
    '1. solid plate 8 × 6 m, thickness 0.10, top 3.08, one 3 × 2 m opening', spec)
  check('A the top face measures 48 − 6 m²',
    top.reduce((s, t) => s + areaXZ(t), 0), 42)
  check('B ...as 8 triangles (n + 2h − 2, n = 8, h = 1)', top.length, 8)
  check('C the opening is open — nothing covers its centre (3.5, 1.5)',
    covers(top, 3.5, 1.5), 0)
  check('C red: the MIRRORED point (3.5, −1.5) is floor — the hole did not '
    + 'flip sign', covers(top, 3.5, -1.5), 1)
  check('C west of it (1.0, 1.5) is floor', covers(top, 1.0, 1.5), 1)
  check('C east of it (6.5, 1.5) is floor', covers(top, 6.5, 1.5), 1)
  check('C north of it (3.5, 2.9) is floor', covers(top, 3.5, 2.9), 1)
  check('C south of it (3.5, 0.1) is floor', covers(top, 3.5, 0.1), 1)
  check('E the extrusion caps the opening: 2 side triangles per ring edge, '
    + '4 + 4 edges', sideFaces(tris, 3.08, 2.98).length, 16)
  const box = new THREE.Box3().setFromObject(mesh)
  check('D the box is the OUTLINE\'s, x 0…8',
    [box.min.x, box.max.x], [0, 8])
  check('D ...z −3…3', [box.min.z, box.max.z], [-3, 3])
  check('D ...and the verify targets still hold (top 3.08, bottom 2.98)',
    plateTargets(spec).map((t) => t.actual(box) - t.target), [0, 0])
}

// ── 2. The same body WITHOUT a hole — the baseline the numbers come from ───
{
  const spec = plate([], 0.10, 3.08)
  const { tris, top } = measure('2. the same plate with no opening', spec)
  check('A the top face is the full 48 m²',
    top.reduce((s, t) => s + areaXZ(t), 0), 48)
  check('B ...as 2 triangles', top.length, 2)
  check('C and (3.5, 1.5) is floor like everywhere else',
    covers(top, 3.5, 1.5), 1)
  check('E 8 side triangles — the outer ring alone',
    sideFaces(tris, 3.08, 2.98).length, 8)
}

// ── 3. A FLAT plate (thickness 0) — the sign branch ────────────────────────
// `sy = −pz` here, and the hole has to be mirrored with the outline. If it
// were not, the opening would sit at z −2.5…−0.5 and check C would answer the
// other way round.
{
  const spec = plate([HOLE], 0, 0)
  const { mesh, top } = measure(
    '3. flat plate (thickness 0, the mirrored branch), same opening', spec)
  check('A the surface measures 48 − 6 m²',
    top.reduce((s, t) => s + areaXZ(t), 0), 42)
  check('B ...as 8 triangles', top.length, 8)
  check('C the opening is at z +0.5…+2.5, not mirrored: (3.5, 1.5) is open',
    covers(top, 3.5, 1.5), 0)
  check('C red: (3.5, −1.5) is floor', covers(top, 3.5, -1.5), 1)
  check('C west (1.0, 1.5) and east (6.5, 1.5) are floor',
    [covers(top, 1.0, 1.5), covers(top, 6.5, 1.5)], [1, 1])
  const box = new THREE.Box3().setFromObject(mesh)
  check('D the box is the outline\'s here too',
    [box.min.x, box.max.x, box.min.z, box.max.z], [0, 8, -3, 3])
  check('D ...a flat plate has one y target and it holds',
    plateTargets(spec).map((t) => t.actual(box) - t.target), [0])
}

// ── 4. Rings that enclose nothing are ignored ──────────────────────────────
// Two points are a line, and an empty `Path` would break the triangulation of
// the ring around it — the same rule the outline itself is filtered by.
{
  const spec = plate([[[2, 0.5], [5, 0.5]], HOLE, []], 0.10, 3.08)
  const { top } = measure('4. a degenerate ring next to a real one', spec)
  check('A only the real opening is taken out (48 − 6 m²)',
    top.reduce((s, t) => s + areaXZ(t), 0), 42)
  check('B ...and the triangulation is the one-hole one', top.length, 8)
}

console.log(FAILED.length
  ? `\n${FAILED.length} FAILED:\n  - ${FAILED.join('\n  - ')}`
  : '\nall checks passed')
process.exit(FAILED.length ? 1 : 0)
