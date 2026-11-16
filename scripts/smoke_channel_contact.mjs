#!/usr/bin/env node
/**
 * Ruling A126: Auto-align of a pair clip with a channel (`packages/scene-render/src/channelContact.ts`). Every expected
 * number is derived BY HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_channel_contact.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE 1 (metres). Channel O = (0, 0, 0), u = (0, 0, 1) in every frame. Three frames, tip T_t = (0.01, −0.02, z_t)
 *   with z = −0.05, 0, 0.03; base = T − (0, 0, 0.1) (shaft on the axis direction).
 *   [1] ENTRY FRAME = argmin s = frame 0 (s = −0.05).
 *   [2] SOLVE: P_t = diag(1, 1, 0); W = 10 · 3 = 30; M = diag(3, 3, 30), g = (3·0.01, 3·(−0.02), 30·(−0.05))
 *       → Δ = −M⁻¹g = (−0.01, 0.02, 0.05) (±1e-12).
 *   [3] BEFORE (Δ = 0): entry |(0.01, −0.02, −0.05)| = √0.003 = 54.7723 mm; deepest frame 2, depth 30 mm, lateral
 *       √0.0005 = 22.3607 mm, max lateral over s ≥ 0 (frames 1, 2) 22.3607 mm; shaft angle 0°.
 *   [4] AFTER (Δ of [2]): entry 0 mm; deepest frame 2, depth 0.03 + 0.05 = 80 mm, lateral 0; angle 0°.
 *   [5] LAMPS with R 0.035, F 0.05, α 30° (R + F tan α = 63.8675 mm): before → yellow (entry 54.8 > 5, lateral
 *       22.4 ≤ 63.9); after → green; after with the overlap grown by 31 mm (> 30) → yellow.
 * FIXTURE 2. Same channel; two frames, tips (0, 0, −0.01) and (0.02, 0, 0.02).
 *   [6] Δ: M = diag(2, 2, 20), g = (0.02, 0, 20·(−0.01)) → Δ = (−0.01, 0, 0.01). After: entry frame 0 at (−0.01, 0, 0)
 *       → 10 mm; deepest frame 1 at (0.01, 0, 0.03): depth 30 mm, lateral 10 mm → yellow (entry 10 > 5).
 * [7] RED: fixture 1 shifted by (0, 0, −0.1) has every s < 0 → red.
 * [8] bodyOverlap: contacts A|hips–B|x 0.05 and A|leg–B|y 0.02 skipping A|hips → 0.02; skipping nothing → 0.05.
 * [9] No samples → Δ = (0, 0, 0), entry index −1.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-channel-contact-'))
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

const SR = await loadSR()
const near = (a, b, eps, msg) => assert.ok(Math.abs(a - b) <= eps, `${msg}: ${a} vs ${b}`)
const U = [0, 0, 1], O = [0, 0, 0]
const s1 = [-0.05, 0, 0.03].map((z) => ({ tip: [0.01, -0.02, z], base: [0.01, -0.02, z - 0.1], o: O, u: U }))
const CH = { r: 0.035, funnel: 0.05, coneDeg: 30 }

assert.equal(SR.CONTACT_ENTRY_WEIGHT, 10)
assert.equal(SR.CONTACT_ENTRY_GREEN_MM, 5)
assert.equal(SR.CONTACT_CLEAR_MM, 30)
assert.equal(SR.entryFrame(s1), 0)                                                   // [1]
const d = SR.solveContactShift(s1)                                                   // [2]
near(d[0], -0.01, 1e-12, 'dx'); near(d[1], 0.02, 1e-12, 'dy'); near(d[2], 0.05, 1e-12, 'dz')
const b = SR.contactReport(s1)                                                       // [3]
near(b.entryMm, 54.7723, 1e-4, 'entry before'); assert.equal(b.deepIndex, 2)
near(b.depthMm, 30, 1e-9, 'depth before'); near(b.lateralMm, 22.3607, 1e-4, 'lateral before')
near(b.maxLateralMm, 22.3607, 1e-4, 'max lateral'); near(b.axisDeg, 0, 1e-6, 'axis')
const a = SR.contactReport(s1, d)                                                    // [4]
near(a.entryMm, 0, 1e-9, 'entry after'); near(a.depthMm, 80, 1e-9, 'depth after'); near(a.lateralMm, 0, 1e-9, 'lat after')
assert.equal(SR.contactLamp(b, CH), 'yellow')                                        // [5]
assert.equal(SR.contactLamp(a, CH), 'green')
assert.equal(SR.contactLamp(a, CH, 31), 'yellow')
const s2 = [{ tip: [0, 0, -0.01], base: [0, 0, -0.11], o: O, u: U }, { tip: [0.02, 0, 0.02], base: [0.02, 0, -0.08], o: O, u: U }]
const d2 = SR.solveContactShift(s2)                                                  // [6]
near(d2[0], -0.01, 1e-12, 'f2 dx'); near(d2[1], 0, 1e-12, 'f2 dy'); near(d2[2], 0.01, 1e-12, 'f2 dz')
const a2 = SR.contactReport(s2, d2)
near(a2.entryMm, 10, 1e-9, 'f2 entry'); near(a2.depthMm, 30, 1e-9, 'f2 depth'); near(a2.lateralMm, 10, 1e-9, 'f2 lat')
assert.equal(SR.contactLamp(a2, CH), 'yellow')
assert.equal(SR.contactLamp(SR.contactReport(s1, [0, 0, -0.1]), CH), 'red')        // [7]
const contacts = [{ a: 'A', capA: 'hips', b: 'B', capB: 'x', depth: 0.05 }, { a: 'A', capA: 'leg', b: 'B', capB: 'y', depth: 0.02 }]
assert.equal(SR.bodyOverlap(contacts, new Set(['A|hips'])), 0.02)                   // [8]
assert.equal(SR.bodyOverlap(contacts, new Set()), 0.05)
assert.deepEqual(SR.solveContactShift([]), [0, 0, 0])                                // [9]
assert.equal(SR.entryFrame([]), -1)
console.log('smoke_channel_contact: OK')
