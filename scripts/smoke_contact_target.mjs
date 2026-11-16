#!/usr/bin/env node
/**
 * Ruling A139: contact targets of a pair clip (`packages/scene-render/src/contactTarget.ts`, `pairFit.ts`
 * findContact / contactSampleOf). Every expected number is derived BY HAND below (§ B5a).
 *
 * Usage: node scripts/smoke_contact_target.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * [1] hand_left: hand (0,1,0), middle1 (0.08,1,0), index1 (0.08,1,0.03), pinky1 (0.08,1,−0.03)
 *     → O = ½(hand + middle1) = (0.04, 1, 0); u = (pinky − index)/0.06 = (0, 0, −1); r 0.025; not provisional.
 * [2] without middle1: mid = ½(index + pinky) = (0.08, 1, 0) → the same O.
 * [3] head_front: head (0,1.5,0), headtop_end (0,1.7,0) → L 0.2, h (0,1,0); eyes (∓0.03, 1.6, 0.08) → mean − H =
 *     (0, 0.1, 0.08), minus its h part → (0, 0, 0.08) → f (0,0,1). O = H + 0.5·0.2·f + 0.15·0.2·h = (0, 1.53, 0.1);
 *     u = −f = (0, 0, −1); provisional.
 * [4] no eyes, headZ (0, 0.6, 0.8): minus h part → (0, 0, 0.8) → f (0,0,1) → the same O.
 * [5] no head → null; no pinky → null.
 * [6] findContact: chains [pair_tip, attached_part]; receiving with target hand_left → {chain 1, 'hand_left'} (a
 *     pair_tip chain never aims at a point target: only pair_tip → null); head_front missing → null; 'none' → null;
 *     'channel' with a channel accepting attached_part → chain 1 + its id.
 * [7] contactSampleOf on hand_left with base (0.04,1,−0.15) → tip (0.04,1,0.05): shaft +z, u (0,0,−1) flips to (0,0,1).
 * [8] solve against that hand: o (0.04,1,0), u (0,0,1), tips (0.05,1,0) and (0.05,1,0.05): entry frame 0 (s 0);
 *     M = diag(2, 2, 20), g = (0.02, 0, 0) → Δ = (−0.01, 0, 0); after: entry 0 mm, max lateral 0 mm.
 * [9] targetLamp r 0.025: entry 3 / lateral 20 → green; 30 / 20 → yellow (≤ 50 each); 60 / 20 → red; no frames → red.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-contact-target-'))
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
const v = (a, b, msg) => a.forEach((x, i) => near(x, b[i], 1e-9, `${msg}[${i}]`))
const hand = { lefthand: [0, 1, 0], lefthandmiddle1: [0.08, 1, 0], lefthandindex1: [0.08, 1, 0.03], lefthandpinky1: [0.08, 1, -0.03] }
const h1 = SR.targetFrame('hand_left', hand)                                                    // [1]
v(h1.o, [0.04, 1, 0], 'hand o'); v(h1.u, [0, 0, -1], 'hand u'); assert.equal(h1.r, 0.025); assert.equal(h1.provisional, false)
const { lefthandmiddle1: _m, ...noMid } = hand
v(SR.targetFrame('hand_left', noMid).o, [0.04, 1, 0], 'hand o no middle')                    // [2]
const head = { head: [0, 1.5, 0], headtop_end: [0, 1.7, 0], lefteye: [-0.03, 1.6, 0.08], righteye: [0.03, 1.6, 0.08] }
const hf = SR.targetFrame('head_front', head)                                                   // [3]
v(hf.o, [0, 1.53, 0.1], 'head o'); v(hf.u, [0, 0, -1], 'head u'); assert.equal(hf.provisional, true)
v(SR.targetFrame('head_front', { head: head.head, headtop_end: head.headtop_end, headZ: [0, 0.6, 0.8] }).o, [0, 1.53, 0.1], 'head o headZ') // [4]
assert.equal(SR.targetFrame('head_front', {}), null)                                            // [5]
assert.equal(SR.targetFrame('hand_left', { ...hand, lefthandpinky1: undefined }), null)
const seg = { a: [0.04, 1, -0.15], b: [0.04, 1, 0.05] }
const ent = { chains: [{ op: 'pair_tip', segments: [seg] }, { op: 'attached_part', segments: [seg] }], channels: [] }
const rec = { chains: [], channels: [{ id: 'B:c', o: [0, 0, 0], u: [0, 0, 1], accepts: ['attached_part'] }], targets: SR.targetFrames(hand) }
assert.deepEqual(SR.findContact(ent, rec, 'hand_left'), { chain: 1, channel: 'hand_left' })      // [6]
assert.equal(SR.findContact(ent, rec, 'head_front'), null)
assert.equal(SR.findContact(ent, rec, 'none'), null)
assert.deepEqual(SR.findContact(ent, rec, 'channel'), { chain: 1, channel: 'B:c' })
assert.equal(SR.findContact({ chains: [ent.chains[0]], channels: [] }, rec, 'hand_left'), null)
const smp = SR.contactSampleOf(ent, rec, { chain: 1, channel: 'hand_left' }, [0, 0, 0])            // [7]
v(smp.u, [0, 0, 1], 'grip u along shaft'); v(smp.o, [0.04, 1, 0], 'grip o')
const ss = [[0.05, 1, 0], [0.05, 1, 0.05]].map((tip) => ({ tip, base: [tip[0], tip[1], tip[2] - 0.2], o: [0.04, 1, 0], u: [0, 0, 1] }))
const d = SR.solveContactShift(ss)                                                                 // [8]
v(d, [-0.01, 0, 0], 'hand solve')
const rep = SR.contactReport(ss, d)
near(rep.entryMm, 0, 1e-9, 'entry'); near(rep.maxLateralMm, 0, 1e-9, 'lateral')
const R = (entryMm, maxLateralMm, frames = 3) => ({ frames, entryMm, maxLateralMm })            // [9]
assert.equal(SR.targetLamp(R(3, 20), 0.025), 'green')
assert.equal(SR.targetLamp(R(30, 20), 0.025), 'yellow')
assert.equal(SR.targetLamp(R(60, 20), 0.025), 'red')
assert.equal(SR.targetLamp(R(0, 0, 0), 0.025), 'red')
console.log('smoke_contact_target: OK')
