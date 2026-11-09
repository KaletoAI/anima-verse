#!/usr/bin/env node
/**
 * Smoke check: card hair keeps its VERTEX COLOURS and its DOUBLE SIDE through
 * every material step both renderers put a loaded character GLB through.
 *
 * Usage: node scripts/smoke_client_vertex_colors.mjs
 *
 * WHY: HairDeck hair (docs/schnittstellen-3d.md § A3a, garment node
 * `garment_hair_<item>`) carries its colour ONLY as COLOR_0 on a double-sided
 * material with no texture. A step that swaps the material (a separate
 * texture, the underwater ghost) or drops `vertexColors` renders the hair
 * as one flat colour; a lost `side` shows the cards from one side only.
 *
 * THE FIXTURES (built here as GLB bytes, no file on disk):
 *   one bone `Hips` (skin 0, identity inverse bind), a body triangle (POSITION,
 *   JOINTS_0, WEIGHTS_0; material 0 single-sided, metallicFactor unset = 1.0)
 *   and a hair node `garment_hair_hair_kira` with extras
 *   `garment = {kind: hair, item_id: hair_kira, fsig}` on skin 0, material 1
 *   `doubleSided: true`, metallicFactor 0.
 *   [A] full tier: hair = ONE primitive, COLOR_0 UNSIGNED_BYTE normalized
 *       VEC4 (what the graft writes) — 3 vertices (255,0,0,255) (0,255,0,255)
 *       (0,0,255,255) → read back 1/0/0, 0/1/0, 0/0/1, alpha 1.
 *   [B] low tier: hair = TWO primitives, COLOR_0 FLOAT VEC3 (what the Blender
 *       LOD writes) — three makes a Group (with the extras) holding two meshes.
 *
 * THE STEPS AND WHAT EACH MUST LEAVE (hand-derived from the code paths):
 *   [1] each app's GLTFLoader factory (client3d/src/scene/gltfLoader.ts,
 *       frontend/src/lib/gltfLoader.ts): every hair mesh has a `color`
 *       attribute (itemSize 4 normalized for A, 3 for B), material
 *       vertexColors true, side DoubleSide (2); body vertexColors false,
 *       side FrontSide (0).
 *   [2] client3d `zeroFigureMetalness`: body metalness 1 → 0; every hair
 *       material is the SAME object as before, vertexColors/side unchanged.
 *   [3] client3d `applyFigureTexture` (the FBX texture route): the body gets
 *       a NEW material with map = the texture; the hair keeps its own
 *       material object (map null).
 *   [4] `SkeletonUtils.clone` (one figure instance): the clone's hair mesh
 *       shares that material → vertexColors true, DoubleSide.
 *   [5] `SubmergedGhost` on the instance, water at y = 0.5: one ghost per
 *       mesh (A: 2, B: 3); the hair ghosts have vertexColors true and
 *       DoubleSide, the body ghost vertexColors false and FrontSide.
 *   [6] frontend `applyViewerTexture` (Model3DViewer's texture route): body
 *       map = texture and colour white; hair map null, vertexColors true,
 *       colour unchanged (its base colour factor 1,1,1 in the fixture).
 *   [7] Source: figures.ts calls applyFigureTexture in both texture paths and
 *       builds no inline textured material; Model3DViewer calls
 *       applyViewerTexture and sets no `mat.map = tex` itself.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

/** One GLB with the body triangle and hair of the given colour layout. */
function buildGlb(variant) {
  const chunks = []
  const views = []
  const accessors = []
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
      ...(extra.normalized ? { normalized: true } : {}), ...(extra.minmax || {}) })
    return accessors.length - 1
  }
  const tri = (y) => new Float32Array([0, y, 0, 0.1, y, 0, 0, y + 0.1, 0])
  const pos = (y) => acc(tri(y), 5126, 'VEC3', 3,
    { minmax: { min: [0, y, 0], max: [0.1, y + 0.1, 0] } })
  const joints = () => acc(new Uint8Array(12), 5121, 'VEC4', 3)
  const weights = () => acc(new Float32Array([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]), 5126, 'VEC4', 3)
  const colour = () => variant === 'A'
    ? acc(new Uint8Array([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255]), 5121, 'VEC4', 3, { normalized: true })
    : acc(new Float32Array([1, 0, 0, 0, 1, 0, 0, 0, 1]), 5126, 'VEC3', 3)
  const prim = (y, hair) => ({
    attributes: { POSITION: pos(y), JOINTS_0: joints(), WEIGHTS_0: weights(), ...(hair ? { COLOR_0: colour() } : {}) },
    material: hair ? 1 : 0,
  })
  const ibm = acc(new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]), 5126, 'MAT4', 1, { ibm: true })
  const hairPrims = variant === 'A' ? [prim(1.6, true)] : [prim(1.6, true), prim(1.65, true)]
  const json = {
    asset: { version: '2.0' },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [
      { name: 'Armature', children: [1, 2, 3] },
      { name: 'Hips' },
      { name: 'Body', mesh: 0, skin: 0 },
      { name: 'garment_hair_hair_kira', mesh: 1, skin: 0,
        extras: { garment: { kind: 'hair', item_id: 'hair_kira', fsig: 'abc123def456' } } },
    ],
    meshes: [{ name: 'body', primitives: [prim(0, false)] }, { name: 'hair', primitives: hairPrims }],
    materials: [
      { name: 'skin', pbrMetallicRoughness: { baseColorFactor: [0.8, 0.6, 0.5, 1] } },
      { name: 'hair', doubleSided: true, pbrMetallicRoughness: { metallicFactor: 0, roughnessFactor: 0.9 } },
    ],
    skins: [{ joints: [1], inverseBindMatrices: ibm }],
    accessors,
    bufferViews: views,
    buffers: [{ byteLength: offset }],
  }
  let jsonBytes = Buffer.from(JSON.stringify(json), 'utf8')
  jsonBytes = Buffer.concat([jsonBytes, Buffer.alloc((4 - (jsonBytes.length % 4)) % 4, 0x20)])
  const bin = Buffer.concat(chunks)
  const header = Buffer.alloc(12)
  const total = 12 + 8 + jsonBytes.length + 8 + bin.length
  header.writeUInt32LE(0x46546c67, 0); header.writeUInt32LE(2, 4); header.writeUInt32LE(total, 8)
  const ch = (len, type) => { const b = Buffer.alloc(8); b.writeUInt32LE(len, 0); b.writeUInt32LE(type, 4); return b }
  const glb = Buffer.concat([header, ch(jsonBytes.length, 0x4e4f534a), jsonBytes, ch(bin.length, 0x004e4942), bin])
  return glb.buffer.slice(glb.byteOffset, glb.byteOffset + glb.byteLength)
}

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_client_vertex_colors_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild',
      'frontend/node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm', '--log-level=warning',
      `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root,
    })
    process.exit(run.status ?? 1)
  }

  globalThis.self = globalThis
  const THREE = await import('three')
  const SkeletonUtils = await import('three/addons/utils/SkeletonUtils.js')
  const { createGLTFLoader: client3dLoader } = await import('../client3d/src/scene/gltfLoader.ts')
  const { createGLTFLoader: adminLoader } = await import('../frontend/src/lib/gltfLoader.ts')
  const { applyFigureTexture, zeroFigureMetalness } = await import('../client3d/src/scene/figureMaterials.ts')
  const { SubmergedGhost } = await import('../client3d/src/scene/submergedGhost.ts')
  const { applyViewerTexture } = await import('../frontend/src/tabs/characters/modelTexture.ts')
  const { inGarment } = await import('../packages/scene-render/src/figure.ts')

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const meshesOf = (root) => {
    const hair = []; const body = []
    root.traverse((o) => { if (o.isMesh) (inGarment(o) ? hair : body).push(o) })
    return { hair, body }
  }
  const texture = () => new THREE.DataTexture(new Uint8Array([200, 150, 120, 255]), 1, 1)
  const near = (a, b) => Math.abs(a - b) < 1e-6

  for (const variant of ['A', 'B']) {
    const glb = buildGlb(variant)
    const prims = variant === 'A' ? 1 : 2
    const size = variant === 'A' ? 4 : 3
    console.log(`[${variant}] hair COLOR_0 ${variant === 'A' ? 'UNSIGNED_BYTE normalized VEC4' : 'FLOAT VEC3, 2 primitives'}`)

    // [1] both loader factories
    for (const [app, factory] of [['client3d', client3dLoader], ['frontend', adminLoader]]) {
      const gltf = await factory().parseAsync(glb.slice(0), '')
      const { hair, body } = meshesOf(gltf.scene)
      check(`[1] ${app}: ${prims} hair mesh(es), 1 body`, hair.length === prims && body.length === 1,
        `${hair.length}/${body.length}`)
      check(`[1] ${app}: hair colour attribute itemSize ${size}`,
        hair.every((m) => m.geometry.attributes.color?.itemSize === size))
      if (variant === 'A') {
        const c = hair[0].geometry.attributes.color
        check(`[1] ${app}: colours read back 1/0/0 0/1/0 0/0/1 a1`,
          c.normalized && near(c.getX(0), 1) && near(c.getY(1), 1) && near(c.getZ(2), 1) && near(c.getW(0), 1))
      }
      check(`[1] ${app}: hair vertexColors + DoubleSide`,
        hair.every((m) => m.material.vertexColors === true && m.material.side === THREE.DoubleSide))
      check(`[1] ${app}: body no vertexColors, FrontSide`,
        body[0].material.vertexColors === false && body[0].material.side === THREE.FrontSide)
    }

    // client3d: the load sequence of figures.ts, then one figure instance
    {
      const template = (await client3dLoader().parseAsync(glb.slice(0), '')).scene
      const before = meshesOf(template).hair.map((m) => m.material)
      // [2]
      const log = zeroFigureMetalness(template)
      const { hair, body } = meshesOf(template)
      check('[2] metalness zeroed on the body', body[0].material.metalness === 0, log.join(' | '))
      check('[2] hair materials are the same objects',
        hair.every((m, i) => m.material === before[i]))
      check('[2] hair still vertexColors + DoubleSide',
        hair.every((m) => m.material.vertexColors && m.material.side === THREE.DoubleSide))
      // [3]
      const tex = texture()
      applyFigureTexture(template, tex)
      check('[3] body got the texture material', body[0].material.map === tex)
      check('[3] hair keeps its own material, no map',
        hair.every((m, i) => m.material === before[i] && !m.material.map && m.material.vertexColors
          && m.material.side === THREE.DoubleSide))
      // [4]
      const inst = SkeletonUtils.clone(template)
      const ih = meshesOf(inst).hair
      check('[4] clone: hair vertexColors + DoubleSide',
        ih.length === prims && ih.every((m) => m.isSkinnedMesh && m.material.vertexColors
          && m.material.side === THREE.DoubleSide))
      // [5]
      const ghost = new SubmergedGhost(inst)
      ghost.set(0.5)
      const parts = ghost.parts
      const hairGhosts = parts.filter((g) => inGarment(g.parent))
      const bodyGhosts = parts.filter((g) => !inGarment(g.parent))
      check(`[5] ghost parts ${prims + 1}`, parts.length === prims + 1, String(parts.length))
      check('[5] hair ghosts vertexColors + DoubleSide',
        hairGhosts.length === prims && hairGhosts.every((g) => g.material.vertexColors === true
          && g.material.side === THREE.DoubleSide),
        hairGhosts.map((g) => `vc=${g.material.vertexColors} side=${g.material.side}`).join(', '))
      check('[5] body ghost no vertexColors, FrontSide',
        bodyGhosts.length === 1 && bodyGhosts[0].material.vertexColors === false
          && bodyGhosts[0].material.side === THREE.FrontSide)
      ghost.dispose()
    }

    // [6] frontend viewer texture route
    {
      const object = (await adminLoader().parseAsync(glb.slice(0), '')).scene
      const tex = texture()
      applyViewerTexture(object, tex)
      const { hair, body } = meshesOf(object)
      check('[6] viewer: body map = texture, colour white',
        body[0].material.map === tex && body[0].material.color.getHex() === 0xffffff)
      check('[6] viewer: hair map null, vertexColors + DoubleSide, colour 1/1/1',
        hair.every((m) => !m.material.map && m.material.vertexColors && m.material.side === THREE.DoubleSide
          && m.material.color.r === 1 && m.material.color.g === 1 && m.material.color.b === 1))
    }
  }

  // [7] the consumers go through these steps
  {
    const root = process.cwd()   // the bundle runs from /tmp with cwd = repo root
    const figures = fs.readFileSync(path.join(root, 'client3d/src/scene/figures.ts'), 'utf8')
    const viewer = fs.readFileSync(path.join(root, 'frontend/src/tabs/characters/Model3DViewer.tsx'), 'utf8')
    const calls = (figures.match(/applyFigureTexture\(template, tex\)/g) || []).length
    check('[7] figures.ts: applyFigureTexture in both texture paths', calls === 2, String(calls))
    check('[7] figures.ts: zeroFigureMetalness(template)', /zeroFigureMetalness\(template\)/.test(figures))
    check('[7] figures.ts: no inline textured material',
      !/new THREE\.MeshStandardMaterial\(\{\s*map:\s*tex/.test(figures))
    check('[7] Model3DViewer: applyViewerTexture(object, tex)', /applyViewerTexture\(object, tex\)/.test(viewer))
    check('[7] Model3DViewer: no own `mat.map = tex`', !/mat\.map = tex/.test(viewer))
  }

  if (failures.length) {
    console.log(`FAILED ${failures.length}: ${failures.join('; ')}`)
    process.exit(1)
  }
  console.log('ALL OK')
}

main().catch((e) => { console.error(e); process.exit(1) })
