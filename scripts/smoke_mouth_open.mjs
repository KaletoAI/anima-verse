#!/usr/bin/env node
/**
 * Ruling A203 parts 2 and 3: the morph target `mouth_open`, the bone `Jaw` and who drives them. Numbers by hand (§ B5a).
 *
 * Usage: node scripts/smoke_mouth_open.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * [1] mouthOpenFor(radius, openHeight) = (2 radius + 0.004) / openHeight clamped to [0, 1]:
 *     radius 0.012, height 0.0365 -> 0.028 / 0.0365 = 0.767123; radius 0.018 -> 0.040 / 0.0365 = 1.0959 -> 1;
 *     radius 0 -> 0; height 0 -> 0 (a body whose record carries no open height is not opened by contact).
 * [2] bindMouthOpen on a skinned mesh with the morph target at slot 1 (slot 0 is another target): manual 0.3 ->
 *     influence[1] 0.3, influence[0] untouched (0.9); contact 0.5 -> 0.5 (the larger); contact 0 -> back to 0.3;
 *     manual 7 -> clamped to 1. A mesh without the target -> null.
 * [3] FigureRuntime with the built mouth channel (open_height 0.04) in its payload:
 *     applyChannelOpenings([{channel "mouth", w 0.5, segments [{r 0.02}, {r 0.016}]}]) -> radius = the largest
 *     segment radius x w = 0.01 -> (0.02 + 0.004) / 0.04 = 0.6; an occupant of ANOTHER channel changes nothing;
 *     no occupant -> 0; setMouthOpen(0.25) -> 0.25 without contact, 0.6 with it (max); inspect().mouthOpen says the
 *     same. A payload without open_height -> contact opens nothing (0), the manual value still applies.
 * [3b] THE CHANNEL READOUT through the runtime (`channelReadouts()`, `inspect().readouts`): the record of [3] gives
 *     (with one head capsule, so the partner binding — made by the first partner snapshot, as in phase B — exists)
 *     O = a_pos (0, 1.57, 0.11), u = (b_pos − a_pos) / 0.08 = (0, −0.6, −0.8), D = 0.08, R 0.02. One occupant from
 *     'Q', w 1, k 0.9, one link O − 0.02u = (0, 1.582, 0.126) -> O + 0.05u = (0, 1.54, 0.07), r 0.025: insertion
 *     0.05 + 0.025 = 0.075 (of D 0.9375), of length 0.05 / 0.07 = 0.7142857, stretch 0.005 (ratio 0.25), k 0.9,
 *     receiver '' (the owner names it), entering 'Q'. At w 0.5 the link's radius is 0.0125: insertion 0.0625,
 *     stretch 0. An occupant at w 0 gives no readout; no occupant -> [].
 * [4] THE JAW BONE (part 3). Head at (0, 1.6, 0), Jaw its child at local (0, -0.02, 0.02) = model (0, 1.58, 0.02),
 *     no bind rotation, `mouth_open_deg` 20 on the bone; a vertex at model (0, 1.5, 0.1) weighted 1 to the jaw.
 *     Value 0.5 -> the jaw turns 10 degrees about the model's +X: local quaternion (sin 5, 0, 0, cos 5) =
 *     (0.0871557, 0, 0, 0.9961947). The vertex, rel. to the hinge (0, -0.08, 0.08): y' = y cos - z sin =
 *     -0.078785 - 0.013892 = -0.092677, z' = y sin + z cos = -0.013892 + 0.078785 = 0.064893 -> (0, 1.487323,
 *     0.084893): the front goes DOWN. Value 0 again -> the rest quaternion. Never driven -> the bone is not
 *     touched (a clip's rotation stays).
 *     With the Head's BIND turned 90 degrees about +Y the model's +X is the jaw's local -Z... by hand: R_y(90) maps
 *     local x -> model (0, 0, -1), local z -> model (1, 0, 0); the first row of R is (0, 0, 1), so the model's +X is
 *     the bone's local +Z and the same 10 degrees give the local quaternion (0, 0, 0.0871557, 0.9961947) — the
 *     vertex lands on the same (0, 1.487323, 0.084893).
 *     Without `mouth_open_deg` the full angle is JAW_OPEN_DEG = 30 (Ruling A206; 26 before): value 1 ->
 *     (sin 15, 0, 0, cos 15) = (0.2588190, 0, 0, 0.9659258).
 * [5] THE TEETH (Ruling A206). mouthPassHeight: {open_height 0.04, teeth_gap 0.025} -> 0.025 (the teeth decide);
 *     {open_height 0.04} -> 0.04; {teeth_gap 0, open_height 0.04} -> 0.04; {} / null -> 0. FigureRuntime with the
 *     record of [3] plus teeth_gap 0.025: the occupant of [3] (radius 0.02 x w 0.5 = 0.01) -> (0.02 + 0.004) / 0.025
 *     = 0.96 (0.6 without teeth). bindChannelOpening on a figure whose ONLY mesh lies on the
 *     channel axis inside the channel: 'mouth_tongue' -> bound with all 4 vertices as candidates (the tongue is pushed).
 * [6] THE TEETH MOVE WITH THE OPENING (owner finding 2026-11-19; before it, at 8fa2d763f, a 'mouth_teeth' mesh was
 *     never bound, so the part passed through both rows). Fixture: channel O origin, u +z, D 0.08, R 0.02, F 0.03;
 *     bones Head (index 0) and Jaw (index 1) at the origin; occupant one segment (0,0,−0.05) → (0,0,0.10), r 0.012
 *     → T = r + 2 mm = 0.014.
 *     - a lip ring (material Material_0, Head): vertices at distance 0.01 from the axis on s = 0: B = max(0.015,
 *       1.5 · max(0.012, 0.02)) = 0.03, b = 0.044, f(0.01) = 0.01 + 0.014 · (1 − 0.01/0.044)² = 0.01 + 0.014 ·
 *       0.7727273² = 0.0183595 → (0.01, 0, 0) moves to (0.0183595, 0, 0).
 *     - two tooth rows (material mouth_teeth): upper x ∈ {−0.01, 0, 0.01}, y +0.004, z 0.01, weighted 1.0 to Head;
 *       lower the same at y −0.004, weighted 1.0 to Jaw. Since A211 they follow the same radial map as the lip
 *       (b = 0.044): x = 0 at d 0.004 → f = 0.004 + 0.014 · (40/44)² = 0.0155702 → (0, ±0.0155702, 0.01); x = ±0.01
 *       at d = sqrt(0.000116) = 0.0107703 → f = 0.0107703 + 0.014 · (1 − 0.0107703/0.044)² = 0.0187553, f/d =
 *       1.7413908 → (±0.0174139, ±0.0069656, 0.01). Every tooth vertex ≥ T = 0.014 from the axis (none inside the
 *       part). restore() → rest (float32).
 *     - the jaw opened (Jaw moved by (0, −0.005, 0) in the world): the lower row is at world y −0.009: x = 0 at d 0.009
 *       → f = 0.009 + 0.014 · (35/44)² = 0.0178585 → world y −0.0178585, bind y −0.0128585 (it keeps following the
 *       jaw); x = ±0.01 at d = sqrt(0.000181) = 0.0134536 → f = 0.0134536 + 0.014 · (1 − 0.0134536/0.044)² =
 *       0.0202011, f/d = 1.5015378 → world (±0.0150154, −0.0135138), bind y −0.0085138; the upper row as before.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function load() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-mouth-open-'))
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
const vnear = (a, b, eps = 1e-5) => a.length === b.length && a.every((x, i) => near(x, b[i], eps))
const fmt = (v) => `[${v.map((x) => x.toFixed(6)).join(', ')}]`

// [1]
check('[1] 0.012 in 0.0365', near(SR.mouthOpenFor(0.012, 0.0365), 0.767123, 1e-6), SR.mouthOpenFor(0.012, 0.0365))
check('[1] 0.018 clamps to 1', SR.mouthOpenFor(0.018, 0.0365) === 1)
check('[1] no radius / no height', SR.mouthOpenFor(0, 0.0365) === 0 && SR.mouthOpenFor(0.02, 0) === 0)
check('[1] names', SR.MOUTH_OPEN_TARGET === 'mouth_open' && SR.MOUTH_OPEN_MARGIN_M === 0.004)

// fixture: a head mesh with two morph targets ("other", "mouth_open")
const make = (withTarget = true) => {
  const root = new THREE.Group()
  const inst = new THREE.Group(); root.add(inst)
  const hips = new THREE.Bone(); hips.name = 'mixamorig:Hips'; inst.add(hips)
  const headBone = new THREE.Bone(); headBone.name = 'mixamorig:Head'; headBone.position.set(0, 1.6, 0); hips.add(headBone)
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 1.6, 0.1, 0, 1.7, 0.1, 0, 1.5, 0.1], 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  if (withTarget) {
    mesh.morphTargetDictionary = { other: 0, mouth_open: 1 }
    mesh.morphTargetInfluences = [0.9, 0]
  }
  inst.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([hips, headBone]))
  return { root, inst, mesh }
}

// [2]
let f = make()
const mo = SR.bindMouthOpen(f.inst)
mo.setManual(0.3)
check('[2] manual 0.3 on its own slot', near(f.mesh.morphTargetInfluences[1], 0.3, 1e-12) && f.mesh.morphTargetInfluences[0] === 0.9,
  JSON.stringify(f.mesh.morphTargetInfluences))
mo.setContact(0.5)
check('[2] contact 0.5 wins', near(f.mesh.morphTargetInfluences[1], 0.5, 1e-12) && mo.value === 0.5)
mo.setContact(0)
check('[2] back to the manual value', near(f.mesh.morphTargetInfluences[1], 0.3, 1e-12))
mo.setManual(7)
check('[2] clamped to 1', f.mesh.morphTargetInfluences[1] === 1)
check('[2] no target -> null', SR.bindMouthOpen(make(false).inst) === null)

// [3]
const built = (openHeight) => ({ id: 'mouth', kind: 'channel', a: 'mixamorig:Head', b: 'mixamorig:Head',
  a_pos: [0, 1.57, 0.11], b_pos: [0, 1.522, 0.046], r: 0.02, cone_deg: 35, funnel: 0.03,
  accepts: ['attached_part', 'appendage_chain'], min_length: 0, compress_min: 0.6, suppress: [],
  frame: { side: [1, 0, 0], up: [0, 1, 0], front: [0, 0, 1] }, placement: 'rig', applied: null,
  ...(openHeight ? { open_height: openHeight } : {}) })
const runtime = (openHeight) => {
  const g = make()
  const rt = SR.createFigureRuntime(THREE, { root: g.root, motion: () => undefined,
    collision: { version: SR.COLLISION_VERSION, capsules: [], channels: [built(openHeight)] }, tier: 'full', bindRadius: 2 })
  return { rt, mesh: g.mesh }
}
const seg = (r) => ({ a: [0, 1.57, 0.2], b: [0, 1.57, 0.3], r })
let { rt, mesh } = runtime(0.04)
rt.applyChannelOpenings([{ channel: 'mouth', w: 0.5, segments: [seg(0.02), seg(0.016)] }], { left: 0 })
check('[3] contact opens to 0.6', near(mesh.morphTargetInfluences[1], 0.6, 1e-9), mesh.morphTargetInfluences[1])
rt.applyChannelOpenings([{ channel: 'other:chan', w: 1, segments: [seg(0.03)] }], { left: 0 })
check('[3] another channel: closed', mesh.morphTargetInfluences[1] === 0, mesh.morphTargetInfluences[1])
rt.applyChannelOpenings([], { left: 0 })
check('[3] no occupant: closed', mesh.morphTargetInfluences[1] === 0)
rt.setMouthOpen(0.25)
check('[3] manual 0.25', near(mesh.morphTargetInfluences[1], 0.25, 1e-12) && rt.mouthOpenValue() === 0.25)
rt.applyChannelOpenings([{ channel: 'mouth', w: 0.5, segments: [seg(0.02)] }], { left: 0 })
check('[3] contact above the manual value', near(mesh.morphTargetInfluences[1], 0.6, 1e-9))
;({ rt, mesh } = runtime(0))
rt.applyChannelOpenings([{ channel: 'mouth', w: 1, segments: [seg(0.02)] }], { left: 0 })
check('[3] no open height: contact opens nothing', mesh.morphTargetInfluences[1] === 0, mesh.morphTargetInfluences[1])
rt.setMouthOpen(0.4)
check('[3] ... the manual value still applies', near(mesh.morphTargetInfluences[1], 0.4, 1e-12))

// [3b]
{
  const g3 = make()
  rt = SR.createFigureRuntime(THREE, { root: g3.root, motion: () => undefined,
    collision: { version: SR.COLLISION_VERSION, channels: [built(0.04)],
      capsules: [{ id: 'head', a: 'mixamorig:Head', b: 'mixamorig:Head', r: 0.075, region: 'head' }] },
    tier: 'full', bindRadius: 2 })
  // The partner binding (and its channels) is made by the first partner snapshot, as phase B does.
  check('[3b] the partner binding is made', !!rt.partnerSnapshot(null, 'R'))
  const link = { a: [0, 1.582, 0.126], b: [0, 1.54, 0.07], r: 0.025 }
  rt.applyChannelOpenings([{ channel: 'mouth', w: 1, k: 0.9, from: 'Q', segments: [link] }], { left: 0 })
  const r = rt.channelReadouts()
  check('[3b] one readout: mouth, from Q, receiver \'\', w 1, k 0.9', r.length === 1 && r[0].channel === 'mouth'
    && r[0].entering === 'Q' && r[0].receiver === '' && r[0].w === 1 && r[0].compressK === 0.9, JSON.stringify(r))
  check('[3b] D 0.08, R 0.02, insertion 0.075 (0.9375), of length 0.7142857', r.length === 1 && near(r[0].depthM, 0.08, 1e-6)
    && near(r[0].restRadiusM, 0.02, 1e-9) && near(r[0].insertionM, 0.075, 1e-6) && near(r[0].insertionOfDepth, 0.9375, 1e-5)
    && near(r[0].insertionOfLength, 0.7142857, 1e-6), JSON.stringify(r))
  check('[3b] stretch 0.005, ratio 0.25', r.length === 1 && near(r[0].stretchM, 0.005, 1e-9) && near(r[0].stretchRatio, 0.25, 1e-7),
    JSON.stringify(r))
  check('[3b] inspect() carries the same', JSON.stringify(rt.inspect()?.readouts) === JSON.stringify(r))
  rt.applyChannelOpenings([{ channel: 'mouth', w: 0.5, from: 'Q', segments: [link] }], { left: 0 })
  const h = rt.channelReadouts()
  check('[3b] w 0.5: insertion 0.0625, stretch 0, k 1', h.length === 1 && near(h[0].insertionM, 0.0625, 1e-6) && h[0].stretchM === 0
    && h[0].compressK === 1, JSON.stringify(h))
  rt.applyChannelOpenings([{ channel: 'mouth', w: 0, from: 'Q', segments: [link] }], { left: 0 })
  check('[3b] w 0: no readout', rt.channelReadouts().length === 0)
  rt.applyChannelOpenings([], { left: 0 })
  check('[3b] no occupant: none', rt.channelReadouts().length === 0)
}

// [4]
const jawFixture = (headTurnY = 0, deg = 20) => {
  const root = new THREE.Group()
  const inst = new THREE.Group(); root.add(inst)
  const hips = new THREE.Bone(); hips.name = 'mixamorig:Hips'; inst.add(hips)
  const head = new THREE.Bone(); head.name = 'mixamorig:Head'; head.position.set(0, 1.6, 0); head.rotation.y = headTurnY
  hips.add(head)
  const jaw = new THREE.Bone(); jaw.name = 'mixamorig:Jaw'
  if (deg) jaw.userData.mouth_open_deg = deg
  head.add(jaw)
  // The jaw at model (0, 1.58, 0.02) whatever the head's bind turn: its local offset is the model offset turned back.
  jaw.position.copy(new THREE.Vector3(0, -0.02, 0.02).applyQuaternion(head.quaternion.clone().invert()))
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 1.5, 0.1, 0, 1.7, 0.1, 0, 1.6, 0.2], 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([2, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  inst.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([hips, head, jaw]))
  const vertex = () => {
    root.updateMatrixWorld(true)
    const p = new THREE.Vector3(0, 1.5, 0.1)
    return p.applyMatrix4(mesh.skeleton.boneInverses[2]).applyMatrix4(jaw.matrixWorld).toArray()
  }
  return { inst, jaw, vertex }
}
const q = (b) => [b.quaternion.x, b.quaternion.y, b.quaternion.z, b.quaternion.w]
let j = jawFixture()
let jo = SR.bindMouthOpen(j.inst)
check('[4] a body with a jaw and no target binds', jo !== null)
jo.setManual(0.5)
check('[4] 10 degrees about local X', vnear(q(j.jaw), [0.0871557, 0, 0, 0.9961947], 1e-6), fmt(q(j.jaw)))
check('[4] the jaw vertex goes down', vnear(j.vertex(), [0, 1.487323, 0.084893], 1e-5), fmt(j.vertex()))
jo.setManual(0)
check('[4] back to rest', vnear(q(j.jaw), [0, 0, 0, 1], 1e-9), fmt(q(j.jaw)))
j = jawFixture()
jo = SR.bindMouthOpen(j.inst)
j.jaw.quaternion.set(0, 0.1, 0, Math.sqrt(1 - 0.01))
jo.setContact(0)
check('[4] never driven: a clip keeps the bone', near(j.jaw.quaternion.y, 0.1, 1e-12), fmt(q(j.jaw)))
j = jawFixture(Math.PI / 2)
jo = SR.bindMouthOpen(j.inst)
jo.setManual(0.5)
check('[4] bind turned 90 about Y: local Z', vnear(q(j.jaw), [0, 0, 0.0871557, 0.9961947], 1e-6), fmt(q(j.jaw)))
check('[4] ... the same vertex position', vnear(j.vertex(), [0, 1.487323, 0.084893], 1e-5), fmt(j.vertex()))
j = jawFixture(0, 0)
jo = SR.bindMouthOpen(j.inst)
jo.setManual(1)
check('[4] no angle on the bone: 30 degrees', vnear(q(j.jaw), [0.2588190, 0, 0, 0.9659258], 1e-6) && SR.JAW_OPEN_DEG === 30,
  fmt(q(j.jaw)))

// [5]
check('[5] teeth decide', SR.mouthPassHeight({ open_height: 0.04, teeth_gap: 0.025 }) === 0.025)
check('[5] no teeth: the lips', SR.mouthPassHeight({ open_height: 0.04 }) === 0.04
  && SR.mouthPassHeight({ teeth_gap: 0, open_height: 0.04 }) === 0.04)
check('[5] neither', SR.mouthPassHeight({}) === 0 && SR.mouthPassHeight(null) === 0)
{
  const g = make()
  const rt5 = SR.createFigureRuntime(THREE, { root: g.root, motion: () => undefined,
    collision: { version: SR.COLLISION_VERSION, capsules: [], channels: [{ ...built(0.04), teeth_gap: 0.025 }] },
    tier: 'full', bindRadius: 2 })
  rt5.applyChannelOpenings([{ channel: 'mouth', w: 0.5, segments: [seg(0.02), seg(0.016)] }], { left: 0 })
  check('[5] contact opens by the teeth gap: 0.96', near(g.mesh.morphTargetInfluences[1], 0.96, 1e-9), g.mesh.morphTargetInfluences[1])
}
const onAxisFigure = (material) => {
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0.02, 0, 0, 0.04, 0.001, 0, 0.06, 0, 0.001, 0.08, 0, 0], 3))
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(new Array(12).fill(0).map((_, i) => (i % 3 === 1 ? 1 : 0)), 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Array(16).fill(0), 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(new Array(16).fill(0).map((_, i) => (i % 4 === 0 ? 1 : 0)), 4))
  geo.setIndex([0, 1, 2, 1, 3, 2])
  const bone = new THREE.Bone()
  const m = new THREE.MeshBasicMaterial(); m.name = material
  const mesh = new THREE.SkinnedMesh(geo, m)
  const root = new THREE.Group(); root.add(bone, mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([bone]))
  return root
}
const ch5 = { id: 'mouth', o: [0, 0, 0], u: [1, 0, 0], depth: 0.08, r: 0.02, coneDeg: 35, funnel: 0.03, accepts: [],
  minLength: 0, compressMin: 0.6, kinds: null, suppress: new Set() }
const tongue = SR.bindChannelOpening(THREE, onAxisFigure('mouth_tongue'), ch5)
check('[5] tongue: bound, 4 candidates', tongue !== null && tongue.candidates === 4, tongue && tongue.candidates)

// [6]
{
  const ch6 = { id: 'mouth', o: [0, 0, 0], u: [0, 0, 1], depth: 0.08, r: 0.02, coneDeg: 35, funnel: 0.03, accepts: [],
    minLength: 0, compressMin: 0.6, kinds: null, suppress: new Set() }
  const seg6 = [{ a: [0, 0, -0.05], b: [0, 0, 0.10], r: 0.012 }]
  const meshOf = (positions, joints, material, bones) => {
    const n = positions.length / 3
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    geo.setAttribute('normal', new THREE.Float32BufferAttribute(new Array(3 * n).fill(0).map((_, i) => (i % 3 === 2 ? 1 : 0)), 3))
    geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(joints.flatMap((j) => [j, 0, 0, 0]), 4))
    geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(joints.flatMap(() => [1, 0, 0, 0]), 4))
    geo.setIndex(Array.from({ length: n - (n % 3) }, (_, i) => i))
    const mat = new THREE.MeshBasicMaterial(); mat.name = material
    const mesh = new THREE.SkinnedMesh(geo, mat)
    return mesh
  }
  const teethFigure = () => {
    const root = new THREE.Group()
    const head = new THREE.Bone(); head.name = 'mixamorig:Head'
    const jaw = new THREE.Bone(); jaw.name = 'mixamorig:Jaw'
    root.add(head, jaw)
    const lips = meshOf([0.01, 0, 0, -0.01, 0, 0, 0, 0.01, 0], [0, 0, 0], 'Material_0')
    const teeth = meshOf([-0.01, 0.004, 0.01, 0, 0.004, 0.01, 0.01, 0.004, 0.01,
      -0.01, -0.004, 0.01, 0, -0.004, 0.01, 0.01, -0.004, 0.01], [0, 0, 0, 1, 1, 1], 'mouth_teeth')
    root.add(lips, teeth)
    root.updateMatrixWorld(true)
    const skeleton = new THREE.Skeleton([head, jaw])
    lips.bind(skeleton); teeth.bind(skeleton)
    return { root, jaw, lips, teeth }
  }
  const xyz = (mesh, i) => [mesh.geometry.attributes.position.getX(i), mesh.geometry.attributes.position.getY(i),
    mesh.geometry.attributes.position.getZ(i)]
  let F = teethFigure()
  const tb = SR.bindChannelOpening(THREE, F.root, ch6)
  check('[6] the teeth are bound (6 + the 3 lip vertices)', tb !== null && tb.candidates === 9, tb && tb.candidates)
  tb.apply(ch6, seg6)
  check('[6] lip (0.01, 0, 0) → (0.0183595, 0, 0)', vnear(xyz(F.lips, 0), [0.0183595, 0, 0], 1e-6), fmt(xyz(F.lips, 0)))
  const up = [0, 1, 2].map((i) => xyz(F.teeth, i)), lo = [3, 4, 5].map((i) => xyz(F.teeth, i))
  const X = [-0.0174139, 0, 0.0174139], Y = [0.0069656, 0.0155702, 0.0069656]
  check('[6] upper row on the radial map', up.every((p, k) => vnear(p, [X[k], Y[k], 0.01], 1e-6)), JSON.stringify(up))
  check('[6] lower row mirrored', lo.every((p, k) => vnear(p, [X[k], -Y[k], 0.01], 1e-6)), JSON.stringify(lo))
  const inside = [...up, ...lo].filter((p) => Math.hypot(p[0], p[1]) < 0.014 - 1e-6)
  check('[6] no tooth vertex inside T = 0.014', inside.length === 0, JSON.stringify(inside))
  tb.restore()
  check('[6] restore: the teeth at rest', vnear(xyz(F.teeth, 1), [0, 0.004, 0.01], 1e-8) && vnear(xyz(F.teeth, 4), [0, -0.004, 0.01], 1e-8)
    && vnear(xyz(F.lips, 0), [0.01, 0, 0], 1e-8), fmt(xyz(F.teeth, 1)))
  tb.dispose()
  F = teethFigure()
  F.jaw.position.set(0, -0.005, 0); F.root.updateMatrixWorld(true)
  const tj = SR.bindChannelOpening(THREE, F.root, ch6)
  tj.apply(ch6, seg6)
  const lowBind = xyz(F.teeth, 4), lowSide = xyz(F.teeth, 5), upBind = xyz(F.teeth, 1)
  check('[6] jaw opened: the lower row\'s bind y −0.0128585 (world −0.0178585), the side (0.0150154, −0.0085138), the upper 0.0155702',
    near(lowBind[1], -0.0128585, 1e-6) && vnear(lowSide, [0.0150154, -0.0085138, 0.01], 1e-6) && near(upBind[1], 0.0155702, 1e-6),
    fmt(lowBind) + fmt(lowSide) + fmt(upBind))
  tj.dispose()
}

console.log(failed ? `FAILED (${failed})` : 'ALL OK')
process.exit(failed ? 1 : 0)
