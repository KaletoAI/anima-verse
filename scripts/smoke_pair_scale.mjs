#!/usr/bin/env node
/**
 * Owner decision 2026-11-20 ("the alignment is per pair; it must be general"): the size rule of
 * `packages/scene-render/src/pairScale.ts` — each figure's horizontal root path scaled by its own ratio a = h / 1.70 m
 * about the clip's contact pivot C. Every expected number is derived BY HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_pair_scale.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * SCALES: a_A = 1.60 / 1.70 = 16/17 = 0.94117647, a_B = 1.85 / 1.70 = 37/34 = 1.08823529.
 * PIVOT: stored pair_pivot_cm [12, 30] → C = (0.12, 0.30) m (pairPivotOf).
 * [1] THE CONTACT HOLDS. A synthetic stroke, 17 frames t_k = k/16: the receiving figure A sways, its root
 *     p_A(t) = (−0.05 + 0.01·sin 2πt, −0.40); the entering figure B strokes along forward,
 *     p_B(t) = (0.12 + 0.004·cos 2πt, 0.70 + 0.05·cos 2πt). At every frame the contact is at C (the stored pivot), so
 *     the body-fixed offsets of the two contact points are c_A(t) = C − p_A(t), c_B(t) = C − p_B(t). Scaled,
 *     p_i' = C + a_i·(p_i − C) and the contact points are p_i' + a_i·c_i — algebraically both equal C, so the two
 *     coincide: expect |(p_A' + a_A c_A) − (p_B' + a_B c_B)| < 1e-5 m (0.01 mm) horizontally at every frame, for the
 *     pair 1.60 / 1.85 and for 1.85 / 1.60 (roles swapped).
 * [2] HAND VALUES at t = 0: p_A = (−0.05, −0.40): p_A − C = (−0.17, −0.70), a_A·(−0.17) = −0.16 (0.17·16/17),
 *     a_A·(−0.70) = −11.2/17 = −0.65882353 → p_A' = (−0.04, −0.35882353). p_B = (0.124, 0.75): p_B − C = (0.004, 0.45),
 *     a_B·0.004 = 0.00435294, a_B·0.45 = 0.48970588 → p_B' = (0.12435294, 0.78970588). (±1e-8)
 * [3] IDENTITY: pairFigureScale(1.70) === 1, of undefined / 0 / NaN / −1 === 1; with a = 1 scalePairRoot returns the
 *     very object it was given (no arithmetic), so both scales 1 reproduce the input exactly, every frame;
 *     scalePairShift likewise.
 * [4] pairPivotOf: null / [] / [400, 0] (beyond ±300) / ['1', 2] → the origin (0, 0); [12, 30] → (0.12, 0.30).
 * [5] THE SHIFT: scalePairShift((0.02, −0.01), 37/34) = (0.02176471, −0.01088235) (±1e-8).
 * [6] clipFramePivot inverts the placement x = ax + rx·cos + rz·sin, z = az − rx·sin + rz·cos. Anchor (2, 3),
 *     yaw 90° (cos 0, sin 1): r = (0.12, 0.30) is world (2.30, 2.88); clipFramePivot((2.30, 0.9, 2.88)) = (0.12, 0.30)
 *     (±1e-12). Yaw 0: identity minus the anchor.
 * [7] pairPivotCm: relation 1, o = (2.30, 0.9, 2.88) every frame, u = (0, 0, 1), tips at z 2.86 / 2.91 / 2.89 → the
 *     deep frame is index 1 (largest axial 0.03), pivot (12.0, 30.0) cm. Relation 2: deep frame index 0 (tip z
 *     2.85 + 0.05 over o z 2.80 at frame 0, the others shallower) with o = world of r = (0.20, 0.10) = (2.10, 0.9, 2.80)
 *     at frame 0 and o one metre off at the others (a wrong pick shows) → (20.0, 10.0). The mean: (16.0, 20.0).
 *     No relation with samples → null.
 * [8] THE GAME PLACEMENT (the numbers of client3d/scripts/smoke_pair_root_sets.mjs [B], here as the pure composition
 *     npcs.ts tickInteraction runs: scalePairRoot, then the anchor transform). Root p = (0.3, 0.1), pivot
 *     C = (0.12, 0.30), anchor (10, 22), yaw 90° (x = ax + rx·cos + rz·sin = 10 + rz, z = az − rx·sin + rz·cos = 22 − rx):
 *     no height and 1.70 m → p unchanged → (10.1, 21.7); 1.85 m, a = 37/34: p' = (0.12 + a·0.18, 0.30 − a·0.20) =
 *     (0.31588235, 0.08235294) → (10.08235294, 21.68411765); 1.60 m, a = 16/17: p' = (0.28941176, 0.11176471) →
 *     (10.11176471, 21.71058824) (±1e-8).
 *
 * VECTOR: shared/test-vectors/pair_scale.json carries [1] (the contact point p_i' + a_i·c_i at the frames t = 0, 1/4,
 * 1/2, 3/4 — sin/cos exact there — for both height orders, = C ±1e-12), [2]–[5] and [8] for the native client; this
 * smoke replays it after its own asserts. [6]/[7] (Auto-align, admin only) stay local.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-pair-scale-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: "export * from '@anima/scene-render';", resolveDir: join(ROOT, 'client3d'), loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'sr.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'sr.mjs')
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}
const S = await loadSR()
let n = 0
const ok = (label) => { n++; console.log('  ok', label) }
const near = (got, want, eps, label) => {
  assert.ok(Math.abs(got - want) <= eps, `${label}: ${got} vs ${want}`)
}

const aA = S.pairFigureScale(1.60), aB = S.pairFigureScale(1.85)
near(aA, 16 / 17, 1e-15, 'a_A'); near(aB, 37 / 34, 1e-15, 'a_B')
const C = S.pairPivotOf([12, 30])
near(C.x, 0.12, 1e-15, 'C.x'); near(C.z, 0.30, 1e-15, 'C.z')

// [1] the contact holds at every frame of the stroke
const frames = Array.from({ length: 17 }, (_, k) => k / 16)
const pA = (t) => ({ x: -0.05 + 0.01 * Math.sin(2 * Math.PI * t), z: -0.40 })
const pB = (t) => ({ x: 0.12 + 0.004 * Math.cos(2 * Math.PI * t), z: 0.70 + 0.05 * Math.cos(2 * Math.PI * t) })
for (const [sa, sb] of [[aA, aB], [aB, aA]]) {
  let worst = 0
  for (const t of frames) {
    const a = pA(t), b = pB(t)
    const cA = { x: C.x - a.x, z: C.z - a.z }, cB = { x: C.x - b.x, z: C.z - b.z }
    const a2 = S.scalePairRoot(a, C, sa), b2 = S.scalePairRoot(b, C, sb)
    const qa = { x: a2.x + sa * cA.x, z: a2.z + sa * cA.z }, qb = { x: b2.x + sb * cB.x, z: b2.z + sb * cB.z }
    worst = Math.max(worst, Math.hypot(qa.x - qb.x, qa.z - qb.z))
    // and the contact point is C itself
    near(qa.x, C.x, 1e-12, 'contact x'); near(qa.z, C.z, 1e-12, 'contact z')
    // the roots really moved (the rule is not a no-op)
    assert.ok(Math.hypot(a2.x - a.x, a2.z - a.z) > 1e-3 && Math.hypot(b2.x - b.x, b2.z - b.z) > 1e-3)
  }
  assert.ok(worst < 1e-5, `worst ${worst}`)
  ok(`[1] contact points coincide < 0.01 mm at all 17 frames (scales ${sa.toFixed(4)} / ${sb.toFixed(4)}; worst ${(worst * 1000).toExponential(2)} mm)`)
}

// [2] hand values at t = 0
{
  const a2 = S.scalePairRoot(pA(0), C, aA), b2 = S.scalePairRoot(pB(0), C, aB)
  near(a2.x, -0.04, 1e-8, 'pA.x'); near(a2.z, -0.35882353, 1e-8, 'pA.z')
  near(b2.x, 0.12435294, 1e-8, 'pB.x'); near(b2.z, 0.78970588, 1e-8, 'pB.z')
  ok('[2] t = 0: p_A\' = (-0.04, -0.35882353), p_B\' = (0.12435294, 0.78970588)')
}

// [3] identity
{
  assert.equal(S.pairFigureScale(1.7), 1)
  for (const h of [undefined, null, 0, NaN, -1]) assert.equal(S.pairFigureScale(h), 1)
  for (const t of frames) {
    const a = pA(t), b = pB(t)
    assert.equal(S.scalePairRoot(a, C, 1), a); assert.equal(S.scalePairRoot(b, C, 1), b)
    assert.equal(S.scalePairRoot(a, C, 1).x, a.x); assert.equal(S.scalePairRoot(b, C, 1).z, b.z)
  }
  const sh = { x: 0.02, z: -0.01 }
  assert.equal(S.scalePairShift(sh, 1), sh)
  ok('[3] scale 1 (1.70 m, or no height) returns the input object unchanged at every frame; shift too')
}

// [4] pivot parsing
{
  for (const bad of [null, undefined, [], [400, 0], ['1', 2], [1, 2, 3], [NaN, 0]]) {
    const p = S.pairPivotOf(bad)
    assert.equal(p.x, 0); assert.equal(p.z, 0)
  }
  ok('[4] invalid / absent pivots read as the clip frame origin; [12, 30] as (0.12, 0.30)')
}

// [5] the renderer shift
{
  const s = S.scalePairShift({ x: 0.02, z: -0.01 }, aB)
  near(s.x, 0.02176471, 1e-8, 'shift x'); near(s.z, -0.01088235, 1e-8, 'shift z')
  ok('[5] shift (0.02, -0.01) at 1.85 m = (0.02176471, -0.01088235)')
}

// [6] world → clip frame
{
  const p = S.clipFramePivot([2.30, 0.9, 2.88], { x: 2, z: 3 }, Math.PI / 2)
  near(p.x, 0.12, 1e-12, 'cf x'); near(p.z, 0.30, 1e-12, 'cf z')
  const q = S.clipFramePivot([2.12, 0, 3.30], { x: 2, z: 3 }, 0)
  near(q.x, 0.12, 1e-12, 'cf0 x'); near(q.z, 0.30, 1e-12, 'cf0 z')
  ok('[6] clipFramePivot inverts the placement at yaw 90° and 0°')
}

// [7] Auto-align's pivot
{
  const u = [0, 0, 1]
  const o1 = [2.30, 0.9, 2.88]
  const rel1 = [2.86, 2.91, 2.89].map((z) => ({ tip: [2.30, 0.9, z], o: o1, u }))
  const o2 = [2.10, 0.9, 2.80], far = [3.10, 0.9, 3.80]
  const rel2 = [{ tip: [2.10, 0.9, 2.85], o: o2, u }, { tip: [3.10, 0.9, 3.80], o: far, u }, { tip: [3.10, 0.9, 3.79], o: far, u }]
  const one = S.pairPivotCm([rel1], { x: 2, z: 3 }, Math.PI / 2)
  assert.deepEqual(one, [12, 30])
  const two = S.pairPivotCm([rel2], { x: 2, z: 3 }, Math.PI / 2)
  assert.deepEqual(two, [20, 10])
  const both = S.pairPivotCm([rel1, rel2], { x: 2, z: 3 }, Math.PI / 2)
  assert.deepEqual(both, [16, 20])
  assert.equal(S.pairPivotCm([[]], { x: 0, z: 0 }, 0), null)
  ok('[7] pairPivotCm: (12, 30), (20, 10), mean (16, 20); none → null')
}
// the shared vector (native AnimaNative.Tests PairScaleVectorTests replays the same file)
{
  const { loadVectors, runVectors } = await import(join(ROOT, 'shared/test-vectors/vectors.mjs'))
  const { passed, failed } = runVectors(loadVectors('pair_scale'), {
    pairFigureScale: (h) => S.pairFigureScale(h),
    pairPivotOf: (stored) => S.pairPivotOf(stored),
    scalePairRoot: (root, pivot, a) => S.scalePairRoot(root, pivot, a),
    scalePairShift: (shift, a) => S.scalePairShift(shift, a),
    pairContactPoint: (p, pivotCm, h) => {
      const C = S.pairPivotOf(pivotCm), a = S.pairFigureScale(h)
      const q = S.scalePairRoot(p, C, a)
      return { x: q.x + a * (C.x - p.x), z: q.z + a * (C.z - p.z) }
    },
    pairPlacedRoot: (root, pivot, h, anchor) => {
      const r = S.scalePairRoot(root, pivot, S.pairFigureScale(h))
      const c = Math.cos(anchor.yaw), s = Math.sin(anchor.yaw)
      return { x: anchor.x + r.x * c + r.z * s, z: anchor.z - r.x * s + r.z * c }
    },
  })
  assert.equal(failed, 0, `pair_scale.json: ${failed} failed`)
  ok(`[vector] pair_scale.json: ${passed} cases`)
}
console.log(`smoke_pair_scale: ${n} ok`)
