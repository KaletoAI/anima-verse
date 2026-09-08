#!/usr/bin/env node
/**
 * Smoke check for `buildExtra` (`packages/scene-render/src/primitives.ts`) —
 * the ONE box routine both renderers hand a scene extra to, since v13 with a
 * `rotation` (the stair stringer) and a `tileM` (a textured extra). Numbers,
 * no screenshots (§ B5a).
 *
 * Usage:  node packages/scene-render/scripts/smoke_extra_box.mjs
 *         (self-bundles through esbuild like the client3d smokes)
 *
 * THE SAME HAND-DERIVED NUMBERS AS THE SERVER SMOKE (scripts/
 * smoke_scene_recipe.py [5s]), so a drift between the two sides fails here:
 *
 *   [1] rotation — the contract's own stringer (EG → OG, at (2, −2), dir 90,
 *       storey 3.00): centre [3.999582, 1.437218, −2.575], size
 *       [4.969547, 0.16, 0.05], rotation [0, 0, 38.2997]. The server put the
 *       board's TOP EDGE on the line from (0, −0.04) to (3.90, 3.04) in
 *       (along, y), i.e. from x = 2 to x = 5.9 in the scene — so the box's
 *       local corner (−L/2, +d/2, 0) must land on (2.00, −0.04) and
 *       (+L/2, +d/2, 0) on (5.90, 3.04) once three has applied the Euler in
 *       radians: 38.2997° = 0.668460 rad, and
 *         x' = x·cos θ − y·sin θ = −2.4847736·0.7847797 − 0.08·0.6197748
 *            = −1.9500000 − 0.0495820 = −1.9995820  → +3.9995820 = 2.0000
 *         y' = x·sin θ + y·cos θ = −2.4847736·0.6197748 + 0.08·0.7847797
 *            = −1.5400000 + 0.0627824 = −1.4772176  → +1.4372176 = −0.0400
 *       A flight along +z (dir 0) pitches about x by −38.2997°: the local
 *       corner (0, +d/2, −L/2) then lands on (2, −0.04, −2) — the foot.
 *   [2] uvs — a tread, size [0.26, 0.04, 1.10], tileM 0.5: every face is
 *       scaled by ITS OWN extent over the tile (the wall routine), so the
 *       largest uv on the +x face is (1.10/0.5, 0.04/0.5) = (2.2, 0.08), on
 *       the +y face (0.26/0.5, 1.10/0.5) = (0.52, 2.2) and on the +z face
 *       (0.52, 0.08). tileM 0 leaves every face at 0..1.
 *   [3] no rotation → the mesh is axis aligned (rotation 0, 0, 0).
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_extra_box_bundled.mjs'
    const root = path.join(__dirname, '../../../')
    const bin = ['client3d/node_modules/.bin/esbuild',
                 'frontend/node_modules/.bin/esbuild',
                 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const esbuildResult = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm',
      `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (esbuildResult.status !== 0) process.exit(esbuildResult.status ?? 1)
    const runResult = spawnSync('node', [bundlePath], {
      stdio: 'inherit',
      env: { ...process.env, SMOKE_BUNDLED: '1' },
    })
    process.exit(runResult.status ?? 1)
  }

  const THREE = await import('three')
  const { buildExtra } = await import('../src/primitives.ts')

  const FAILED = []
  const near = (got, want, eps = 1e-4) => Array.isArray(want)
    ? got.length === want.length && want.every((w, i) => near(got[i], w, eps))
    : Math.abs(got - want) <= eps
  function check(label, got, want, eps = 1e-4) {
    const ok = near(got, want, eps)
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: ${JSON.stringify(got)}`
      + (ok ? '' : `  (expected ${JSON.stringify(want)})`))
    if (!ok) FAILED.push(label)
  }
  const corner = (mesh, local) => {
    mesh.updateMatrixWorld(true)
    const v = new THREE.Vector3(...local)
    mesh.localToWorld(v)
    return [v.x, v.y, v.z]
  }
  const mat = new THREE.MeshStandardMaterial()

  console.log('\n[1] rotation — the stringer of smoke_scene_recipe [5s]')
  const L = 4.969547, d = 0.16
  const east = buildExtra(THREE, {
    kind: 'stair_stringer', center: [3.999582, 1.437218, -2.575],
    size: [L, d, 0.05], rotation: [0, 0, 38.2997], stair: 0, level: 0,
  }, mat)
  check('Euler z in radians', east.rotation.z, 38.2997 * Math.PI / 180, 1e-9)
  check('Euler x, y stay 0', [east.rotation.x, east.rotation.y], [0, 0], 1e-12)
  check('top-foot corner (−L/2, +d/2) lands on (2.00, −0.04, −2.575)',
    corner(east, [-L / 2, d / 2, 0]), [2.0, -0.04, -2.575])
  check('top-head corner (+L/2, +d/2) lands on (5.90, 3.04, −2.575)',
    corner(east, [L / 2, d / 2, 0]), [5.9, 3.04, -2.575])
  const south = buildExtra(THREE, {
    kind: 'stair_stringer', center: [1.425, 1.437218, -2 + 1.999582],
    size: [0.05, d, L], rotation: [-38.2997, 0, 0], stair: 0, level: 0,
  }, mat)
  check('dir 0: top-foot corner (0, +d/2, −L/2) lands on (1.425, −0.04, −2)',
    corner(south, [0, d / 2, -L / 2]), [1.425, -0.04, -2.0])
  check('dir 0: top-head corner lands on (1.425, 3.04, 1.90)',
    corner(south, [0, d / 2, L / 2]), [1.425, 3.04, 1.9])

  console.log('\n[2] uvs — a tread [0.26, 0.04, 1.10] tiled at 0.5 m')
  const faceMax = (mesh, f) => {
    const uv = mesh.geometry.getAttribute('uv')
    let mu = 0, mv = 0
    for (let i = f * 4; i < f * 4 + 4; i++) {
      mu = Math.max(mu, uv.getX(i)); mv = Math.max(mv, uv.getY(i))
    }
    return [mu, mv]
  }
  const tread = buildExtra(THREE, {
    kind: 'stair_tread', center: [0, 0, 0], size: [0.26, 0.04, 1.10],
  }, mat, 0.5)
  check('+x face (depth × height) → (2.2, 0.08)', faceMax(tread, 0), [2.2, 0.08])
  check('+y face (width × depth) → (0.52, 2.2)', faceMax(tread, 2), [0.52, 2.2])
  check('+z face (width × height) → (0.52, 0.08)', faceMax(tread, 4), [0.52, 0.08])
  const plain = buildExtra(THREE, {
    kind: 'stair_tread', center: [0, 0, 0], size: [0.26, 0.04, 1.10],
  }, mat)
  check('tileM 0: every face stays 0..1',
    [faceMax(plain, 0), faceMax(plain, 2), faceMax(plain, 4)],
    [[1, 1], [1, 1], [1, 1]])

  console.log('\n[3] no rotation → axis aligned')
  check('rotation (0, 0, 0)', [plain.rotation.x, plain.rotation.y, plain.rotation.z],
    [0, 0, 0], 1e-12)
  check('centre kept', [plain.position.x, plain.position.y, plain.position.z],
    [0, 0, 0], 1e-12)

  console.log()
  if (FAILED.length) {
    console.log(`${FAILED.length} check(s) FAILED:`)
    for (const f of FAILED) console.log(`  - ${f}`)
    process.exit(1)
  }
  console.log('all checks passed')
}

main()
