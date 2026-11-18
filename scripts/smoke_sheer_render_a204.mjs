#!/usr/bin/env node
/**
 * Smoke check (A204): a SHEER template piece is drawn see-through in both renderers.
 *
 * Usage: node scripts/smoke_sheer_render_a204.mjs [figure.glb]
 *        (with a path, the same checks run on that assembled figure as well)
 *
 * THE FIXTURE (GLB bytes built here): bone `Hips`, a body triangle (material 0 `skin`, opaque, single-sided) and a
 * node `garment_clothing_item_skirt` with extras `garment = {kind: clothing, …}`, material 1 exactly as
 * `garment_template.material_overrides({fabric: sheer, opacity: 0.4})` grafts it:
 * alphaMode BLEND, doubleSided, baseColorFactor [1, 1, 1, 0.4], extras {anima_sheer: true, opacity: 0.4}.
 *
 * HAND-DERIVED EXPECTATIONS (three's GLTFLoader: BLEND → transparent true, depthWrite false; doubleSided → side 2;
 * baseColorFactor alpha → opacity; extras → userData):
 *   [1] both loader factories: skirt transparent, depthWrite false, opacity 0.4, side DoubleSide (2);
 *       body transparent false, depthWrite true, side FrontSide (0).
 *   [2] client3d `zeroFigureMetalness` leaves those flags as they are (it only touches metalness).
 *   [3] `prepareSheerPieces(root, DoubleSide)` returns 1 (one sheer mesh), sets the skirt's renderOrder to
 *       SHEER_RENDER_ORDER = 2 and keeps transparent / depthWrite false / opacity 0.4; the body keeps renderOrder 0.
 *   [4] `SkeletonUtils.clone` (one figure instance): renderOrder 2 and the shared material survive.
 *   [5] Source: client3d figures.ts and both admin viewers (Model3DViewer, meshSnapshot) call prepareSheerPieces.
 * Before A204 (commit e08e95fdb) `prepareSheerPieces` did not exist — [3] fails there by construction.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

function buildGlb() {
  const chunks = []; const views = []; const accessors = []
  let offset = 0
  const push = (typed, target) => {
    const bytes = Buffer.from(typed.buffer, typed.byteOffset, typed.byteLength)
    const pad = (4 - (bytes.length % 4)) % 4
    chunks.push(bytes, Buffer.alloc(pad))
    views.push({ buffer: 0, byteOffset: offset, byteLength: bytes.length, ...(target ? { target } : {}) })
    offset += bytes.length + pad
    return views.length - 1
  }
  const acc = (typed, componentType, type, count, extra = {}) => {
    accessors.push({ bufferView: push(typed, extra.ibm ? undefined : 34962), componentType, type, count,
      ...(extra.minmax || {}) })
    return accessors.length - 1
  }
  const prim = (y, material) => ({
    attributes: {
      POSITION: acc(new Float32Array([0, y, 0, 0.1, y, 0, 0, y + 0.1, 0]), 5126, 'VEC3', 3,
        { minmax: { min: [0, y, 0], max: [0.1, y + 0.1, 0] } }),
      JOINTS_0: acc(new Uint8Array(12), 5121, 'VEC4', 3),
      WEIGHTS_0: acc(new Float32Array([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]), 5126, 'VEC4', 3),
    },
    material,
  })
  const ibm = acc(new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]), 5126, 'MAT4', 1, { ibm: true })
  const json = {
    asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: [0] }],
    nodes: [
      { name: 'Armature', children: [1, 2, 3] }, { name: 'Hips' },
      { name: 'Body', mesh: 0, skin: 0 },
      { name: 'garment_clothing_item_skirt', mesh: 1, skin: 0,
        extras: { garment: { kind: 'clothing', item_id: 'item_skirt', fsig: 'abc123def456' } } },
    ],
    meshes: [{ name: 'body', primitives: [prim(0, 0)] }, { name: 'skirt', primitives: [prim(0.5, 1)] }],
    materials: [
      { name: 'skin', pbrMetallicRoughness: { baseColorFactor: [0.8, 0.6, 0.5, 1] } },
      { name: 'skirt', alphaMode: 'BLEND', doubleSided: true,
        pbrMetallicRoughness: { baseColorFactor: [1, 1, 1, 0.4] }, extras: { anima_sheer: true, opacity: 0.4 } },
    ],
    skins: [{ joints: [1], inverseBindMatrices: ibm }],
    accessors, bufferViews: views, buffers: [{ byteLength: offset }],
  }
  let jsonBytes = Buffer.from(JSON.stringify(json), 'utf8')
  jsonBytes = Buffer.concat([jsonBytes, Buffer.alloc((4 - (jsonBytes.length % 4)) % 4, 0x20)])
  const bin = Buffer.concat(chunks)
  const header = Buffer.alloc(12)
  header.writeUInt32LE(0x46546c67, 0); header.writeUInt32LE(2, 4)
  header.writeUInt32LE(12 + 8 + jsonBytes.length + 8 + bin.length, 8)
  const ch = (len, type) => { const b = Buffer.alloc(8); b.writeUInt32LE(len, 0); b.writeUInt32LE(type, 4); return b }
  const glb = Buffer.concat([header, ch(jsonBytes.length, 0x4e4f534a), jsonBytes, ch(bin.length, 0x004e4942), bin])
  return glb.buffer.slice(glb.byteOffset, glb.byteOffset + glb.byteLength)
}

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_sheer_render_a204_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild', 'frontend/node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) { console.error('esbuild not found (npm install) — nothing was checked'); process.exit(1) }
    const built = spawnSync(bin, [__filename, '--bundle', '--platform=node', '--format=esm', '--log-level=warning',
      `--outfile=${bundlePath}`], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath, ...process.argv.slice(2)], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root })
    process.exit(run.status ?? 1)
  }
  globalThis.self = globalThis
  const THREE = await import('three')
  const SkeletonUtils = await import('three/addons/utils/SkeletonUtils.js')
  const { createGLTFLoader: client3dLoader } = await import('../client3d/src/scene/gltfLoader.ts')
  const { createGLTFLoader: adminLoader } = await import('../frontend/src/lib/gltfLoader.ts')
  const { zeroFigureMetalness } = await import('../client3d/src/scene/figureMaterials.ts')
  const { prepareSheerPieces, SHEER_RENDER_ORDER, inGarment } = await import('../packages/scene-render/src/index.ts')
  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const split = (root) => {
    const sheer = []; const body = []
    root.traverse((o) => {
      if (!o.isMesh) return
      if (o.material?.userData?.anima_sheer === true) sheer.push(o)
      else if (!inGarment(o)) body.push(o)
    })
    return { sheer, body }
  }
  const near = (a, b) => Math.abs(a - b) < 1e-6
  const cases = [['fixture', buildGlb(), 0.4]]
  if (process.argv[2]) {
    const b = fs.readFileSync(process.argv[2])
    cases.push([path.basename(process.argv[2]), b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength), null])
  }
  for (const [name, glb, opacity] of cases) {
    console.log(`[${name}]`)
    for (const [app, factory] of [['client3d', client3dLoader], ['frontend', adminLoader]]) {
      const { sheer, body } = split((await factory().parseAsync(glb.slice(0), '')).scene)
      check(`[1] ${app}: ≥1 sheer mesh, ≥1 body mesh`, sheer.length >= 1 && body.length >= 1, `${sheer.length}/${body.length}`)
      check(`[1] ${app}: sheer transparent, no depth write, DoubleSide`, sheer.every((m) =>
        m.material.transparent && !m.material.depthWrite && m.material.side === THREE.DoubleSide))
      if (opacity !== null) check(`[1] ${app}: sheer opacity ${opacity}`, sheer.every((m) => near(m.material.opacity, opacity)))
      check(`[1] ${app}: body opaque with depth write`, body.every((m) => !m.material.transparent && m.material.depthWrite))
    }
    const template = (await client3dLoader().parseAsync(glb.slice(0), '')).scene
    zeroFigureMetalness(template)
    let { sheer, body } = split(template)
    check('[2] zeroFigureMetalness keeps the sheer flags', sheer.every((m) => m.material.transparent && !m.material.depthWrite))
    const marked = prepareSheerPieces(template, THREE.DoubleSide)
    check('[3] prepareSheerPieces marks every sheer mesh', marked === sheer.length, `${marked}`)
    check(`[3] sheer renderOrder ${SHEER_RENDER_ORDER} = 2`, SHEER_RENDER_ORDER === 2 && sheer.every((m) => m.renderOrder === 2))
    check('[3] body renderOrder 0', body.every((m) => m.renderOrder === 0))
    const inst = SkeletonUtils.clone(template);
    ({ sheer, body } = split(inst))
    check('[4] clone keeps renderOrder 2 and the blended material', sheer.length === marked
      && sheer.every((m) => m.renderOrder === 2 && m.material.transparent && !m.material.depthWrite))
  }
  const root = process.cwd()
  for (const rel of ['client3d/src/scene/figures.ts', 'frontend/src/tabs/characters/Model3DViewer.tsx',
    'frontend/src/tabs/characters/meshSnapshot.ts']) {
    check(`[5] ${rel} calls prepareSheerPieces`, /prepareSheerPieces\(/.test(fs.readFileSync(path.join(root, rel), 'utf8')))
  }
  if (failures.length) { console.log(`FAILED: ${failures.length}`); process.exit(1) }
  console.log('all passed')
}
main().catch((e) => { console.error(e); process.exit(1) })
