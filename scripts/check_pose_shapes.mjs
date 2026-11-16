#!/usr/bin/env node
/**
 * Ruling A141 — does the RENDERER reproduce a template drape's poses? Loads a drape GLB of
 * `garment_template_build.py` (a run directory written with `render`: `template.glb` + the Blender-evaluated
 * garment per pose, `template_<pose>_posed.f32`, glTF axes), poses the rig in three exactly as the Blender
 * script's `set_pose` (world-axis rotations about each bone's head, arms lowered in every pose but rest), blends
 * the pose shapes with `bindPoseShapes` (scene-render, the client's code) and skins every garment vertex with
 * three (`getVertexPosition`: morphs, then the skin). Prints per pose the influences and the largest / p99
 * distance to Blender's vertices (each three vertex matched to Blender's by its rest position). A measurement, not a smoke: it needs a run directory.
 *
 * Usage: node scripts/check_pose_shapes.mjs <run_dir> [pose …]   (default poses rest walk sit kneel)
 */
import { readFile, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
const THREE = await import(join(ROOT, 'node_modules/three/build/three.module.js'))
const { GLTFLoader } = await import(join(ROOT, 'node_modules/three/examples/jsm/loaders/GLTFLoader.js'))

async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.check-pose-shapes-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: "export * from '@anima/scene-render';", resolveDir: join(ROOT, 'client3d'), loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'sr.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'sr.mjs')
    await writeFile(file, built.outputFiles[0].text.replaceAll(/from "three"/g, `from "${join(ROOT, 'node_modules/three/build/three.module.js')}"`), 'utf8')
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

// garment_template_drape.py POSES / ARMS_DOWN (Blender axes: X = glTF X, Y = glTF −Z, Z = glTF Y)
const POSES = {
  rest: [],
  walk: [['LeftUpLeg', 'X', -25], ['RightUpLeg', 'X', 20], ['RightLeg', 'X', 30], ['LeftLeg', 'X', 10]],
  sit: [['LeftUpLeg', 'X', -85], ['RightUpLeg', 'X', -85], ['LeftLeg', 'X', 90], ['RightLeg', 'X', 90]],
  kneel: [['LeftUpLeg', 'X', -10], ['RightUpLeg', 'X', -10], ['LeftLeg', 'X', 100], ['RightLeg', 'X', 100]],
}
const ARMS_DOWN = [['LeftArm', 'Y', 30], ['RightArm', 'Y', -30], ['LeftForeArm', 'X', -20], ['RightForeArm', 'X', -20]]
const AXIS = { X: [1, 0, 0], Y: [0, 0, -1], Z: [0, 1, 0] }

const [dir, ...want] = process.argv.slice(2)
if (!dir) { console.error('usage: check_pose_shapes.mjs <run_dir> [pose …]'); process.exit(2) }
const SR = await loadSR()
// Node has no image decoder: the GLB is parsed without its textures (geometry, skin and morphs only).
function withoutTextures(glb) {
  const jsonLen = glb.readUInt32LE(12)
  const json = JSON.parse(glb.subarray(20, 20 + jsonLen).toString('utf8'))
  delete json.textures; delete json.images; delete json.samplers
  for (const m of json.materials ?? []) {
    if (m.pbrMetallicRoughness) { delete m.pbrMetallicRoughness.baseColorTexture; delete m.pbrMetallicRoughness.metallicRoughnessTexture }
    delete m.normalTexture; delete m.occlusionTexture; delete m.emissiveTexture
  }
  let text = Buffer.from(JSON.stringify(json), 'utf8')
  text = Buffer.concat([text, Buffer.alloc((4 - (text.length % 4)) % 4, 0x20)])
  const rest = glb.subarray(20 + jsonLen)
  const head = Buffer.alloc(20)
  head.writeUInt32LE(0x46546c67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(20 + text.length + rest.length, 8)
  head.writeUInt32LE(text.length, 12); head.writeUInt32LE(0x4e4f534a, 16)
  const out = Buffer.concat([head, text, rest])
  return out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength)
}
const buf = withoutTextures(await readFile(join(dir, 'template.glb')))
const gltf = await new Promise((ok, bad) => new GLTFLoader().parse(buf, '', ok, bad))
const scene = gltf.scene
let mesh = null
scene.traverse(o => { if (o.isSkinnedMesh && o.name.startsWith('garment_')) mesh = o })
if (!mesh) throw new Error('no garment mesh')
// The drape GLB carries no assembly extras: hand the payload in from the run record.
const run = JSON.parse(await readFile(join(dir, 'run.json'), 'utf8'))
mesh.userData.garment = { kind: 'clothing', pose_shapes: run.data.pose_shapes }
const bones = new Map()
scene.traverse(o => { if (o.isBone) bones.set(SR.normBoneName ? SR.normBoneName(o.name) : o.name.replace(/^mixamorig:?/i, '').toLowerCase(), o) })
const rest = new Map([...bones].map(([k, b]) => [k, b.quaternion.clone()]))
scene.updateMatrixWorld(true)
const ps = SR.bindPoseShapes(THREE, scene)
const M = new THREE.Matrix4(), T = new THREE.Matrix4(), R = new THREE.Matrix4(), Ti = new THREE.Matrix4()
function setPose(name) {
  for (const [k, b] of bones) b.quaternion.copy(rest.get(k))
  scene.updateMatrixWorld(true)
  for (const [bn, ax, deg] of [...POSES[name], ...(name !== 'rest' ? ARMS_DOWN : [])]) {
    const b = bones.get(bn.toLowerCase())
    if (!b) continue
    const head = new THREE.Vector3().setFromMatrixPosition(b.matrixWorld)
    T.makeTranslation(head.x, head.y, head.z); Ti.makeTranslation(-head.x, -head.y, -head.z)
    R.makeRotationAxis(new THREE.Vector3(...AXIS[ax]), deg * Math.PI / 180)
    M.copy(T).multiply(R).multiply(Ti).multiply(b.matrixWorld)
    M.premultiply(new THREE.Matrix4().copy(b.parent.matrixWorld).invert())
    const p = new THREE.Vector3(), s = new THREE.Vector3()
    M.decompose(p, b.quaternion, s)
    scene.updateMatrixWorld(true)
  }
}
const n = mesh.geometry.attributes.position.count
// The exporter splits vertices (UV seams): each three vertex is matched to Blender's vertex at the same rest
// position (rest pose, both sides), then compared in every pose.
async function posed(pose) { return new Float32Array((await readFile(join(dir, `template_${pose}_posed.f32`))).buffer.slice(0)) }
setPose('rest'); ps.update(); scene.updateMatrixWorld(true); mesh.skeleton.update()
const restRef = await posed('rest')
const grid = new Map()
const key = (x, y, z) => `${Math.round(x * 500)},${Math.round(y * 500)},${Math.round(z * 500)}`
for (let j = 0; j < restRef.length / 3; j++) {
  const k = key(restRef[3 * j], restRef[3 * j + 1], restRef[3 * j + 2])
  if (!grid.has(k)) grid.set(k, [])
  grid.get(k).push(j)
}
const match = new Int32Array(n).fill(-1)
const w = new THREE.Vector3()
for (let i = 0; i < n; i++) {
  mesh.getVertexPosition(i, w); w.applyMatrix4(mesh.matrixWorld)
  let best = -1, bd = 0.004
  const [cx, cy, cz] = [Math.round(w.x * 500), Math.round(w.y * 500), Math.round(w.z * 500)]
  for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (let c = -1; c <= 1; c++) {
    for (const j of grid.get(`${cx + a},${cy + b},${cz + c}`) ?? []) {
      const dd = Math.hypot(w.x - restRef[3 * j], w.y - restRef[3 * j + 1], w.z - restRef[3 * j + 2])
      if (dd < bd) { bd = dd; best = j }
    }
  }
  match[i] = best
}
console.log(JSON.stringify({ matched: [...match].filter(j => j >= 0).length, of: n }))
for (const pose of want.length ? want : Object.keys(POSES)) {
  setPose(pose)
  ps.update()
  scene.updateMatrixWorld(true)
  mesh.skeleton.update()
  const ref = await posed(pose)
  const d = []
  const v = new THREE.Vector3()
  for (let i = 0; i < n; i++) {
    const j = match[i]
    if (j < 0) continue
    mesh.getVertexPosition(i, v)
    v.applyMatrix4(mesh.matrixWorld)
    d.push(Math.hypot(v.x - ref[3 * j], v.y - ref[3 * j + 1], v.z - ref[3 * j + 2]))
  }
  d.sort((a, b) => a - b)
  const m = d.length
  const inf = Object.fromEntries(Object.entries(ps.last.influences).map(([k, x]) => [k, +x.toFixed(4)]))
  console.log(JSON.stringify({ pose, influences: inf, verts: n, ref_verts: ref.length / 3,
    compared: m, max_mm: +(d[m - 1] * 1000).toFixed(2), p99_mm: +(d[Math.floor(m * 0.99)] * 1000).toFixed(2) }))
}
