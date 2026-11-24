#!/usr/bin/env node
/**
 * THE START OVERLAP (owner 2026-11-24): Auto-align may REDUCE an overlap of the moved role with another person that the
 * clip's own arrangement already has (`packages/scene-render/src/pairAlign.ts` — the solve's reduce term, the verdict's
 * exchange rate, the order of preference). Every number is derived BY HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_align_start_overlap.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * Constants: T = ALIGN_OVERLAP_TOL_MM = 40 mm, w = ALIGN_OVERLAP_WEIGHT = 0.5, the wall ALIGN_CLEAR_WEIGHT 100.
 * FIXTURE (metres): basis I (side x, up y, forward z), shift only (no turn axes, no root angle, no support). One channel
 *   relation, axis u = (0, 0, 1), opening O = (0, 0.9, 0.4); a straight part of length L = 0.12 along u, 4 frames with
 *   the tip at s = 0.05, 0.08, 0.118, 0.08 (deep = frame 2, root s = −0.002 = the depth target; shallow = frame 0). The
 *   shaft lies ON the axis: a side shift a moves the shaft line's crossing of the opening plane by a at both key frames
 *   (the lever is unchanged), so the axis error costs 2a². One clearance frame: the mover's capsule a sphere of r 0.03 at
 *   (0, 0.9, 0), the other figure's a sphere of r 0.1 at (0.03, 0.9, 0): depth = 0.13 − |0.03 − a| — 0.100 at the start;
 *   its allowance clearAllowM(0.100) = 0.100 (the wall: 100·max(0, a) for a > 0).
 *   [1] THE TERM: cost 2a² + (w·(0.06 + a))² for a ≤ 0 → 4a + 2·0.25·(0.06 + a) = 0 → a = −0.03 / 4.5 = −0.0066667:
 *       the overlap 100 → 93.333 mm (6.667 mm less), the axis error 0 → 6.667 mm at both key frames (|a − that| < 2e-5).
 *   [2] BELOW T: the other sphere at (0.1, 0.9, 0) — start depth 0.13 − 0.1 = 0.030 < T: no term costs, a = 0 (< 1e-6).
 *   [3] FAILS ON THE OLD CODE (cf9e976a7 — the wall only): [1]'s fixture gives a = 0 (< 1e-6), the overlap stays 100 mm.
 *   [4] overlapExcessMm([0.100, 0.030, 0.045]) = max(0, 60, −10, 5) = 60 mm.
 *   [5] THE VERDICT's exchange rate: before axis 20 mm, after 26 mm (6 mm worse), depth error unchanged, no clearance row
 *       over its allowance, no support, no root. Without `overlap`: 6 > ALIGN_GAIN_SLACK_MM 1 → discarded 'worse'. With the
 *       excess 60 → 40 (20 mm removed): allowed growth 1 + 0.5·20 = 11 ≥ 6 and the gain 20 ≥ ALIGN_GAIN_MM 5 → applied.
 *       With 60 → 52 (8 removed): allowed 1 + 4 = 5 < 6 → 'worse'.
 *   [6] THE ORDER OF PREFERENCE: a = {axis 30, overlap 40}, b = {axis 45, overlap 0}, both applicable, deep and clearance
 *       holding: 30 + 0.5·40 = 50 > 45 → b first (compareCandidates(a, b) > 0); without the overlap a first (< 0).
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
const OLD = 'cf9e976a7d7fcc88a3a6e4ed1404d4610b780142'
async function loadSR(oldAt = null) {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-start-overlap-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const stdin = oldAt
      ? { contents: execFileSync('git', ['show', `${oldAt}:packages/scene-render/src/pairAlign.ts`], { cwd: ROOT, encoding: 'utf8' }),
        resolveDir: join(ROOT, 'packages/scene-render/src'), loader: 'ts' }
      : { contents: "export * from '@anima/scene-render';", resolveDir: join(ROOT, 'client3d'), loader: 'ts' }
    const built = await esbuild.build({ stdin, bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'sr.mjs'), external: ['three', 'three/*'], logLevel: 'error' })
    const file = join(dir, 'sr.mjs')
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}
const SR = await loadSR()
let failures = 0
const check = (label, ok, detail = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}`); if (!ok) failures++ }
assert.equal(SR.ALIGN_OVERLAP_TOL_MM, 40)
assert.equal(SR.ALIGN_OVERLAP_WEIGHT, 0.5)

const O = [0, 0.9, 0.4], U = [0, 0, 1], L = 0.12
const samples = [0.05, 0.08, 0.118, 0.08].map((s, k) => {
  const root = [O[0], O[1], O[2] + s - L]
  const chain = [0, 1, 2, 3, 4].map((j) => [root[0], root[1], root[2] + 0.03 * j])
  return { tip: chain[4], base: chain[0], chain, o: O, u: U, pivot: [0, 0.9, 0], raised: 1, channel: true, phase: k / 4 }
})
const clearAt = (cx) => [{ pivot: [0, 0.9, 0], mover: [{ id: 'm', a: [0, 0.9, 0], b: [0, 0.9, 0], r: 0.03 }],
  others: [{ name: 'Q', allowM: SR.clearAllowM(0.13 - cx), caps: [{ id: 'c', a: [cx, 0.9, 0], b: [cx, 0.9, 0], r: 0.1 }] }] }]
const solve = (lib, cx) => lib.solveAlign({ relations: [{ samples }], basis: [1, 0, 0, 0, 1, 0, 0, 0, 1], cap: lib.alignCap(), clear: clearAt(cx) })
{
  const sol = solve(SR, 0.03)
  const a = sol.x[0], depth = 0.13 - Math.abs(0.03 - a)
  const moved = samples.map((s) => SR.moveSample(s, sol.fix))
  const rep = SR.keyReport(moved)
  check('[1] the term: a = −6.667 mm, overlap 100 → 93.333 mm, axis error 6.667 mm at both key frames',
    Math.abs(a + 0.03 / 4.5) < 2e-5 && Math.abs(sol.x[1]) < 2e-5 && Math.abs(sol.x[2]) < 2e-5
      && Math.abs(rep.deep.openOffMm - 6.6667) < 0.02 && Math.abs(rep.shallow.openOffMm - 6.6667) < 0.02,
    `a ${(a * 1000).toFixed(4)} mm, overlap ${(depth * 1000).toFixed(3)} mm, axis ${rep.deep.openOffMm.toFixed(3)}/${rep.shallow.openOffMm.toFixed(3)} mm`)
}
{
  const sol = solve(SR, 0.1)
  check('[2] below T (start 30 mm): nothing moves', Math.hypot(...sol.x) < 1e-6, `|x| ${Math.hypot(...sol.x).toExponential(2)} m`)
}
{
  const OLDSR = await loadSR(OLD)
  const sol = solve(OLDSR, 0.03)
  check('[3] fails on cf9e976a7: the wall alone keeps a = 0, the overlap stays 100 mm', Math.abs(sol.x[0]) < 1e-6,
    `a ${(sol.x[0] * 1000).toExponential(2)} mm`)
}
check('[4] overlapExcessMm([0.100, 0.030, 0.045]) = 60', Math.abs(SR.overlapExcessMm([0.1, 0.03, 0.045]) - 60) < 1e-9)
{
  const row = (off) => ({ index: 0, phase: 0, depthMm: 50, rootDepthMm: -2, visRootMm: -2, rootOutside: true, tipInside: true,
    pastBottom: false, tipOffMm: off, rootOffMm: off, shaftDeg: 0, openOffMm: off, leverMm: 0, rootTargetMm: -2,
    bendDeg: null, bendWantDeg: null, bendAtLimit: false })
  const kb = { deep: row(20), shallow: row(20) }, ka = { deep: row(26), shallow: row(26) }
  const v0 = SR.alignVerdict(kb, ka, true, [], null, null)
  const v1 = SR.alignVerdict(kb, ka, true, [], null, null, { beforeMm: 60, afterMm: 40 })
  const v2 = SR.alignVerdict(kb, ka, true, [], null, null, { beforeMm: 60, afterMm: 52 })
  check('[5] the exchange rate: none → worse; 20 mm removed → applied; 8 mm removed → worse',
    v0.why === 'worse' && v1.applied && !v1.why && v2.why === 'worse', `${v0.why} / ${v1.applied} / ${v2.why}`)
}
{
  const base = { applied: true, deepOk: true, clearOk: true, depthMm: 50 }
  const a = { ...base, axisMm: 30, overlapMm: 40 }, b = { ...base, axisMm: 45, overlapMm: 0 }
  check('[6] the order of preference: 30 + 20 > 45 → the other first; without the overlap the first',
    SR.compareCandidates(a, b) > 0 && SR.compareCandidates({ ...a, overlapMm: 0 }, b) < 0)
}
console.log(failures ? `${failures} check(s) failed` : 'all checks passed')
process.exit(failures ? 1 : 0)
