#!/usr/bin/env node
/**
 * Ruling A159: the MOUTH OPENING (`packages/scene-render/src/contactTarget.ts` `mouthChannel`, `channels.ts`
 * `bindChannels`, `pairFit.ts` `findContact`) and the opening widening to the entering part's SURFACE radius
 * (`channelOpening.ts`, collision v8 `r_surface`). Every expected number is derived BY HAND below (§ B5a).
 *
 * Usage: node scripts/smoke_mouth_opening.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * [1] mouthChannel: head (0,1.5,0), headtop_end (0,1.7,0), eyes (∓0.03, 1.6, 0.08) → L 0.2, h (0,1,0), f (0,0,1):
 *     O = H + 0.5·0.2·f + 0.15·0.2·h = (0, 1.53, 0.1); u = −f = (0,0,−1); D = 0.5·0.2 = 0.1; R = 0.1·0.2 = 0.02;
 *     F = 0.15·0.2 = 0.03; α 35°; accepts [attached_part, appendage_chain]; minLength 0; compressMin 0.6; kinds null;
 *     suppress = the set passed in.
 * [2] bindChannels on a figure with only head bones (Head at (0,1.5,0), HeadTop_End local (0,0.2,0), eyes local
 *     (∓0.03, 0.1, 0.08)) and a payload without channels: one channel, the mouth, O (0,1.53,0.1); suppress = the
 *     payload's head-region capsule ids {head} (not left_thigh). Figure moved to x = 1 → update() → O (1, 1.53, 0.1).
 *     Scaled ×0.5 about the origin (head (0, 0.75, 0), L 0.1) → O (0, 0.765, 0.05), R 0.01, D 0.05.
 *     A figure without a head and without declared channels → null; another version → null.
 * [2b] Only a Head bone (no head-top end, no eyes — the common rig): L = 0.2 × the head's world scale, h = its +Y,
 *     f = its +Z. Unrotated at (0,1.5,0), figure ×0.5 → head (0,0.75,0), L 0.1: O = (0,0.75,0) + 0.05·(0,0,1) +
 *     0.015·(0,1,0) = (0, 0.765, 0.05), R 0.01. Head turned +90° about x (local Y → world +Z, local Z → world −Y),
 *     scale 1: h (0,0,1), f (0,−1,0): O = (0,1.5,0) + 0.1·(0,−1,0) + 0.03·(0,0,1) = (0, 1.4, 0.03), u (0, 1, 0).
 * [3] findContact against channels [declared 'B:c' accepting attached_part, mouth]: 'channel' → 'B:c'; 'mouth' →
 *     'mouth'. Against [mouth] only: 'channel' → null (the mouth is never a declared channel), 'mouth' → 'mouth'.
 *     contactSampleOf on the mouth: o (0,1.53,0.1), u (0,0,−1) unchanged (not a grip), channel = true.
 * [4] THICKNESS. A part link with core r_c 0.025, surface r_s 0.030, state girth 1.2, entering the mouth of [1] along
 *     its axis; a face vertex P on the opening plane (s = 0), 0.01 m off the axis. m = 0.002, band floor 0.015, K 1.5,
 *     channel R 0.02.
 *     OLD (opening around the core): r = 0.025·1.2 = 0.030 → T = 0.032, B = max(0.015, 1.5·0.030) = 0.045,
 *       b = 0.077; f(0.01) = 0.01 + 0.032·(1 − 0.01/0.077)² = 0.01 + 0.032·(67/77)² = 0.01 + 0.032·0.7571260 =
 *       0.0342280 — 1.772 mm INSIDE the part's surface (0.036).
 *     NEW (around the surface): r = 0.030·1.2 = 0.036 → T = 0.038, B = 1.5·0.036 = 0.054, b = 0.092;
 *       f(0.01) = 0.01 + 0.038·(82/92)² = 0.01 + 0.038·0.7944234 = 0.0401881 — 4.188 mm outside it; displacement
 *       |Δ| = 0.0301881 along +x (P − Q).
 *     On the axis the rim opens to T: f(0) = 0.038 ≥ 0.036.
 * [5] The mouth's depth scale: tip at s 0.2, s_e 0, r_c 0.036 → floor 0.1 − 0.036 = 0.064, (0.064 − 0)/(0.2 − 0) = 0.32
 *     → clamped to compressMin 0.6. Tip at s 0.07, s_e 0: (0.064)/(0.07) = 0.9142857.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function load() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-mouth-opening-'))
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

const SR = await load()
const THREE = await import(join(ROOT, 'node_modules/three/build/three.module.js'))
let failed = 0
const check = (label, ok, got = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${ok ? '' : `  (got ${got})`}`)
  if (!ok) failed++
}
const near = (a, b, eps) => Math.abs(a - b) <= eps
const vnear = (a, b, eps) => a.length === b.length && a.every((x, i) => near(x, b[i], eps))
const fmt = (v) => `[${v.map((x) => x.toFixed(6)).join(', ')}]`

// [1]
const head = { head: [0, 1.5, 0], headtop_end: [0, 1.7, 0], lefteye: [-0.03, 1.6, 0.08], righteye: [0.03, 1.6, 0.08] }
const sup = new Set(['head'])
const m = SR.mouthChannel(head, sup)
check('[1] O (0, 1.53, 0.1), u (0, 0, −1)', vnear(m.o, [0, 1.53, 0.1], 1e-9) && vnear(m.u, [0, 0, -1], 1e-9), fmt(m.o))
check('[1] D 0.1, R 0.02, F 0.03, α 35', near(m.depth, 0.1, 1e-12) && near(m.r, 0.02, 1e-12) && near(m.funnel, 0.03, 1e-12)
  && m.coneDeg === 35, JSON.stringify(m))
check('[1] gates: accepts both part ops, minLength 0, compressMin 0.6, kinds null, suppress passed',
  m.accepts.join() === 'attached_part,appendage_chain' && m.minLength === 0 && m.compressMin === 0.6 && m.kinds === null
  && m.suppress === sup && m.id === 'mouth')

// [2]
const bone = (name, x, y, z) => { const b = new THREE.Bone(); b.name = name; b.position.set(x, y, z); return b }
const H = bone('mixamorig:Head', 0, 1.5, 0)
H.add(bone('mixamorig:HeadTop_End', 0, 0.2, 0), bone('mixamorig:LeftEye', -0.03, 0.1, 0.08), bone('mixamorig:RightEye', 0.03, 0.1, 0.08))
const fig = new THREE.Group(); fig.add(H); fig.updateMatrixWorld(true)
const payload = { version: SR.COLLISION_VERSION, capsules: [
  { id: 'head', a: 'mixamorig:Head', b: 'mixamorig:Head', r: 0.075, region: 'head' },
  { id: 'left_thigh', a: 'LeftUpLeg', b: 'LeftLeg', r: 0.08, region: 'leg' }] }
const bound = SR.bindChannels(THREE, fig, payload)
const c0 = bound?.channels
check('[2] one channel, the mouth, O (0, 1.53, 0.1)', !!c0 && c0.length === 1 && c0[0].id === 'mouth'
  && vnear(c0[0].o, [0, 1.53, 0.1], 1e-6), c0 ? JSON.stringify(c0.map((c) => [c.id, c.o])) : 'null')
check('[2] suppress = the head capsules', !!c0 && c0[0].suppress.has('head') && !c0[0].suppress.has('left_thigh'))
fig.position.set(1, 0, 0); fig.updateMatrixWorld(true); bound.update()
check('[2] moved: O (1, 1.53, 0.1)', vnear(bound.channels[0].o, [1, 1.53, 0.1], 1e-6), fmt(bound.channels[0].o))
fig.position.set(0, 0, 0); fig.scale.setScalar(0.5); fig.updateMatrixWorld(true); bound.update()
const cs = bound.channels[0]
check('[2] ×0.5: O (0, 0.765, 0.05), R 0.01, D 0.05', vnear(cs.o, [0, 0.765, 0.05], 1e-6) && near(cs.r, 0.01, 1e-6)
  && near(cs.depth, 0.05, 1e-6), JSON.stringify({ o: cs.o, r: cs.r, d: cs.depth }))
const bare = new THREE.Group(); bare.add(bone('mixamorig:Hips', 0, 1, 0)); bare.updateMatrixWorld(true)
check('[2] no head, no declared channel → null', SR.bindChannels(THREE, bare, payload) === null)
check('[2] another version → null', SR.bindChannels(THREE, fig, { ...payload, version: SR.COLLISION_VERSION - 1 }) === null)

// [2b]
const lone = (rx, k) => {
  const g = new THREE.Group(); const b = bone('mixamorig:Head', 0, 1.5, 0); b.rotation.x = rx; g.add(b)
  g.scale.setScalar(k); g.updateMatrixWorld(true); return SR.bindChannels(THREE, g, payload)?.channels[0]
}
const l1 = lone(0, 0.5), l2 = lone(Math.PI / 2, 1)
check('[2b] head only, ×0.5: O (0, 0.765, 0.05), R 0.01', !!l1 && vnear(l1.o, [0, 0.765, 0.05], 1e-6) && near(l1.r, 0.01, 1e-9),
  l1 ? fmt(l1.o) : 'null')
check('[2b] head turned 90° about x: O (0, 1.4, 0.03), u (0, 1, 0)', !!l2 && vnear(l2.o, [0, 1.4, 0.03], 1e-6)
  && vnear(l2.u, [0, 1, 0], 1e-6), l2 ? fmt(l2.o) + fmt(l2.u) : 'null')

// [3]
const seg = { a: [0, 1.53, 0.3], b: [0, 1.53, 0.12] }
const ent = { chains: [{ op: 'attached_part', segments: [seg] }], channels: [] }
const declared = { id: 'B:c', o: [0, 1, 0], u: [0, 0, 1], accepts: ['attached_part'] }
const both = { chains: [], channels: [declared, m] }, onlyMouth = { chains: [], channels: [m] }
check('[3] channel → the declared one', SR.findContact(ent, both, 'channel')?.channel === 'B:c')
check('[3] mouth → the mouth', SR.findContact(ent, both, 'mouth')?.channel === 'mouth')
check('[3] only a mouth: channel → null, mouth → mouth', SR.findContact(ent, onlyMouth, 'channel') === null
  && SR.findContact(ent, onlyMouth, 'mouth')?.channel === 'mouth')
const smp = SR.contactSampleOf(ent, onlyMouth, { chain: 0, channel: 'mouth' }, [0, 0, 0])
check('[3] sample: o, u unchanged, channel true', vnear(smp.o, [0, 1.53, 0.1], 1e-9) && vnear(smp.u, [0, 0, -1], 1e-9)
  && smp.channel === true, JSON.stringify(smp))

// [4]
const P = [0.01, 1.53, 0.1]
const axisSeg = (r) => [{ a: [0, 1.53, 0.2], b: [0, 1.53, 0.05], r }]
const oldD = SR.openedDistance(0.01, 0.025 * 1.2, {}, m.r)
const newD = SR.openedDistance(0.01, 0.030 * 1.2, {}, m.r)
check('[4] old: f(0.01) = 0.0342280 (1.772 mm inside the 0.036 surface)', near(oldD, 0.0342280, 1e-7), oldD.toFixed(7))
check('[4] new: f(0.01) = 0.0401881 (4.188 mm outside)', near(newD, 0.0401881, 1e-7), newD.toFixed(7))
const disp = SR.openingDisplacement(P, m, axisSeg(0.036))
check('[4] displacement (0.0301881, 0, 0)', !!disp && vnear(disp, [0.0301881, 0, 0], 1e-7), disp ? fmt(disp) : 'null')
check('[4] rim on the axis opens to T = 0.038', near(SR.openedDistance(0, 0.036, {}, m.r), 0.038, 1e-12))

// [5]
check('[5] depth scale clamps at 0.6', near(SR.depthScale(0.2, 0, m, 0.036), 0.6, 1e-12), SR.depthScale(0.2, 0, m, 0.036))
check('[5] depth scale 0.9142857', near(SR.depthScale(0.07, 0, m, 0.036), 0.064 / 0.07, 1e-12), SR.depthScale(0.07, 0, m, 0.036))

console.log(failed ? `smoke_mouth_opening: ${failed} FAILED` : 'smoke_mouth_opening: OK')
process.exit(failed ? 1 : 0)
