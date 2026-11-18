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
 *     Without `mouth_open_deg` the full angle is JAW_OPEN_DEG = 26: value 1 -> (sin 13, 0, 0, cos 13) =
 *     (0.2249511, 0, 0, 0.9743701).
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
check('[4] no angle on the bone: 26 degrees', vnear(q(j.jaw), [0.2249511, 0, 0, 0.9743701], 1e-6) && SR.JAW_OPEN_DEG === 26,
  fmt(q(j.jaw)))

console.log(failed ? `FAILED (${failed})` : 'ALL OK')
process.exit(failed ? 1 : 0)
