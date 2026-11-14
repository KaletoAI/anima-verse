#!/usr/bin/env node
/**
 * The 3D client's per-strand hair wiring (strand-hair plan 2026-11-13 Task 9, spec § 6.2.2):
 * `client3d/src/scene/strandBudget.ts` `strandCandidates` (what `NpcManager.tickStrandHair` hands the budget) and
 * `Figure.prepareStrandHair` / `setStrandHair` / `setFirstPerson` in `client3d/src/scene/figures.ts`. Hand-derived.
 *
 * Usage: node scripts/smoke_client_strand_wiring.mjs   (no server, no world; bundles the client with esbuild)
 *
 * [1] CANDIDATES. Camera at the origin; figures a at (3, 0, 0) full tier with a record, b at (0, 0, 5) low tier
 *     with a record, c at (0, 0, −6) full tier without a record: candidates == [{name 'a', distance 3, costMs 6.5,
 *     running false}] — the distance tier carries no binding, a figure without a record has nothing to run.
 * [2] FIRST PERSON. d at (2, 0, 0), full tier with a record, the camera's own body in first person: not a
 *     candidate (the shrunk head hides the hair); the list stays [a].
 * FIGURE FIXTURE (as `scripts/smoke_strand_hair_handle.mjs`): Hips (0,0,0) → Spine2 (0,1.30,0) → Neck (0,1.45,0)
 *   → Head (0,1.55,0); a body mesh; a hair garment (`garment_hair_fixture`, kind hair) of 2 cards × 17 rows × 2
 *   vertices + a 4-vertex cap with `_strand_card` / `_strand_u`; capsules `head` (Neck→Head r 0.2) and `torso`
 *   (Spine2→Neck r 0.12); motion {rev 'm1', groups {hair_c00 (hair), tail}}; the record of 2 cards.
 * [3] Figure(model) with `loadStrandRecord` → the record: prepareStrandHair() true; setStrandHair(true) →
 *     strandRunning, the handle enabled, the figure's hair mesh wears the TEMPLATE's hair material again (out of the
 *     garment push — before it wore this figure's patched clone) and after one update the secondary motion is
 *     configured with rev 'm1:strands' (the hair groups dropped). strandCostMs is the handle's cost.
 * [4] setFirstPerson(true) turns it off: strandRunning false, the hair mesh back on the template geometry, its
 *     patched clone back; one update later the rev is 'm1' again (the chains back). setStrandHair(true) in first
 *     person stays off.
 * [5] REVIEW FOCUS 2. A record that names 1 card while the mesh's `_strand_card` reaches 2: prepareStrandHair()
 *     false twice, ONE console warning, no handle; setStrandHair(true) leaves the figure on its chains.
 * [6] A low-tier figure never prepares (no handle, no download asked: the loader is not called).
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function loadClient() {
  const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-strand-'))
  try {
    const src = join(ROOT, 'client3d/src')
    const entry = [
      `export { strandCandidates } from '${src}/scene/strandBudget';`,
      `export { Figure } from '${src}/scene/figures';`,
      `export { COLLISION_VERSION } from '${join(ROOT, 'packages/scene-render/src/collision')}';`,
    ].join('\n')
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: join(ROOT, 'client3d'), loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'client.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'client.mjs')
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}

const THREE = await import('three')
const { strandCandidates, Figure, COLLISION_VERSION } = await loadClient()

// [1] / [2] candidates
{
  const view = (name, [x, y, z], tier, hasRecord, firstPerson = false) =>
    ({ name, position: { x, y, z }, tier, hasRecord, firstPerson, costMs: 6.5, running: false })
  const figs = [view('a', [3, 0, 0], 'full', true), view('b', [0, 0, 5], 'low', true),
    view('c', [0, 0, -6], 'full', false)]
  const got = strandCandidates(figs, { x: 0, y: 0, z: 0 })
  check('[1] only the full-tier figure with a record: [a at 3 m]',
    JSON.stringify(got) === JSON.stringify([{ name: 'a', distance: 3, costMs: 6.5, running: false }]), JSON.stringify(got))
  const withOwn = strandCandidates([...figs, view('d', [2, 0, 0], 'full', true, true)], { x: 0, y: 0, z: 0 })
  check('[2] the own body in first person is no candidate', withOwn.map(c => c.name).join() === 'a',
    withOwn.map(c => c.name).join())
}

// --- the figure fixture -------------------------------------------------------------------------------------------
const R = 17, XK = [-0.03, 0.03]
const PARAMS = { damping: 0.04, stiffness: 1.0, bend: 0.15, iterations: 6, root_deg: 10, root_frac: 0.2,
  fly_soft: true, fly_arc: 0.30, tether: true, tether_r0: 0.015, tether_r1: 0.06, tether_head: 0.012,
  head_clr: 0.03, face_box: true }
const CAPSULES = [
  { id: 'head', a: 'mixamorig:Neck', b: 'mixamorig:Head', r: 0.2, region: 'head' },
  { id: 'torso', a: 'mixamorig:Spine2', b: 'mixamorig:Neck', r: 0.12, region: 'torso' },
]
function record(cards = 2) {
  const rest = [], pins = [], freeArc = [], freeFrac = [], w = []
  for (let k = 0; k < cards; k++) {
    pins.push(2)
    for (let i = 0; i < R; i++) {
      rest.push(XK[k], 1.60 - 0.02 * i, -0.10)
      freeArc.push(i < 2 ? 0 : 0.02 * (i - 1)); freeFrac.push(i < 2 ? 0 : (i - 1) / 15); w.push(1)
    }
  }
  return { version: 1, item_id: 'hair_fixture', fsig: '0123456789ab', mode: 'hairdeck', fit_sha256: 'f'.repeat(64),
    frame: 'head_bind', head_bone: 'mixamorig:Head', rows: R, cards, rest, pins, free_arc: freeArc,
    free_frac: freeFrac, follow: { bones: ['mixamorig:Head'], w }, ear_y: 1.50,
    face_box: [-0.06, 0.06, 1.48, 1.66, 0.05], eye_box: [-0.04, 0.04, 1.55, 1.64, 0.05],
    sdf: { dims: [2, 2, 2], lo: [-0.2, 1.3, -0.2], vox: 0.4, order: 'x_fastest', unit: 'mm_int8',
      data: Buffer.from(new Int8Array(8).fill(127).buffer).toString('base64') },
    capsules: { version: COLLISION_VERSION, capsules: CAPSULES, scales: {} }, params: PARAMS,
    vertex_attributes: { card: '_STRAND_CARD', u: '_STRAND_U' } }
}
function template() {
  const fig = new THREE.Group()
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = name; b.position.set(...at); (parent ?? fig).add(b); return b
  }
  const hips = bone('mixamorig:Hips', null, [0, 0, 0])
  const spine = bone('mixamorig:Spine2', hips, [0, 1.30, 0])
  const neck = bone('mixamorig:Neck', spine, [0, 0.15, 0])
  const head = bone('mixamorig:Head', neck, [0, 0.10, 0])
  fig.updateMatrixWorld(true)
  const skeleton = new THREE.Skeleton([hips, spine, neck, head])
  const bodyGeo = new THREE.BufferGeometry()
  bodyGeo.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 0.3, 0, 0, 0, 1.7, 0], 3))
  bodyGeo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Array(12).fill(0), 4))
  bodyGeo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
  const body = new THREE.SkinnedMesh(bodyGeo, new THREE.MeshStandardMaterial()); body.name = 'body'
  const pos = [], nrm = [], card = [], u = [], si = [], sw = []
  for (let k = 0; k < 2; k++) for (let i = 0; i < R; i++) for (const s of [-1, 1]) {
    pos.push(XK[k] + s * 0.004, 1.60 - 0.02 * i, -0.10); nrm.push(0, 0, -1)
    card.push(k + 1); u.push(i); si.push(2, 3, 0, 0); sw.push(0.5, 0.5, 0, 0)
  }
  for (const [x, z] of [[-0.02, -0.02], [0.02, -0.02], [0.02, 0.02], [-0.02, 0.02]]) {
    pos.push(x, 1.695, z); nrm.push(0, 1, 0); card.push(0); u.push(0); si.push(3, 0, 0, 0); sw.push(1, 0, 0, 0)
  }
  const hairGeo = new THREE.BufferGeometry()
  hairGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  hairGeo.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3))
  hairGeo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(si, 4))
  hairGeo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(sw, 4))
  hairGeo.setAttribute('_strand_card', new THREE.Uint16BufferAttribute(card, 1))
  hairGeo.setAttribute('_strand_u', new THREE.Float32BufferAttribute(u, 1))
  const hair = new THREE.SkinnedMesh(hairGeo, new THREE.MeshStandardMaterial()); hair.name = 'hair'
  const garment = new THREE.Group()
  garment.name = 'garment_hair_fixture'
  garment.userData.garment = { kind: 'hair' }
  garment.add(hair)
  fig.add(body, garment)
  fig.updateMatrixWorld(true)
  body.bind(skeleton, body.matrixWorld)
  hair.bind(skeleton, hair.matrixWorld)
  return { fig, hair }
}
const MOTION = { rev: 'm1', groups: {
  hair_c00: { bones: ['HairGen_c00_00'], hair: true, freq_hz: 1, zeta: 0.5 },
  tail: { bones: ['Tail_00'], freq_hz: 1, zeta: 0.5 } } }
function model(tpl, tier = 'full') {
  return { motion: { payload: MOTION }, collision: { version: COLLISION_VERSION, capsules: CAPSULES }, footPose: null,
    hairStrands: tier === 'full' ? { url: '/x', sha256: 'abc' } : null, name: 'Fixture', template: tpl.fig,
    clips: [], scale: 1, height: 1.7, assignOnly: true, noClips: false, tier, libraryFits: false }
}
const hairOf = f => {
  let m = null
  f.root.traverse(o => { if (o.isSkinnedMesh && o.name === 'hair') m = o })
  return m
}

// [3] / [4]
{
  const tpl = template()
  const figure = new Figure(model(tpl))
  figure.loadStrandRecord = () => record()
  const hair = hairOf(figure)
  const patched = hair.material
  check('[3] prepareStrandHair: a handle', figure.prepareStrandHair() === true && !!figure.strandHair)
  check('[3] before: the hair wears this figure\'s patched clone', patched !== tpl.hair.material)
  figure.setStrandHair(true)
  check('[3] setStrandHair(true): running, handle enabled', figure.strandRunning && figure.strandHair.enabled)
  check('[3] the hair is out of the garment push (template material back)', hair.material === tpl.hair.material)
  check('[3] the hair mesh runs on an owned geometry', hair.geometry !== tpl.hair.geometry)
  figure.update(1 / 60, { realDelta: 1 / 60 })
  check('[3] the secondary motion is configured without the hair groups (rev m1:strands)',
    figure.secondaryRev === 'm1:strands', String(figure.secondaryRev))
  check('[3] strandCostMs is the handle\'s', figure.strandCostMs === figure.strandHair.costMs)
  figure.setFirstPerson(true)
  check('[4] first person turns it off: the template geometry back, the patched clone back',
    !figure.strandRunning && hair.geometry === tpl.hair.geometry && hair.material === patched)
  figure.update(1 / 60, { realDelta: 1 / 60 })
  check('[4] the chains are back (rev m1)', figure.secondaryRev === 'm1', String(figure.secondaryRev))
  figure.setStrandHair(true)
  check('[4] setStrandHair(true) in first person stays off', !figure.strandRunning)
  figure.dispose()
}

// [5] Review Focus 2
{
  const tpl = template()
  const figure = new Figure(model(tpl))
  figure.loadStrandRecord = () => record(1)
  const warn = console.warn
  let warnings = 0
  console.warn = () => { warnings++ }
  const a = figure.prepareStrandHair(), b = figure.prepareStrandHair()
  console.warn = warn
  figure.setStrandHair(true)
  check('[5] a mismatched record: refused twice, ONE warning, no handle, still on chains',
    !a && !b && warnings === 1 && figure.strandHair === null && !figure.strandRunning, `warnings ${warnings}`)
  figure.dispose()
}

// [6] the distance tier
{
  const tpl = template()
  const figure = new Figure(model(tpl, 'low'))
  let asked = 0
  figure.loadStrandRecord = () => { asked++; return record() }
  check('[6] a low-tier figure never prepares, never asks for the record', !figure.prepareStrandHair() && asked === 0)
  figure.dispose()
}

console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed')
assert.equal(failures, 0)
