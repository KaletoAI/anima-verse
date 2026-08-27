#!/usr/bin/env node
/**
 * Smoke check for the shared DOOR-LEAF PIVOT rule (ruling R13, 2026-08-28) —
 * `packages/scene-render/src/leafPivot.ts`, the ONE routine both renderers
 * hang a door leaf's pivot with.
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_leaf_pivot.mjs
 *
 * Every expected number is derived BY HAND (§ B5a). The box throughout is
 * the door fixture of scripts/smoke_picture_areas.py fixture F —
 *
 *   leaf_bbox = {min: [0.1, 0.1, −0.02], max: [0.9, 2.1, 0]}
 *
 * (a 0.8 × 2.0 m leaf, 2 cm thick, front at z = 0). The rule: rotate the box
 * by the FIX rotation R (three's Euler 'YXZ' = Ry·Rx·Rz, the order place()
 * uses), pick (min x, min y, centre z) in that frame, map back by Rᵀ; the
 * axis is Rᵀ·(0, 1, 0). Column-vector matrices:
 *
 *   Rx(a) = [[1,0,0],[0,cos,−sin],[0,sin,cos]]
 *   Ry(b) = [[cos,0,sin],[0,1,0],[−sin,0,cos]]
 *   Rz(g) = [[cos,−sin,0],[sin,cos,0],[0,0,1]]
 *
 * --- fix 0 (R12 exactly) ---------------------------------------------------
 *   point (0.1, 0.1, −0.01)   axis (0, 1, 0)
 *     x = min.x, y = min.y, z = (−0.02 + 0)/2 = −0.01
 *
 * --- fix y = 180° -----------------------------------------------------------
 *   Ry(180): (x, y, z) → (−x, y, −z). Rotated box x ∈ [−0.9, −0.1],
 *   y ∈ [0.1, 2.1], z ∈ [0, 0.02] → pick (−0.9, 0.1, 0.01) → back through
 *   Ry(−180) = Ry(180): (0.9, 0.1, −0.01). The fixed frame's min.x IS the raw
 *   max.x — the edge R12's raw rule would have called the free one.
 *   axis (0, 1, 0).
 *
 * --- fix y = 90° ------------------------------------------------------------
 *   Ry(90): cos 0, sin 1 → (x, y, z) → (z, y, −x). Rotated box
 *   x ∈ [−0.02, 0], y ∈ [0.1, 2.1], z ∈ [−0.9, −0.1] → pick (−0.02, 0.1, −0.5)
 *   → Ry(−90): (x, y, z) → (−z, y, x) → (0.5, 0.1, −0.02): the raw min.z
 *   edge (the leaf's BACK face), mid-width. axis (0, 1, 0).
 *
 * --- fix x = 90° (the axis tilts) -------------------------------------------
 *   Rx(90): cos 0, sin 1 → (x, y, z) → (x, −z, y). Rotated box
 *   x ∈ [0.1, 0.9], y ∈ [0, 0.02], z ∈ [0.1, 2.1] → pick (0.1, 0, 1.1)
 *   → Rx(−90): (x, y, z) → (x, z, −y) → (0.1, 1.1, 0): the raw min.x edge at
 *   mid-HEIGHT on the front face; axis Rx(−90)·(0,1,0) = (0, 0, −1) — the
 *   fixed vertical is raw −z, the hinge line runs along the leaf's depth.
 *
 * --- fix z = 90° (rolled: the top edge becomes the hinge) -------------------
 *   Rz(90): cos 0, sin 1 → (x, y, z) → (−y, x, z). Rotated box
 *   x ∈ [−2.1, −0.1], y ∈ [0.1, 0.9], z ∈ [−0.02, 0] → pick (−2.1, 0.1, −0.01)
 *   → Rz(−90): (x, y, z) → (y, −x, z) → (0.1, 2.1, −0.01); axis (1, 0, 0):
 *   the line through the leaf's TOP-left corner along raw +x.
 *
 * --- the matrix IS three's --------------------------------------------------
 *   Besides the hand numbers, every case is cross-checked against
 *   `new THREE.Euler(x, y, z, 'YXZ')` applied to the box corners — the proof
 *   that the package's R is the rotation place() puts on the fix group.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_leaf_pivot_bundled.mjs'
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
      cwd: root,
    })
    process.exit(run.status ?? 1)
  }

  const { leafPivot, fixMatrix } =
    await import('../packages/scene-render/src/leafPivot.ts')
  const THREE = await import('three')

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const near = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps
  const vnear = (a, b) => a.length === 3 && b.length === 3 && a.every((v, i) => near(v, b[i]))
  const fmt = (v) => `(${v.map((x) => +x.toFixed(6)).join(', ')})`

  const bbox = { min: [0.1, 0.1, -0.02], max: [0.9, 2.1, 0] }
  const cases = [
    ['fix 0 (R12 exactly)', {}, [0.1, 0.1, -0.01], [0, 1, 0]],
    ['fix y = 180°: the fixed min.x is the raw max.x', { y: 180 }, [0.9, 0.1, -0.01], [0, 1, 0]],
    ['fix y = 90°: the raw min.z edge, mid-width', { y: 90 }, [0.5, 0.1, -0.02], [0, 1, 0]],
    ['fix x = 90°: min.x at mid-height on the front, axis −z', { x: 90 }, [0.1, 1.1, 0], [0, 0, -1]],
    ['fix z = 90°: the top-left corner, axis +x', { z: 90 }, [0.1, 2.1, -0.01], [1, 0, 0]],
  ]
  console.log('--- leafPivot(bbox, fix): hand-derived point + axis ---')
  for (const [label, fix, point, axis] of cases) {
    const got = leafPivot(bbox, fix)
    check(`${label}: point ${fmt(point)}`, vnear(got.point, point), fmt(got.point))
    check(`${label}: axis ${fmt(axis)}`, vnear(got.axis, axis), fmt(got.axis))
  }
  check('undefined fix is fix 0', vnear(leafPivot(bbox, undefined).point, [0.1, 0.1, -0.01]))
  check('the axis is unit length for a tilted fix',
    near(Math.hypot(...leafPivot(bbox, { x: 30, y: 45, z: 60 }).axis), 1))

  console.log('\n--- the rotation matrix is three\'s Euler YXZ (what place() applies) ---')
  const corner = [0.9, 2.1, -0.02]
  for (const [label, fix] of cases.concat([['a mixed fine fix', { x: 17, y: -40, z: 125 }]])) {
    const R = fixMatrix(fix)
    const mine = [0, 1, 2].map((r) => R[r][0] * corner[0] + R[r][1] * corner[1] + R[r][2] * corner[2])
    const e = new THREE.Euler(((fix.x || 0) * Math.PI) / 180, ((fix.y || 0) * Math.PI) / 180,
      ((fix.z || 0) * Math.PI) / 180, 'YXZ')
    const v = new THREE.Vector3(...corner).applyEuler(e)
    check(`${label}: R·corner == three's Euler(YXZ)·corner`, vnear(mine, [v.x, v.y, v.z]),
      `${fmt(mine)} vs ${fmt([v.x, v.y, v.z])}`)
  }
  // …and the mapped-back pivot really lies on the fixed frame's min-x/min-y line:
  // rotate the answer forward again and compare with the fixed pick.
  for (const [label, fix] of cases) {
    const got = leafPivot(bbox, fix)
    const e = new THREE.Euler(((fix.x || 0) * Math.PI) / 180, ((fix.y || 0) * Math.PI) / 180,
      ((fix.z || 0) * Math.PI) / 180, 'YXZ')
    const box = new THREE.Box3()
    for (const x of [bbox.min[0], bbox.max[0]]) for (const y of [bbox.min[1], bbox.max[1]])
      for (const z of [bbox.min[2], bbox.max[2]]) box.expandByPoint(new THREE.Vector3(x, y, z).applyEuler(e))
    const fwd = new THREE.Vector3(...got.point).applyEuler(e)
    const ax = new THREE.Vector3(...got.axis).applyEuler(e)
    check(`${label}: in the fixed frame the pivot sits at (box.min.x, box.min.y, centre z)`,
      near(fwd.x, box.min.x) && near(fwd.y, box.min.y) && near(fwd.z, (box.min.z + box.max.z) / 2),
      fmt([fwd.x, fwd.y, fwd.z]))
    check(`${label}: …and the axis is the fixed frame's +y`, vnear([ax.x, ax.y, ax.z], [0, 1, 0]))
  }

  console.log()
  if (failures.length) {
    console.log(`FAILED: ${failures.length}`)
    for (const f of failures) console.log(`  - ${f}`)
    process.exit(1)
  }
  console.log('all checks passed')
}

main().catch((e) => { console.error(e); process.exit(1) })
