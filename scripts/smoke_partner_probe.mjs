#!/usr/bin/env node
/**
 * The admin viewer's partner probe, the pure part (packages/scene-render/src/partnerProbe.ts; cross-person
 * collision plan Task 8). Hand-derived; every number below comes from the formulas, not from a recorded run.
 *
 * Usage: node scripts/smoke_partner_probe.mjs   (no server, no world; bundles itself with esbuild)
 *
 * PLACEMENT (`probeCapsules`): mirror x → −x, then the yaw θ about +y as three turns (x' = x·cos θ + z·sin θ,
 * z' = −x·sin θ + z·cos θ: +x goes to −z, +z to +x), then + (x, 0, z).
 * [1] Capsule `c` (0.1, 0, 0) → (0.1, 1, 0), r 0.05, region test, at pose (0, 0, yaw 0):
 *     mirrored → a (−0.1, 0, 0), b (−0.1, 1, 0), r 0.05, id/region kept; not mirrored → unchanged.
 * [2] Pose (1, 2, yaw 90°), mirrored: a = (−0.1, 0, 0) → x' = −0.1·0 + 0·1 = 0, z' = 0.1·1 + 0 = 0.1 → + (1, 2) =
 *     (1, 0, 2.1); b (1, 1, 2.1). Not mirrored: x' = 0, z' = −0.1 → a (1, 0, 1.9). A point on +z, (0, 0, 0.2) at
 *     pose (0, 0, yaw 90°): x' = 0.2, z' = 0 → (0.2, 0, 0) — the probe facing +z now faces +x. Yaw 180°, (0.1, 0, 0)
 *     not mirrored → (−0.1, 0, 0). Tolerance 1e-9 (cos 90° is 6e-17 in floats).
 * SWEEP (`probeSweepOffset`): a triangle wave of `span`, slope `speed`, period 4·span/speed, starting at 0 forwards.
 * [3] speed 0.5, span 0.6 (period 4.8 s): t = 0, 0.6, 1.2, 1.8, 2.4, 3.0 → 0, 0.3, 0.6, 0.3, 0, −0.3; t 3.6 → −0.6,
 *     t 4.8 → 0 (one period). span 0 or speed 0 → 0.
 * [4] `probeSweptPose` moves along the facing (sin θ, 0, cos θ): pose (1, 2, 90°) + 0.3 → (1.3, 2, 90°); pose
 *     (0, −0.4, 0°) + 0.2 → (0, −0.2, 0°).
 * [5] `probeSnapshot(caps)` = {name 'probe', capsules caps (the same array), channels [], interaction null};
 *     `PROBE_NAME` = 'probe'.
 * Before the module existed (base d1ca15228) the bundle fails to resolve partnerProbe.ts: nothing passes.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import assert from 'node:assert/strict'

if (!process.env.PARTNER_PROBE_BUNDLED) {
  const root = join(dirname(fileURLToPath(import.meta.url)), '..')
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild']
    .map(rel => join(root, rel)).find(existsSync)
  assert.ok(bin, 'esbuild unavailable (npm install) — nothing was checked')
  const dir = mkdtempSync(join(root, 'scripts/.smoke-partner-probe-'))
  let status = 1
  try {
    const output = join(dir, 'bundle.mjs')
    const built = spawnSync(bin, [fileURLToPath(import.meta.url), '--bundle', '--platform=node', '--format=esm',
      '--external:three', `--outfile=${output}`, '--log-level=error'], { stdio: 'inherit' })
    assert.equal(built.status, 0)
    const run = spawnSync('node', [output], { stdio: 'inherit', env: { ...process.env, PARTNER_PROBE_BUNDLED: '1' } })
    status = run.status ?? 1
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
  process.exit(status)
}
const { PROBE_NAME, probeCapsules, probeSweepOffset, probeSweptPose, probeSnapshot } =
  await import('../packages/scene-render/src/partnerProbe.ts')

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
const near = (got, want, tol = 1e-9) => got.length === want.length && got.every((v, i) => Math.abs(v - want[i]) <= tol)
const cap = { id: 'c', region: 'test', a: [0.1, 0, 0], b: [0.1, 1, 0], r: 0.05 }

console.log('--- [1] mirror ---')
{
  const [m] = probeCapsules([cap], { x: 0, z: 0, yaw: 0 }, true)
  check('mirrored: x → −x', near(m.now.a, [-0.1, 0, 0]) && near(m.now.b, [-0.1, 1, 0]), JSON.stringify(m.now))
  check('mirrored: r, id, region kept', m.now.r === 0.05 && m.id === 'c' && m.region === 'test')
  const [p] = probeCapsules([cap], { x: 0, z: 0, yaw: 0 }, false)
  check('not mirrored: unchanged', near(p.now.a, [0.1, 0, 0]) && near(p.now.b, [0.1, 1, 0]), JSON.stringify(p.now))
}

console.log('--- [2] yaw about +y, then the translation ---')
{
  const [m] = probeCapsules([cap], { x: 1, z: 2, yaw: 90 }, true)
  check('mirrored, yaw 90°, pose (1, 2): a (1, 0, 2.1)', near(m.now.a, [1, 0, 2.1]), JSON.stringify(m.now.a))
  check('… b (1, 1, 2.1)', near(m.now.b, [1, 1, 2.1]), JSON.stringify(m.now.b))
  const [p] = probeCapsules([cap], { x: 1, z: 2, yaw: 90 }, false)
  check('not mirrored: a (1, 0, 1.9)', near(p.now.a, [1, 0, 1.9]), JSON.stringify(p.now.a))
  const [f] = probeCapsules([{ ...cap, a: [0, 0, 0.2], b: [0, 0, 0.2] }], { x: 0, z: 0, yaw: 90 }, false)
  check('+z turns to +x: (0, 0, 0.2) → (0.2, 0, 0)', near(f.now.a, [0.2, 0, 0]), JSON.stringify(f.now.a))
  const [h] = probeCapsules([cap], { x: 0, z: 0, yaw: 180 }, false)
  check('yaw 180°: (0.1, 0, 0) → (−0.1, 0, 0)', near(h.now.a, [-0.1, 0, 0]), JSON.stringify(h.now.a))
}

console.log('--- [3] the sweep ---')
{
  const ts = [0, 0.6, 1.2, 1.8, 2.4, 3.0, 3.6, 4.8]
  const want = [0, 0.3, 0.6, 0.3, 0, -0.3, -0.6, 0]
  const got = ts.map(t => probeSweepOffset(t, 0.5, 0.6))
  check('speed 0.5, span 0.6: 0, 0.3, 0.6, 0.3, 0, −0.3, −0.6, 0', near(got, want), JSON.stringify(got))
  check('span 0 / speed 0 → 0', probeSweepOffset(1, 0.5, 0) === 0 && probeSweepOffset(1, 0, 0.6) === 0)
}

console.log('--- [4] along the facing ---')
{
  const a = probeSweptPose({ x: 1, z: 2, yaw: 90 }, 0.3)
  check('yaw 90°: + 0.3 along +x', near([a.x, a.z, a.yaw], [1.3, 2, 90]), JSON.stringify(a))
  const b = probeSweptPose({ x: 0, z: -0.4, yaw: 0 }, 0.2)
  check('yaw 0°: + 0.2 along +z', near([b.x, b.z, b.yaw], [0, -0.2, 0]), JSON.stringify(b))
}

console.log('--- [5] the snapshot ---')
{
  const caps = probeCapsules([cap], { x: 0, z: 0, yaw: 0 }, false)
  const snap = probeSnapshot(caps)
  check('name probe, the same capsules, no channels, no interaction',
    snap.name === 'probe' && PROBE_NAME === 'probe' && snap.capsules === caps && Array.isArray(snap.channels)
    && snap.channels.length === 0 && snap.interaction === null, JSON.stringify(snap))
}

console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed')
process.exit(failures ? 1 : 0)
