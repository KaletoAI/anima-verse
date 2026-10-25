/**
 * Smoke: a wall texture must tile in WORLD METRES on every face of the box —
 * the broad face AND the narrow ones a door or window leaves behind.
 *
 * Usage (the package is TypeScript, so it is bundled first):
 *     node_modules/.bin/esbuild client3d/scripts/smoke_wall_uv.mjs --bundle \
 *         --platform=node --format=esm --outfile=/tmp/wuv.mjs && node /tmp/wuv.mjs
 *
 * Runs headless against the SHARED buildWall — the one routine both renderers
 * use — with the real three from node_modules, so the box's uv layout is the
 * one that actually ships, not a stub of it.
 *
 * THE DEFECT IT PINS DOWN (user report: "windows and doors of locations are
 * warped in the client"). Both renderers used to compute ONE repeat from the
 * wall FACE and put it on the material:
 *
 *     tex.repeat.set(len / tileM, wall.height / tileM)
 *
 * `BoxGeometry` normalises the uvs of every face to 0..1, so that one repeat
 * hits all six. Five of them are not the wall face:
 *
 *   ±x  the end faces  — a door jamb / window reveal, only `thickness` wide
 *   ±y  top and bottom — a sill's top, a lintel's underside, `thickness` deep
 *   ±z  the wall faces — the only ones the old number was ever right for
 *
 * With a typical `thickness` of 0.07 m the error is not subtle: see the red
 * counter-check in section 3, which recomputes the old numbers.
 *
 * EXPECTED, worked out by hand. Metres per tile must be the same everywhere,
 * so a face's uv span is (its own extent in metres) / tileM.
 *
 *   A. Wall segment 10.2624 m long, 2.65 m high, 0.07 m thick, tileM 2:
 *        wall face  (±z): u = 10.2624/2 = 5.1312   v = 2.65/2 = 1.325
 *        reveal     (±x): u =    0.07/2 = 0.035    v = 2.65/2 = 1.325
 *        top/bottom (±y): u = 10.2624/2 = 5.1312   v =  0.07/2 = 0.035
 *
 *      The reveal's u is 0.035 and NOT 5.1312 — that single number is the
 *      whole bug: the old code tiled 146.6 times too often across 7 cm.
 *
 *   B. Sill under a window, 1.2 m long, 0.9 m high, 0.07 m thick, tileM 2:
 *        top face   (±y): u = 1.2/2 = 0.6          v = 0.07/2 = 0.035
 *      The old v was 0.9/2 = 0.45, i.e. 12.86 times too dense on the one face
 *      a person standing at the window actually looks down on.
 *
 * The face order is NOT hard-coded here on purpose: each group of 4 vertices
 * is identified by its NORMAL and then measured against the extent that normal
 * implies. A three release that reorders `buildPlane` would therefore be
 * caught by this check instead of silently passing it.
 */
import { loadVectorFile } from '../../shared/test-vectors/vectors.mjs'
import * as THREE from 'three'
// '../../' = the repo root: this file lives in client3d/scripts/, the shared
// package at packages/scene-render. esbuild resolves it relative to THIS file.
import { buildWall } from '../../packages/scene-render/src/primitives.ts'

const vectors = loadVectorFile('shared/test-vectors/scene_primitives.json').cases[0]
const oracle = vectors.expect
  const measured = []
  const FAILED = []

function check(label, got, tol = 1e-4) {
  const want = oracle[measured.length]
  measured.push(got)
  const ok = Math.abs(got - want) <= tol
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: ${got.toFixed(4)}`
    + (ok ? '' : `  (expected ${want})`))
  if (!ok) FAILED.push(label)
}

/** A straight wall of the given length along +x, so `from`/`to` are trivial
 *  and only the box dimensions are under test. */
function wallSpec(len, height, thickness) {
  return {
    room_id: 'r', level: 0, from: [0, 0], to: [len, 0],
    height, thickness, base_y: 0, outward_normal: [0, -1],
    texture_kind: 'brick', glass: false,
  }
}

/**
 * uv spans per face, keyed by the face's own normal ('+x', '-y', ...). Reads
 * the built geometry, so it measures what the renderer will hand the GPU.
 */
function faceSpans(geometry) {
  const uv = geometry.getAttribute('uv')
  const nrm = geometry.getAttribute('normal')
  if (uv.count !== 24) throw new Error(`expected 24 box vertices, got ${uv.count}`)
  const out = new Map()
  for (let f = 0; f < 6; f++) {
    const i0 = f * 4
    const axis = Math.abs(nrm.getX(i0)) > 0.5 ? 'x'
      : Math.abs(nrm.getY(i0)) > 0.5 ? 'y' : 'z'
    const sign = (axis === 'x' ? nrm.getX(i0)
      : axis === 'y' ? nrm.getY(i0) : nrm.getZ(i0)) > 0 ? '+' : '-'
    let uMin = Infinity, uMax = -Infinity, vMin = Infinity, vMax = -Infinity
    for (let i = i0; i < i0 + 4; i++) {
      uMin = Math.min(uMin, uv.getX(i)); uMax = Math.max(uMax, uv.getX(i))
      vMin = Math.min(vMin, uv.getY(i)); vMax = Math.max(vMax, uv.getY(i))
    }
    out.set(sign + axis, { u: uMax - uMin, v: vMax - vMin })
  }
  if (out.size !== 6) throw new Error('two box faces share a normal — layout changed')
  return out
}

function built(len, height, thickness, tileM) {
  const mesh = buildWall(THREE, wallSpec(len, height, thickness),
                         new THREE.MeshBasicMaterial(), tileM)
  return faceSpans(mesh.geometry)
}

// ── 1. The reported case: a long textured wall with openings ─────────────
const [LEN, HIGH, THICK, TILE] = vectors.args

console.log('1. wall 10.2624 x 2.65 x 0.07 m, tile 2 m — every face in world scale')
{
  const s = built(LEN, HIGH, THICK, TILE)
  for (const face of ['+z', '-z']) {
    check(`wall face ${face} u`, s.get(face).u)
    check(`wall face ${face} v`, s.get(face).v)
  }
  for (const face of ['+x', '-x']) {
    check(`reveal ${face} u (jamb, 7 cm)`, s.get(face).u)
    check(`reveal ${face} v`, s.get(face).v)
  }
  for (const face of ['+y', '-y']) {
    check(`lintel/soffit ${face} u`, s.get(face).u)
    check(`lintel/soffit ${face} v (7 cm)`, s.get(face).v)
  }
}

// ── 2. The sill under a window ──────────────────────────────────────────
console.log('\n2. sill 1.2 x 0.9 x 0.07 m, tile 2 m — the face you look down on')
{
  const s = built(1.2, 0.9, THICK, TILE)
  check('sill top +y u', s.get('+y').u)
  check('sill top +y v (7 cm)', s.get('+y').v)
  check('sill face +z u', s.get('+z').u)
  check('sill face +z v', s.get('+z').v)
}

// ── 3. Red counter-check: the OLD material repeat, recomputed ────────────
// Not a second opinion on the fix — a measurement of the defect. The old code
// put ONE pair on the material, so every face got the wall face's numbers.
console.log('\n3. red counter-check — what the old material repeat did')
{
  const oldU = LEN / TILE, oldV = HIGH / TILE
  const s = built(LEN, HIGH, THICK, TILE)
  check('old repeat u (from the wall face)', oldU)
  check('reveal squeeze factor u', oldU / s.get('+x').u, 1e-3)
  const sill = built(1.2, 0.9, THICK, TILE)
  check('sill-top squeeze factor v', (0.9 / TILE) / sill.get('+y').v, 1e-3)
}

// ── 4. tileM 0 leaves the box alone (glass bands, untextured walls) ──────
console.log('\n4. tileM 0 — no texture, so the default 0..1 uvs stay')
{
  const s = built(LEN, HIGH, THICK, 0)
  for (const face of ['+x', '+y', '+z']) {
    check(`face ${face} u`, s.get(face).u)
    check(`face ${face} v`, s.get(face).v)
  }
}

// ── 5. The geometry itself is untouched ─────────────────────────────────
// The uv rewrite must not move a single vertex — the § B5a wall targets
// (base_y, top_y, centre) are measured on the same box.
console.log('\n5. the box still measures what the payload says')
{
  const mesh = buildWall(THREE, wallSpec(LEN, HIGH, THICK),
                         new THREE.MeshBasicMaterial(), TILE)
  mesh.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(mesh)
  check('base_y', box.min.y)
  check('top_y', box.max.y)
  check('centre.x', (box.min.x + box.max.x) / 2)
  check('centre.z', (box.min.z + box.max.z) / 2)
  check('length x', box.max.x - box.min.x)
  check('thickness z', box.max.z - box.min.z)
}

console.log()
if (FAILED.length) {
  console.log(`FAILED (${FAILED.length}): ${FAILED.join(', ')}`)
  process.exit(1)
}
if (globalThis.__scenePrimitiveMeasure) globalThis.__scenePrimitiveMeasure(measured)
  console.log('all checks passed')
