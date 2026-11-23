#!/usr/bin/env node
/**
 * THE BEND BEFORE THE OPENINGS (owner finding 2026-11-24, resting-blowjob: the part aligned by hand onto the mouth,
 * the mouth never opened). The chain bend (Ruling A145, `chainBend.ts`) is what aims an attached part into a
 * partner's channel or mouth. It ran AFTER phase B in both renderers, and the engagement zone (`stepEngagement`'s
 * input) was read from the chain before it: the unbent tip stayed 54–139 mm in front of the mouth, the bent one went up
 * to 6 mm in — never engaged, the mouth (Ruling A203) and the surface opening never saw it. Now
 *   - `SecondaryMotion.bendChain` reads THE ZONE again after it turns the bones (`zoneOf`), so the next update
 *     engages on the part as rendered, and
 *   - `runFigureFrame` calls the caller's `afterSecondary` (the bend) after every secondary motion and BEFORE the
 *     openings, so the opening, the mouth and the readout read the bent segments in the same frame.
 * Every number below is derived BY HAND from the fixture (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_bend_engagement.mjs   (no server, no world; bundles the preview path with esbuild; the
 *        old-code proof reads commit 2e5c6ee5f57a37e5276dad243581bdfd4261029a through `git archive` into a temp dir)
 *
 * FIXTURE (metres; every bind rotation identity). One body template: Hips (0, 0.9, 0) → Spine2 (+0.4 y); a chain
 *   Hips → A1 at (0, 0.9, 0.15) → A2 (+0.1 x) → A3 (+0.1 x), its tip at (0.3, 0.9, 0.15) — the chain points SIDEWAYS
 *   (+x), not ahead. Body box x ±0.3, z ±0.151 (twin vertices at x −0.3 and z −0.151; centred on x = z = 0), y 0 … 1.7 = FIGURE_HEIGHT_M: `anchorFigureBind`
 *   scales by 1 and moves nothing. P (the entering figure) has motion group g = [A1, A2, A3], op appendage_chain,
 *   gain 0, gravity 0 (rigid: every frame its bones are the rest), capsules torso Hips→Spine2 r 0.12 and the chain's
 *   `appendage` capsules r 0.005. Q (the receiver) has the torso and ONE channel `pkg:chan` on Hips: opening
 *   (0, 0.9, 0.12), bottom (0, 0.9, 0) → u = −z, D 0.12, R 0.02, cone 30°, funnel F 0.05, accepts appendage_chain,
 *   min_length 1, kinds [k]. Q stands at the origin; P at (0, 0, 0.55) turned by π, both in the interaction {i1, k}.
 *   P's chain in the world: A1 at (0, 0.9, 0.40), the links along −x: A2 (−0.1, 0.9, 0.40), A3 (−0.2, …), tip (−0.3, …).
 * THE BEND (the caller's, every frame): chain 0, joint 0 (A1), q = rotation about +y by −90° = (0, −√½, 0, √½):
 *   R_y(−90°)(x, y, z) = (−z, y, x) takes −x to −z, so the bent links run from A1 along −z: A2 z 0.30, A3 z 0.20,
 *   tip z 0.10, all at x 0, y 0.9 — on the channel axis. s = (P − O)·u = 0.12 − z: A1 −0.28, A2 −0.18, A3 −0.08,
 *   tip +0.02 (inside C: 0 ≤ s ≤ D, ρ 0 ≤ R; the channel grown for the part stays R since r_c 0.005 + 5 mm < 0.02).
 *   The last link's lever A3 → tip is −z = u: 0° ≤ 30°. The unbent link tips have s = 0.12 − 0.40 = −0.28 < −F: out.
 * HAND-DERIVED:
 *   [1] ENGAGEMENT on the bent part: the zone of frame 1's bend (inside) is what frame 2's update steps on →
 *       first w > 0 at f 2, w = (1/60)/0.2 = 1/12; w = 1 from f 13 (12 engaged updates).
 *   [2] THE OPENING READS THE BENT PART: Q's readout of P in pkg:chan, insertionM = max over the links of
 *       (max s + r) = 0.02 + 0.005·w → 25.000 mm at w = 1 (f ≥ 13); the radius the opening widens to 0.005·w → 5.000 mm.
 *   [3] CONTROL, the bend AFTER phase B (the old order) on the new code: the zone refresh alone still engages at f 2
 *       (w 1/12), but the openings of each frame ran on the unbent links: max s + r = −0.28 + 0.005 < 0 →
 *       insertionM 0.000 mm every frame — why the bend moved into phase B.
 *   [4] FAILS ON 2e5c6ee5f: the old code, bend after phase B: the zone is never read on the bent part → w 0 on all
 *       60 frames, no readout.
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtemp, rm, writeFile, mkdir } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
const OLD = '2e5c6ee5f57a37e5276dad243581bdfd4261029a'

/** The preview path of the working tree (ref null) or of commit `ref` (git archive into a temp dir). */
async function loadPaths(ref) {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-bend-engagement-'))
  try {
    let base = ROOT
    if (ref) {
      base = join(dir, 'src')
      await mkdir(base, { recursive: true })
      const tar = execFileSync('git', ['-C', ROOT, 'archive', ref, 'packages/scene-render/src', 'frontend/src/tabs/poses/placeFigures.ts'],
        { maxBuffer: 1 << 28 })
      execFileSync('tar', ['-x', '-C', base], { input: tar })
    }
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: [
        `export { mountPlaceFigure, placeInteraction, placePhaseB } from '${base}/frontend/src/tabs/poses/placeFigures';`,
        `export { COLLISION_VERSION, FIGURE_HEIGHT_M } from '${base}/packages/scene-render/src/index';`,
      ].join('\n'), resolveDir: join(ROOT, 'frontend'), loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false, alias: { '@anima/scene-render': join(base, 'packages/scene-render/src/index.ts') },
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
  const a2 = bone('A2', a1, [0.1, 0, 0])
  bone('A3', a2, [0.1, 0, 0])
  fig.updateMatrixWorld(true)
  const pos = [], si = []
  const tri = (pts, b) => { for (const p of pts) { pos.push(...p); si.push(b, 0, 0, 0) } }
  tri([[-0.15, 0, -0.1], [0.15, 0, 0.1], [0, 1.7, 0]], 0)
  tri([[0.15, 0, -0.1], [-0.15, 0, 0.1], [0, 1.7, 0]], 0)
  tri([[-0.3, 0.9, 0.15], [-0.29, 0.9, 0.15], [-0.3, 0.9, -0.151]], 0)   // the twins of the chain's reach: box x ±0.3, z ±0.151
  const ring = Array.from({ length: 6 }, (_, k) => [0.03 * Math.cos(k * Math.PI / 3), 0.9 + 0.03 * Math.sin(k * Math.PI / 3), 0.12])
  tri([ring[0], ring[1], ring[2]], 0); tri([ring[3], ring[4], ring[5]], 0)
  tri([ring[0], ring[2], ring[4]], 0); tri([ring[1], ring[3], ring[5]], 0)
  // the chain's own skin (vertices along each link, skinned 1 to it) — its levers for the secondary motion
  ;[2, 3, 4].forEach((b, j) => tri([[0.1 * j, 0.9, 0.15], [0.1 * j + 0.1, 0.9, 0.15], [0.1 * j + 0.05, 0.9, 0.151]], b))
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(pos.map((_, i) => (i % 3 === 2 ? 1 : 0)), 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(si, 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(si.map((_, i) => (i % 4 === 0 ? 1 : 0)), 4))
  const body = new THREE.SkinnedMesh(geo, new THREE.MeshStandardMaterial()); body.name = 'body'
  fig.add(body)
  fig.updateMatrixWorld(true)
  body.bind(new THREE.Skeleton(bones), body.matrixWorld)
  return fig
}
function collision(L, channel) {
  const caps = [{ id: 'torso', a: 'mixamorigHips', b: 'mixamorigSpine2', r: 0.12, region: 'torso' }]
  if (!channel) caps.push(
    { id: 'g:A1', a: 'mixamorigA1', b: 'mixamorigA2', r: 0.005, region: 'appendage' },
    { id: 'g:A2', a: 'mixamorigA2', b: 'mixamorigA3', r: 0.005, region: 'appendage' },
    { id: 'g:A3', a: 'mixamorigA3', b: 'mixamorigA3', b_pos: [0.3, 0.9, 0.15], r: 0.005, region: 'appendage' })
  return { version: L.COLLISION_VERSION, capsules: caps, ...(channel ? { channels: [{
    id: 'pkg:chan', kind: 'channel', a: 'mixamorigHips', b: 'mixamorigHips', a_pos: [0, 0.9, 0.12], b_pos: [0, 0.9, 0],
    r: 0.02, cone_deg: 30, funnel: 0.05, accepts: ['appendage_chain'], min_length: 1, compress_min: 0.8,
    interaction_kinds: ['k'], suppress: ['torso'], frame: { side: [1, 0, 0], up: [0, 1, 0], front: [0, 0, 1] },
    placement: 'declared', applied: null }] } : {}) }
}
const still = () => new THREE.AnimationClip('standing', 1,
  [new THREE.QuaternionKeyframeTrack('mixamorigSpine2.quaternion', [0, 1], [0, 0, 0, 1, 0, 0, 0, 1])])
const FRAMES = 60, DT = 1 / 60
const BEND = [{ joint: 0, q: [0, -Math.SQRT1_2, 0, Math.SQRT1_2] }]

/** 60 frames of the preview path; `mode` 'inside' = the bend as `afterSecondary`, 'after' = after phase B. Per frame
 *  P's engagement weight in Q's pkg:chan and Q's readout of it (null = none). */
function run(L, mode) {
  assert.equal(L.FIGURE_HEIGHT_M, 1.7, 'the fixture is 1.70 m tall so the owner does not rescale it')
  const make = (channel, motion) => L.mountPlaceFigure(THREE, skclone, template(),
    { collision: collision(L, channel), motion: () => (motion ? MOTION : undefined) })
  const p = make(false, true), q = make(true, false)
  const mixers = [p, q].map(fig => { const m = new THREE.AnimationMixer(fig.inst); m.clipAction(still()).play(); return m })
  const interaction = L.placeInteraction('k', 'i1', ['P', 'Q'])
  const state = { openingTurn: 0 }
  const entries = [{ name: 'P', interaction, figure: p.runtime }, { name: 'Q', interaction, figure: q.runtime }]
  const bend = () => p.runtime.bendChain(0, BEND)
  const out = []
  let time = 0
  for (let f = 1; f <= FRAMES; f++) {
    time = (time + DT) % 1
    mixers.forEach(m => m.setTime(time))
    p.root.position.set(0, 0, 0.55); p.root.rotation.set(0, Math.PI, 0, 'YXZ'); p.root.updateMatrixWorld(true)
    q.root.position.set(0, 0, 0); q.root.updateMatrixWorld(true)
    p.runtime.poseStep({ realDelta: DT }); q.runtime.poseStep({ realDelta: DT })
    const res = L.placePhaseB(entries, state, true, mode === 'inside' ? { afterSecondary: bend } : {})
    if (mode === 'after') bend()
    const w = res.figures[0].inspection.engaged.find(e => e.channel === 'pkg:chan')?.w ?? 0
    const rd = res.figures[1].inspection.readouts.find(r => r.channel === 'pkg:chan') ?? null
    const open = res.figures[1].inspection.openings.find(o => o.channel === 'pkg:chan') ?? null
    out.push({ w, insertion: rd ? rd.insertionM : null, radius: open ? open.radius : null })
  }
  p.runtime.dispose(); q.runtime.dispose()
  return out
}

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
const near = (a, b, tol) => a !== null && a !== undefined && Math.abs(a - b) <= tol
const NEW = await loadPaths(null)
const inside = run(NEW, 'inside')
const firstW = inside.findIndex(x => x.w > 0) + 1, fullW = inside.findIndex(x => near(x.w, 1, 1e-9)) + 1
check('[1] engaged on the bent part: first w > 0 at f 2 (1/12), w = 1 from f 13',
  firstW === 2 && near(inside[1].w, 1 / 12, 1e-9) && fullW === 13, `first ${firstW} (w ${inside[firstW - 1]?.w.toFixed(6)}), full ${fullW}`)
const late = inside.slice(12)
check('[2] the opening reads the bent part: insertion 25.000 mm, opening radius 5.000 mm from f 13',
  late.every(x => near(x.insertion, 0.025, 1e-6) && near(x.radius, 0.005, 1e-6)),
  `f13 insertion ${(late[0].insertion * 1000).toFixed(3)} mm, radius ${(late[0].radius * 1000).toFixed(3)} mm`)
const after = run(NEW, 'after')
const firstA = after.findIndex(x => x.w > 0) + 1
check('[3] control, bend after phase B: engages at f 2 (the zone refresh), but every opening ran on the unbent links (insertion 0)',
  firstA === 2 && near(after[1].w, 1 / 12, 1e-9) && after.slice(1).every(x => near(x.insertion, 0, 1e-9)),
  `first ${firstA}, max insertion ${Math.max(...after.map(x => x.insertion ?? 0)) * 1000} mm`)
const OLDL = await loadPaths(OLD)
const old = run(OLDL, 'after')
check(`[4] fails on ${OLD.slice(0, 9)}: never engaged, no readout`, old.every(x => x.w === 0 && x.insertion === null),
  `max w ${Math.max(...old.map(x => x.w))}`)
console.log(failures ? `${failures} check(s) failed` : 'all checks passed')
process.exit(failures ? 1 : 0)
