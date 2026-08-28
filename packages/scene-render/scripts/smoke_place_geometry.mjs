#!/usr/bin/env node
/**
 * Smoke check for the shared PLACE GEOMETRY (`packages/scene-render/src/
 * placeGeometry.ts`) — the admin previews' mirror of the server formulas
 * (plan-posen-plaetze.md § 3.3 / § 6). Numbers, no screenshots (§ B5a).
 *
 * Usage:  node packages/scene-render/scripts/smoke_place_geometry.mjs
 *         (self-bundles through esbuild like the client3d smokes)
 *
 * THE SAME HAND-DERIVED NUMBERS AS THE SERVER SMOKES, so a drift between
 * the two implementations fails here, not on the user's screen:
 *
 *   [1] markerSlots — scripts/smoke_scene_recipe.py block [M]: marker at
 *       (−2, −3), facing 90 (east = +x), capacity 3, spacing 0.6. Lateral
 *       = facing turned +90° = (cos 90°, −sin 90°) = (0, −1); slot i at
 *       (i − 1) × 0.6 along it → z = −3 − (i − 1) × 0.6:
 *         [[-2, -2.4], [-2, -3], [-2, -3.6]]   (an N–S line, centre = marker)
 *       Capacity 1 → the marker itself: markerSlots([1, 2], undefined, 1,
 *       0.6) = [[1, 2]]. And scripts/smoke_places.py s2: (1, −3), facing 0
 *       (south, lateral (1, 0)), capacity 2 → [[0.7, -3], [1.3, -3]].
 *   [2] pairYaw — scripts/smoke_interaction.py [9]: facing 90 → clip +X on
 *       world +x → 0 rad; scripts/smoke_places.py [7]: facing 0 → −π/2,
 *       and facing 0 with yaw_offset 90 → 0 ("lapsitting").
 *   [3] rotateXZ — interaction_engine._rotate: (1, 0) turned by +π/2 →
 *       (cos, −sin) = (0, −1); (0, 1) by +π/2 → (sin, cos) = (1, 0).
 *   [4] pairPoints — smoke_interaction [9]: centre (10, 22), facing 90,
 *       roles a (−0.3, 0) / b (0.3, 0) → yaw 0, a at (9.7, 22), b at
 *       (10.3, 22). Facing 0 (yaw −π/2, c = 0, s = −1): x' = z·s = 0,
 *       z' = −x·s = x → a (−0.3, 0) lands at (10, 21.7), b at (10, 22.3):
 *       clip +X (A → B) points SOUTH, along the facing.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_place_geometry_bundled.mjs'
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

  const { markerSlots, pairYaw, rotateXZ, pairPoints } =
    await import('../src/placeGeometry.ts')

  const FAILED = []
  const EPS = 1e-9
  const same = (got, want) => Array.isArray(want)
    ? got.length === want.length && want.every((w, i) => same(got[i], w))
    : Math.abs(got - want) <= EPS
  function check(label, got, want) {
    const ok = same(got, want)
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: ${JSON.stringify(got)}`
      + (ok ? '' : `  (expected ${JSON.stringify(want)})`))
    if (!ok) FAILED.push(label)
  }

  console.log('\n[1] markerSlots (smoke_scene_recipe [M], smoke_places s2)')
  check('facing 90, cap 3, spacing 0.6 at (−2, −3)',
    markerSlots([-2, -3], 90, 3, 0.6), [[-2, -2.4], [-2, -3], [-2, -3.6]])
  check('capacity 1 is the marker', markerSlots([1, 2], undefined, 1, 0.6), [[1, 2]])
  check('facing 0, cap 2 at (1, −3)', markerSlots([1, -3], 0, 2, 0.6), [[0.7, -3], [1.3, -3]])

  console.log('\n[2] pairYaw (smoke_interaction [9], smoke_places [7])')
  check('facing 90 → 0', pairYaw(90, 0), 0)
  check('facing 0 → −π/2', pairYaw(0, 0), -Math.PI / 2)
  check('facing 0 + offset 90 → 0', pairYaw(0, 90), 0)
  check('no facing reads as 0 (south)', pairYaw(undefined, 0), -Math.PI / 2)

  console.log('\n[3] rotateXZ (interaction_engine._rotate)')
  check('(1, 0) by +π/2 → (0, −1)', rotateXZ(1, 0, Math.PI / 2), [0, -1])
  check('(0, 1) by +π/2 → (1, 0)', rotateXZ(0, 1, Math.PI / 2), [1, 0])

  console.log('\n[4] pairPoints (smoke_interaction [9])')
  const roles = { a: [-0.3, 0], b: [0.3, 0] }
  const east = pairPoints([10, 22], 90, 0, roles)
  check('facing 90: a at (9.7, 22)', east.a, [9.7, 22])
  check('facing 90: b at (10.3, 22)', east.b, [10.3, 22])
  const south = pairPoints([10, 22], 0, 0, roles)
  check('facing 0: a at (10, 21.7)', south.a, [10, 21.7])
  check('facing 0: b at (10, 22.3) — +X points south', south.b, [10, 22.3])

  console.log()
  if (FAILED.length) {
    console.log(`${FAILED.length} check(s) FAILED:`)
    for (const f of FAILED) console.log(`  - ${f}`)
    process.exit(1)
  }
  console.log('all checks passed')
}

main()
