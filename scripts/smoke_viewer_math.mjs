/**
 * Smoke: the two pure rules of the prop viewer's controls
 * (spec-bild-props-v2.md § B1).
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *     node scripts/smoke_viewer_math.mjs
 *
 * WHY THIS CHECK EXISTS. Both rules decide something a screenshot cannot
 * settle: whether a click CLOSES the hand-drawn ring, and whether a freshly
 * loaded model is a different enough object to be framed again. They live in
 * `frontend/src/tabs/props/viewerMath.ts` — outside the WebGL component —
 * precisely so they can be answered here, in numbers.
 *
 * The expectations are derived BY HAND from the spec, not recorded from the
 * code:
 *   · closesOnFirstPoint — the map's gesture (`MapTab.addDraftPoint`): a ring
 *     closes on its FIRST vertex, within `CLOSE_TOL_PX` pixels (the constant
 *     is imported, not copied, so a changed tolerance shows up here), and only
 *     from three points on — two points enclose no area, so even a click
 *     exactly on the start point is an ordinary point there.
 *   · shouldRefit — a bounding-sphere radius more than 25 % away from the
 *     previous model's re-frames the camera: 1.0 → 1.2 is 20 % (keep the
 *     camera), 1.0 → 1.3 is 30 % (re-frame), 1.0 → 0.7 is 30 % smaller
 *     (re-frame), and with no previous model there is nothing to keep.
 *
 * The helpers are TypeScript, so the script bundles itself into /tmp on EVERY
 * run and executes that (same harness as `scripts/smoke_slot_materials.mjs`,
 * including the esbuild lookup — a missing binary must be LOUD, never a silent
 * exit 0).
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const ROOT = path.join(__dirname, '../')

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_viewer_math_bundled.mjs'
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(ROOT, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm',
      `--outfile=${bundlePath}`,
    ], { cwd: ROOT, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' },
    })
    process.exit(run.status ?? 1)
  }

  const { closesOnFirstPoint, shouldRefit } =
    await import('../frontend/src/tabs/props/viewerMath.ts')
  const { CLOSE_TOL_PX } =
    await import('../frontend/src/tabs/world/planGeometry.ts')

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }

  console.log('\n[1] closesOnFirstPoint — the map gesture, in canvas pixels')
  const TOL = CLOSE_TOL_PX
  check(`the tolerance is the map's own (${TOL} px)`, TOL === 14, String(TOL))
  const ring3 = [[100, 100], [200, 100], [200, 200]]
  check('a click ON the first point of a 3-point ring closes it',
        closesOnFirstPoint(ring3, [100, 100], TOL) === true)
  check(`…and one ${TOL - 4} px away still does (inside the tolerance)`,
        closesOnFirstPoint(ring3, [100 + TOL - 4, 100], TOL) === true)
  check('…exactly ON the tolerance closes as well (<=, like the map)',
        closesOnFirstPoint(ring3, [100 + TOL, 100], TOL) === true)
  check(`…one ${TOL + 1} px away does not — it is an ordinary point`,
        closesOnFirstPoint(ring3, [100 + TOL + 1, 100], TOL) === false)
  check('…the diagonal counts as distance, not the axes (10/10 = 14.1 px)',
        closesOnFirstPoint(ring3, [110, 110], TOL) === false)
  check('a LAST point near the first does not close (only the first counts)',
        closesOnFirstPoint(ring3, [200, 200], TOL) === false)
  check('TWO points enclose nothing — even distance 0 is not a close',
        closesOnFirstPoint([[100, 100], [200, 100]], [100, 100], TOL) === false)
  check('one point is not a ring either',
        closesOnFirstPoint([[100, 100]], [100, 100], TOL) === false)
  check('an empty ring is not a ring',
        closesOnFirstPoint([], [100, 100], TOL) === false)

  console.log('\n[2] shouldRefit — the camera survives a model switch')
  check('no previous model: there is nothing to keep, so frame it',
        shouldRefit(null, 1.0) === true)
  check('…undefined reads the same', shouldRefit(undefined, 1.0) === true)
  check('1.0 → 1.2 (20 %): the camera stays', shouldRefit(1.0, 1.2) === false)
  check('1.0 → 1.3 (30 %): frame it again', shouldRefit(1.0, 1.3) === true)
  check('1.0 → 0.7 (30 % smaller): frame it again',
        shouldRefit(1.0, 0.7) === true)
  check('1.0 → 1.0 (the same mesh reloaded): the camera stays',
        shouldRefit(1.0, 1.0) === false)
  check('1.0 → 1.25 sits exactly ON the threshold and still stays (>)',
        shouldRefit(1.0, 1.25) === false)
  check('a degenerate previous radius (0) cannot be compared: frame it',
        shouldRefit(0, 1.0) === true)
  check('a degenerate NEW radius (0) has no framing to keep either',
        shouldRefit(1.0, 0) === true)

  console.log(`\n${failures.length
    ? 'FAILED: ' + failures.join(', ') : 'all checks passed'}`)
  process.exit(failures.length ? 1 : 0)
}

void main()
