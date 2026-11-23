#!/usr/bin/env node
/**
 * THE MOUTH APPROACH (owner 2026-11-24): a part the mouth accepts opens the mouth as it comes at it — before it
 * engages — and closes it with the same ramp as it leaves; only the jaw/morph (`mouthOpen`), never the surface.
 * `mouthOpen.ts` `mouthApproach` (the rule), `SecondaryMotion` (the front link's approach per mouth state, counted
 * while the gate passes), `FigureRuntime.driveMouth` (per occupant max(mouthOpenFor(r·w), approach·mouthOpenFor(r))).
 * Every number below is derived BY HAND (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_mouth_approach.mjs   (no server, no world; bundles the preview path with esbuild)
 *
 * [A1] THE RULE (R 0.02, F 0.05, α 30°; A = MOUTH_APPROACH_M 0.04, δ = MOUTH_APPROACH_CONE_DEG 15):
 *   s −0.09 → 0; −0.07 → 0.5; −0.05 → 1; 0.03 → 1; s −0.10 → 0 (beyond F + A);
 *   ρ at s −0.07: allowed R + 0.07·tan 45° = 0.09 → ρ 0.089 gives 0.5, ρ 0.091 gives 0;
 *   lever 45° → 0.5 (at the edge), 45.1° → 0.
 * FIXTURE (as `smoke_place_preview_partners.mjs`, metres, bind rotations identity): one template, Hips (0, 0.9, 0)
 *   → Spine2 (+0.4 y); a chain Hips → A1 (0, 0.9, 0.15) → A2 (+0.1 z) → A3 (+0.1 z), tip (0, 0.9, 0.45); body box
 *   x ±0.15, z ±0.45, y 0 … 1.7 (no rescale, no shift). P: motion group [A1, A2, A3], op appendage_chain, gain 0,
 *   gravity 0 (rigid), the chain's appendage capsules r 0.005 (the links' surface radius r = 0.005). Q: a declared
 *   channel with the MOUTH's id `mouth` on Hips, opening (0, 0.9, 0.12), bottom (0, 0.9, 0) → u = −z, D 0.12, R 0.02,
 *   cone 30°, funnel 0.05, accepts appendage_chain, min_length 1, kinds [k], open_height H 0.03 (no teeth), and a
 *   morph target `mouth_open` on its body. Q at the origin; P turned by π at (0, 0, z_P), its tip on the axis at
 *   z_P − 0.45: s = 0.12 − (z_P − 0.45) = 0.57 − z_P, ρ 0, lever 0°.
 *   IN, f = 1 … 60: z_P = 0.7015 − 0.002 f → s = −0.1315 + 0.002 f; OUT, f = 61 … 120: z_P = 0.5815 + 0.002 (f − 60)
 *   → s = −0.0115 − 0.002 (f − 60) (the 1.5 mm offset keeps every zone edge between two frames).
 * HAND-DERIVED (the whole part needs mouthOpenFor(0.005, 0.03) = (0.01 + 0.004)/0.03 = 0.466667):
 *   [A2] IN: approach = clamp((s + 0.09)/0.04) = clamp(0.05 f − 1.0375): mouth 0 at f ≤ 20, f 21 → 0.0125·0.466667 =
 *        0.005833, f 30 → 0.4625·… = 0.215833, f 40 → 0.9625·… = 0.449167, f 41 → 1 → 0.466667, held to f 60. The
 *        tip enters the funnel (s ≥ −0.05 ⇔ f ≥ 40.75) at f 41, the update after engages (f 42, w 1/12:
 *        mouthOpenFor(0.005/12) = 0.161111 < 0.466667). The surface is not touched while only approaching: Q has no
 *        opening at f ≤ 41, one from f 42 (w > 0). The morph's influence equals the value every frame.
 *   [A3] OUT: approach = clamp(1.9625 − 0.05 (f − 60)); the tip leaves the grown zone (s < −0.055 ⇔ f − 60 > 21.75)
 *        at f 82, the update after releases (f 83, w 11/12 → w(f) = (94 − f)/12, 0 from f 94):
 *        f 80 → 0.466667 (w 1); f 90 → w 4/12: mouthOpenFor(0.0016667) = 0.244444 vs approach 0.4625 → 0.215833 →
 *        0.244444; f 96 → w 0, approach 0.1625 → 0.075833; f 100 → 0.
 *   [A4] NEVER SNAPS: the largest change between two frames over the 120 is f 93 → 94: 0.161111 (w 1/12) →
 *        0.122500 (approach 0.2625) = 0.038611 (the ramp's slope 0.05·0.466667 = 0.023333, w's 0.027778).
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
async function loadPaths() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-mouth-approach-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: [
        `export { mountPlaceFigure, placeInteraction, placePhaseB } from '${ROOT}/frontend/src/tabs/poses/placeFigures';`,
        "export { COLLISION_VERSION, FIGURE_HEIGHT_M, mouthApproach, MOUTH_APPROACH_M, MOUTH_APPROACH_CONE_DEG } from '@anima/scene-render';",
      ].join('\n'), resolveDir: join(ROOT, 'frontend'), loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'paths.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'paths.mjs')
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}
const THREE = await import('three')
const { clone: skclone } = await import('three/examples/jsm/utils/SkeletonUtils.js')
const L = await loadPaths()
assert.equal(L.FIGURE_HEIGHT_M, 1.7)
let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
const near = (a, b, tol = 1e-6) => typeof a === 'number' && Math.abs(a - b) <= tol

// [A1] the rule
{
  const ch = { r: 0.02, funnel: 0.05, coneDeg: 30 }
  const got = [L.mouthApproach(-0.09, 0, 0, ch), L.mouthApproach(-0.07, 0, 0, ch), L.mouthApproach(-0.05, 0, 0, ch),
    L.mouthApproach(0.03, 0, 0, ch), L.mouthApproach(-0.1, 0, 0, ch), L.mouthApproach(-0.07, 0.089, 0, ch),
    L.mouthApproach(-0.07, 0.091, 0, ch), L.mouthApproach(-0.07, 0, 45, ch), L.mouthApproach(-0.07, 0, 45.1, ch)]
  const want = [0, 0.5, 1, 1, 0, 0.5, 0, 0.5, 0]
  check('[A1] the rule: A 0.04 m, δ 15°, linear 0 at −(F + A) … 1 at −F, widened cone and lever',
    L.MOUTH_APPROACH_M === 0.04 && L.MOUTH_APPROACH_CONE_DEG === 15 && got.every((v, i) => near(v, want[i], 1e-9)), got.map(v => v.toFixed(3)).join(' '))
}

const DEFAULTS = { freq_hz: 2, zeta: 1, gravity: 0, gravity_scale: 1, gain: 0,
  max_deg: 25, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1 }
const MOTION = { rev: 'm1', groups: { g: { ...DEFAULTS, bones: ['A1', 'A2', 'A3'], op: 'appendage_chain' } } }
function template() {
  const fig = new THREE.Group()
  const bones = []
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = `mixamorig${name}`; b.position.set(...at); (parent ?? fig).add(b); bones.push(b); return b
  }
  const hips = bone('Hips', null, [0, 0.9, 0])
  bone('Spine2', hips, [0, 0.4, 0])
  const a1 = bone('A1', hips, [0, 0, 0.15])
  const a2 = bone('A2', a1, [0, 0, 0.1])
  bone('A3', a2, [0, 0, 0.1])
  fig.updateMatrixWorld(true)
  const pos = [], si = []
  const tri = (pts, b) => { for (const p of pts) { pos.push(...p); si.push(b, 0, 0, 0) } }
  tri([[-0.15, 0, -0.1], [0.15, 0, 0.1], [0, 1.7, 0]], 0)
  tri([[0.15, 0, -0.1], [-0.15, 0, 0.1], [0, 1.7, 0]], 0)
  tri([[0, 0.9, -0.45], [0, 0.9, -0.44], [0.001, 0.9, -0.45]], 0)
  const ring = Array.from({ length: 6 }, (_, k) => [0.03 * Math.cos(k * Math.PI / 3), 0.9 + 0.03 * Math.sin(k * Math.PI / 3), 0.12])
  tri([ring[0], ring[1], ring[2]], 0); tri([ring[3], ring[4], ring[5]], 0)
  tri([ring[0], ring[2], ring[4]], 0); tri([ring[1], ring[3], ring[5]], 0)
  ;[2, 3].forEach((b, j) => tri([[0, 0.9, 0.15 + 0.1 * j], [0, 0.9, 0.25 + 0.1 * j], [0.001, 0.9, 0.2 + 0.1 * j]], b))
  tri([[0, 0.9, 0.35], [0, 0.9, 0.45], [0.001, 0.9, 0.4]], 4)
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(pos.map((_, i) => (i % 3 === 2 ? 1 : 0)), 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(si, 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(si.map((_, i) => (i % 4 === 0 ? 1 : 0)), 4))
  const morph = new THREE.Float32BufferAttribute(new Float32Array(pos.length), 3); morph.name = 'mouth_open'
  geo.morphAttributes.position = [morph]
  const body = new THREE.SkinnedMesh(geo, new THREE.MeshStandardMaterial()); body.name = 'body'
  body.updateMorphTargets()
  fig.add(body)
  fig.updateMatrixWorld(true)
  body.bind(new THREE.Skeleton(bones), body.matrixWorld)
  return fig
}
function collision(channel) {
  const caps = [{ id: 'torso', a: 'mixamorigHips', b: 'mixamorigSpine2', r: 0.12, region: 'torso' }]
  if (!channel) caps.push(
    { id: 'g:A1', a: 'mixamorigA1', b: 'mixamorigA2', r: 0.005, region: 'appendage' },
    { id: 'g:A2', a: 'mixamorigA2', b: 'mixamorigA3', r: 0.005, region: 'appendage' },
    { id: 'g:A3', a: 'mixamorigA3', b: 'mixamorigA3', b_pos: [0, 0.9, 0.45], r: 0.005, region: 'appendage' })
  return { version: L.COLLISION_VERSION, capsules: caps, ...(channel ? { channels: [{
    id: 'mouth', kind: 'channel', a: 'mixamorigHips', b: 'mixamorigHips', a_pos: [0, 0.9, 0.12], b_pos: [0, 0.9, 0],
    r: 0.02, cone_deg: 30, funnel: 0.05, accepts: ['appendage_chain'], min_length: 1, compress_min: 0.8,
    interaction_kinds: ['k'], suppress: ['torso'], open_height: 0.03, frame: { side: [1, 0, 0], up: [0, 1, 0], front: [0, 0, 1] },
    placement: 'declared', applied: null }] } : {}) }
}
const still = () => new THREE.AnimationClip('standing', 1,
  [new THREE.QuaternionKeyframeTrack('mixamorigSpine2.quaternion', [0, 1], [0, 0, 0, 1, 0, 0, 0, 1])])
const DT = 1 / 60
const zP = f => (f <= 60 ? 0.7015 - 0.002 * f : 0.5815 + 0.002 * (f - 60))
const make = (channel, motion) => L.mountPlaceFigure(THREE, skclone, template(),
  { collision: collision(channel), motion: () => (motion ? MOTION : undefined) })
const p = make(false, true), q = make(true, false)
const mixers = [p, q].map(fig => { const m = new THREE.AnimationMixer(fig.inst); m.clipAction(still()).play(); return m })
const interaction = L.placeInteraction('k', 'i1', ['P', 'Q'])
const entries = [{ name: 'P', interaction, figure: p.runtime }, { name: 'Q', interaction, figure: q.runtime }]
const state = { openingTurn: 0 }
let morphMesh = null
q.inst.traverse(o => { if (o.morphTargetDictionary?.mouth_open !== undefined) morphMesh = o })
const rows = [null]
let time = 0
for (let f = 1; f <= 120; f++) {
  time = (time + DT) % 1
  mixers.forEach(m => m.setTime(time))
  p.root.position.set(0, 0, zP(f)); p.root.rotation.set(0, Math.PI, 0, 'YXZ'); p.root.updateMatrixWorld(true)
  q.root.position.set(0, 0, 0); q.root.updateMatrixWorld(true)
  p.runtime.poseStep({ realDelta: DT }); q.runtime.poseStep({ realDelta: DT })
  const res = L.placePhaseB(entries, state, true)
  const iq = res.figures[1].inspection
  rows.push({ mouth: iq.mouthOpen, openings: iq.openings.length, morph: morphMesh.morphTargetInfluences[morphMesh.morphTargetDictionary.mouth_open],
    w: res.figures[0].inspection.engaged.find(e => e.channel === 'mouth')?.w ?? 0 })
}
const v = f => rows[f].mouth
const full = 0.466667
check('[A2] IN: 0 to f 20, f 21 0.005833, f 30 0.215833, f 40 0.449167, 0.466667 from f 41 to f 60',
  rows.slice(1, 21).every(r => r.mouth === 0) && near(v(21), 0.005833) && near(v(30), 0.215833) && near(v(40), 0.449167)
  && rows.slice(41, 61).every(r => near(r.mouth, full)), `f20 ${v(20)}, f21 ${v(21).toFixed(6)}, f30 ${v(30).toFixed(6)}, f40 ${v(40).toFixed(6)}, f42 w ${rows[42].w.toFixed(6)}`)
check('[A2] only the jaw while approaching: no surface opening to f 41, one from f 42 (w 1/12); the morph = the value',
  rows.slice(1, 42).every(r => r.openings === 0) && rows[42].openings === 1 && near(rows[42].w, 1 / 12, 1e-9)
  && rows.slice(1).every(r => near(r.morph, r.mouth, 1e-6)), `f41 openings ${rows[41].openings}, f42 ${rows[42].openings}`)
check('[A3] OUT: f 80 0.466667, f 83 w 11/12, f 90 0.244444, f 96 0.075833, f 100 0',
  near(v(80), full) && near(v(90), 0.244444) && near(v(96), 0.075833) && v(100) === 0 && near(rows[83].w, 11 / 12, 1e-9),
  `f80 ${v(80).toFixed(6)}, f83 w ${rows[83].w.toFixed(6)}, f90 ${v(90).toFixed(6)}, f96 ${v(96).toFixed(6)}, f100 ${v(100)}`)
let step = 0, at = 0
for (let f = 2; f <= 120; f++) { const d = Math.abs(v(f) - v(f - 1)); if (d > step) { step = d; at = f } }
check('[A4] never snaps: the largest step between frames is 0.038611 at f 93 → 94', near(step, 0.038611) && at === 94,
  `${step.toFixed(6)} at f ${at}`)
p.runtime.dispose(); q.runtime.dispose()
console.log(failures ? `${failures} check(s) failed` : 'all checks passed')
process.exit(failures ? 1 : 0)
