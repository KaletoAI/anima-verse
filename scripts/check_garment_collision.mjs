#!/usr/bin/env node
/**
 * Motion check for the GARMENT PUSH — how much of a garment sinks into the
 * body while the real library clips play, before and after the collision
 * capsules push it out (spec `docs/superpowers/specs/2026-11-08-collision-capsules-design.md`,
 * "Numbers, not looks").
 *
 * Usage:
 *   node scripts/check_garment_collision.mjs MODEL.glb [MODEL2.glb …]
 *        [--collision PAYLOAD.json]   collision payload (default: fitted from the GLB by
 *                                     app/core/collision.py::fit_capsules via ./.venv/bin/python)
 *        [--clips walk,run,sit]       clip kinds (default walk,run,sit)
 *        [--set female]               clip set tried before the root set
 *        [--samples 4]                samples per clip at t = k/N · duration
 *        [--spike-sampling]           the spike's fixed 10 points per triangle (comparison only)
 *        [--ply DIR]                  also write the posed meshes (PLY, Blender axes) + render_meta.json
 *        [--json FILE]                write the numbers as JSON
 *   Clips come from ANIMATION_CLIPS_DIR (default shared/models/clips), the retarget
 *   reference from ANIMATION_RIG_FILE (default shared/models/rig/reference.fbx) — read only.
 *   Self-bundling via esbuild; runs without the server and without a world.
 *
 * THE POSE is the 3D client's: the clip is retargeted with client3d's own
 * `adaptExternalClips` (rest corrections against the reference rig, hips
 * height against the reference rig's hips), played by a three AnimationMixer,
 * then every skinned mesh is skinned on the CPU with three's skinning math
 * (cross-checked against `SkinnedMesh.applyBoneTransform`).
 *
 * THE PUSH is the renderers' own: `createGarmentCollision` (scene-render) binds
 * the payload to the figure and decides which garment meshes and capsules;
 * per sample its `update()` takes the capsules into each garment mesh's local
 * space and every garment vertex goes through `pushOutOfCapsules` there — the
 * TypeScript twin of the shader (`scripts/smoke_garment_collision.mjs` proves
 * the twin), weighted by `_collide` when the mesh carries it.
 *
 * METRIC — the S1 spike's `motion_pen.py`, ported: the body's triangles
 * (every skinned mesh outside a garment subtree) are sampled on a barycentric
 * grid into a 4 mm voxel grid (the spike's 10 points per triangle, more for a
 * triangle the pose stretched: samples ≤ 2 mm apart — the spike's fixed 10
 * left gaps in stretched run poses, its body volume leaked and the run
 * numbers read ~0 inside) over the posed figure
 * (bounding box + 3 cm), dilated once (6-neighbourhood), hole-filled from the
 * grid border (6-connectivity) = the body volume; the exact Euclidean distance
 * transform gives each inside voxel its depth; each garment vertex reads its
 * depth trilinearly. Penetration = share of garment vertices deeper than 5 mm.
 * The spike's arm mask indexed the PLY's depth axis instead of the height and
 * so excluded nothing — the spike's numbers include the arms; so does this
 * check (cutting the arm faces out opens the shell at the shoulders and the
 * volume leaks), and `after_inside` names per sample the body region — the
 * dominant bone of the nearest body vertex — the remaining garment vertices
 * sit in. A sample whose body volume LEAKS (the hole fill finds no inside —
 * a one-voxel gap lets the border flood in, so every depth reads ~0) is marked `!` and `body_volume_closed: false`; its share is meaningless (the
 * spike's walk s3 = 0.45 % was such a sample: 1.4 % on a closed volume).
 *
 * HIP SIDES. The torso capsules are deliberately thin (hips p2). The hip band
 * = garment vertices whose BIND height lies between the UpLeg joints − 5 cm
 * and the Spine1 joint; "sides" = that band with |x − Hips.x| ≥ 8 cm. Its
 * penetration is reported separately, and so is the garment split at the
 * Spine1 joint's bind height (lower = skirt/hips, upper = bodice/sleeves).
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
// The bundled copy runs from /tmp with cwd = the repo (set by the self-bundling step below).
const REPO = process.env.SMOKE_BUNDLED ? process.cwd() : path.join(__dirname, '..')

function parseArgs(argv) {
  const opts = { models: [], clips: ['walk', 'run', 'sit'], set: '', samples: 4 }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--collision') opts.collision = argv[++i]
    else if (a === '--clips') opts.clips = argv[++i].split(',').filter(Boolean)
    else if (a === '--set') opts.set = argv[++i]
    else if (a === '--samples') opts.samples = Math.max(1, Number(argv[++i]))
    else if (a === '--spike-sampling') opts.spikeSampling = true
    else if (a === '--ply') opts.ply = argv[++i]
    else if (a === '--json') opts.json = argv[++i]
    else if (a.startsWith('--')) throw new Error(`unknown option ${a}`)
    else opts.models.push(a)
  }
  if (!opts.models.length) throw new Error('usage: check_garment_collision.mjs MODEL.glb [options] (see the docstring)')
  return opts
}

// three is a browser library; the globals the client modules touch at load time.
function stubBrowser() {
  globalThis.self = globalThis
  if (!globalThis.window) globalThis.window = globalThis
  if (!globalThis.document) {
    const el = () => ({ style: {}, getContext: () => null, setAttribute() {}, addEventListener() {} })
    globalThis.document = { createElement: el, createElementNS: el, addEventListener() {}, body: el() }
  }
  if (!globalThis.location) globalThis.location = { href: 'http://localhost/', origin: 'http://localhost' }
}

/** Strip images/textures from a GLB (node cannot decode them); geometry, skins, nodes untouched. */
function stripGlbImages(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength)
  if (dv.getUint32(0, true) !== 0x46546c67) throw new Error('not a GLB')
  let off = 12, json = null, bin = null
  while (off < buf.byteLength) {
    const len = dv.getUint32(off, true), type = dv.getUint32(off + 4, true)
    const chunk = buf.subarray(off + 8, off + 8 + len)
    if (type === 0x4e4f534a) json = JSON.parse(new TextDecoder().decode(chunk))
    else if (type === 0x004e4942) bin = chunk
    off += 8 + len
  }
  delete json.images; delete json.textures; delete json.samplers
  for (const m of json.materials ?? []) {
    const pbr = m.pbrMetallicRoughness
    if (pbr) { delete pbr.baseColorTexture; delete pbr.metallicRoughnessTexture }
    delete m.normalTexture; delete m.occlusionTexture; delete m.emissiveTexture
    for (const e of Object.values(m.extensions ?? {})) for (const k of Object.keys(e)) if (/Texture$/.test(k)) delete e[k]
  }
  const jsonBytes = new TextEncoder().encode(JSON.stringify(json))
  const pad = (n) => (4 - (n % 4)) % 4
  const jlen = jsonBytes.length + pad(jsonBytes.length)
  const blen = bin ? bin.length + pad(bin.length) : 0
  const total = 12 + 8 + jlen + (bin ? 8 + blen : 0)
  const out = new Uint8Array(total)
  const o = new DataView(out.buffer)
  o.setUint32(0, 0x46546c67, true); o.setUint32(4, 2, true); o.setUint32(8, total, true)
  o.setUint32(12, jlen, true); o.setUint32(16, 0x4e4f534a, true)
  out.set(jsonBytes, 20)
  for (let i = jsonBytes.length; i < jlen; i++) out[20 + i] = 0x20
  if (bin) {
    const b = 20 + jlen
    o.setUint32(b, blen, true); o.setUint32(b + 4, 0x004e4942, true)
    out.set(bin, b + 8)
  }
  return out
}

// ---------------------------------------------------------------- the metric (motion_pen.py, ported)
const VOX = 0.004
const DEPTH = 0.005

/** Body volume + depth field for posed positions `pos` (all vertices) and body faces `faces`. */
function depthField(pos, bodyFaces, spikeSampling = false) {
  let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < pos.length; i += 3) for (let k = 0; k < 3; k++) {
    lo[k] = Math.min(lo[k], pos[i + k]); hi[k] = Math.max(hi[k], pos[i + k])
  }
  lo = lo.map((v) => v - 0.03)
  const shape = hi.map((v, k) => Math.ceil((v + 0.03 - lo[k]) / VOX) + 1)
  const [nx, ny, nz] = shape
  const N = nx * ny * nz
  const at = (x, y, z) => (x * ny + y) * nz + z
  const surf = new Uint8Array(N)
  // Barycentric grid per triangle: at least the spike's 4 × 4 (n = 3), finer for a triangle the pose stretched,
  // so that no two samples are more than half a voxel apart (a stretched triangle must not leave a gap).
  const baryOf = []
  const grid = (n) => {
    if (baryOf[n]) return baryOf[n]
    const out = []
    for (let i = 0; i <= n; i++) for (let j = 0; i + j <= n; j++) out.push([1 - (i + j) / n, i / n, j / n])
    return (baryOf[n] = out)
  }
  const len = (p, q) => Math.hypot(pos[p] - pos[q], pos[p + 1] - pos[q + 1], pos[p + 2] - pos[q + 2])
  for (let f = 0; f < bodyFaces.length; f += 3) {
    const a = bodyFaces[f] * 3, b = bodyFaces[f + 1] * 3, c = bodyFaces[f + 2] * 3
    const n = spikeSampling ? 3 : Math.max(3, Math.ceil(Math.max(len(a, b), len(b, c), len(c, a)) / (0.5 * VOX)))
    for (const [w0, w1, w2] of grid(n)) {
      const x = Math.round((pos[a] * w0 + pos[b] * w1 + pos[c] * w2 - lo[0]) / VOX)
      const y = Math.round((pos[a + 1] * w0 + pos[b + 1] * w1 + pos[c + 1] * w2 - lo[1]) / VOX)
      const z = Math.round((pos[a + 2] * w0 + pos[b + 2] * w1 + pos[c + 2] * w2 - lo[2]) / VOX)
      surf[at(x, y, z)] = 1
    }
  }
  // dilation, 6-neighbourhood, border = 0
  const dil = new Uint8Array(N)
  for (let x = 0; x < nx; x++) for (let y = 0; y < ny; y++) for (let z = 0; z < nz; z++) {
    const i = at(x, y, z)
    if (surf[i] || (x > 0 && surf[i - ny * nz]) || (x < nx - 1 && surf[i + ny * nz])
      || (y > 0 && surf[i - nz]) || (y < ny - 1 && surf[i + nz]) || (z > 0 && surf[i - 1]) || (z < nz - 1 && surf[i + 1])) dil[i] = 1
  }
  // fill holes: background reached from the border (6-connectivity) stays outside, the rest is inside
  const outside = new Uint8Array(N)
  const stack = new Int32Array(N)
  let sp = 0
  const seed = (i) => { if (!dil[i] && !outside[i]) { outside[i] = 1; stack[sp++] = i } }
  for (let x = 0; x < nx; x++) for (let y = 0; y < ny; y++) for (let z = 0; z < nz; z++) {
    if (x === 0 || y === 0 || z === 0 || x === nx - 1 || y === ny - 1 || z === nz - 1) seed(at(x, y, z))
  }
  while (sp) {
    const i = stack[--sp]
    const z = i % nz, y = ((i - z) / nz) % ny, x = (i - z - y * nz) / (ny * nz)
    if (x > 0) seed(i - ny * nz); if (x < nx - 1) seed(i + ny * nz)
    if (y > 0) seed(i - nz); if (y < ny - 1) seed(i + nz)
    if (z > 0) seed(i - 1); if (z < nz - 1) seed(i + 1)
  }
  // A body volume that leaks (a gap of one voxel lets the border flood reach the inside) is the dilated shell only:
  // the depth of everything inside it reads ~0. `closed` says whether the fill found an inside at all.
  let shell = 0, inside = 0
  for (let i = 0; i < N; i++) { if (dil[i]) shell++; if (!outside[i]) inside++ }
  const closed = inside - shell > 0.05 * shell
  // exact EDT (Felzenszwalb–Huttenlocher), squared, separable over the three axes
  const INF = 1e20
  const d2 = new Float32Array(N)
  for (let i = 0; i < N; i++) d2[i] = outside[i] ? 0 : INF
  const maxn = Math.max(nx, ny, nz)
  const f = new Float64Array(maxn), out = new Float64Array(maxn), v = new Int32Array(maxn), zz = new Float64Array(maxn + 1)
  const pass1d = (n) => {
    let k = 0
    v[0] = 0; zz[0] = -Infinity; zz[1] = Infinity
    for (let q = 1; q < n; q++) {
      let s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
      while (s <= zz[k]) { k--; s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]) }
      k++; v[k] = q; zz[k] = s; zz[k + 1] = Infinity
    }
    k = 0
    for (let q = 0; q < n; q++) {
      while (zz[k + 1] < q) k++
      out[q] = (q - v[k]) * (q - v[k]) + f[v[k]]
    }
  }
  const axis = (n, count, base, stride) => {
    for (let c = 0; c < count; c++) {
      const b = base(c)
      let any = false
      for (let q = 0; q < n; q++) { f[q] = d2[b + q * stride]; if (f[q] !== 0) any = true }
      if (!any) continue
      pass1d(n)
      for (let q = 0; q < n; q++) d2[b + q * stride] = out[q]
    }
  }
  axis(nz, nx * ny, (c) => c * nz, 1)
  axis(ny, nx * nz, (c) => Math.floor(c / nz) * ny * nz + (c % nz), nz)
  axis(nx, ny * nz, (c) => c, ny * nz)
  /** Depth (m) at a point, trilinear; outside the grid = 0. */
  const depthAt = (px, py, pz) => {
    const gx = (px - lo[0]) / VOX, gy = (py - lo[1]) / VOX, gz = (pz - lo[2]) / VOX
    const x0 = Math.floor(gx), y0 = Math.floor(gy), z0 = Math.floor(gz)
    let sum = 0
    for (let dx = 0; dx <= 1; dx++) for (let dy = 0; dy <= 1; dy++) for (let dz = 0; dz <= 1; dz++) {
      const x = x0 + dx, y = y0 + dy, z = z0 + dz
      const w = (dx ? gx - x0 : 1 - (gx - x0)) * (dy ? gy - y0 : 1 - (gy - y0)) * (dz ? gz - z0 : 1 - (gz - z0))
      if (!w || x < 0 || y < 0 || z < 0 || x >= nx || y >= ny || z >= nz) continue
      sum += w * Math.sqrt(d2[at(x, y, z)]) * VOX
    }
    return sum
  }
  return { depthAt, voxels: N, closed }
}

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/check_garment_collision_bundled.mjs'
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(REPO, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm', `--outfile=${bundlePath}`, '--log-level=error',
    ], { cwd: REPO, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const args = process.argv.slice(2).map((a) => (/\.(glb|json)$/.test(a) || a.includes('/') ? path.resolve(a) : a))
    const run = spawnSync('node', ['--max-old-space-size=8192', bundlePath, ...args], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: REPO,
    })
    process.exit(run.status ?? 1)
  }
  const opts = parseArgs(process.argv.slice(2))
  stubBrowser()
  const THREE = await import('three')
  const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
  const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
  const { MeshoptDecoder } = await import('three/examples/jsm/libs/meshopt_decoder.module.js')
  const SR = await import('../packages/scene-render/src/index.ts')
  const { adaptExternalClips } = await import('../client3d/src/scene/figures.ts')
  const { restPoseOf, restCorrections, rigHipsHeight, normBoneName, inGarment,
    createGarmentCollision, pushOutOfCapsules } = SR

  const arrayBufferOf = (buf) => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)
  const loadFbx = (file) => new FBXLoader().parse(arrayBufferOf(fs.readFileSync(file)), '')
  const clipDir = process.env.ANIMATION_CLIPS_DIR || path.join(REPO, 'shared/models/clips')
  const rigFile = process.env.ANIMATION_RIG_FILE || path.join(REPO, 'shared/models/rig/reference.fbx')

  // ---- clips + donor (read only)
  const library = []
  const clipFiles = {}
  for (const kind of opts.clips) {
    const file = [opts.set && path.join(clipDir, opts.set, `${kind}.fbx`), path.join(clipDir, `${kind}.fbx`)]
      .find((p) => p && fs.existsSync(p))
    if (!file) throw new Error(`no clip for ${kind} in ${clipDir}`)
    const clip = loadFbx(file).animations[0].clone()
    clip.name = kind
    library.push(clip)
    clipFiles[kind] = path.relative(REPO, file)
  }
  const rig = loadFbx(rigFile)
  const donorRest = restPoseOf(THREE, rig)
  const donorHipsY = rigHipsHeight(THREE, rig)

  const report = { clip_files: clipFiles, rig: path.relative(REPO, rigFile), samples: opts.samples,
    spike_sampling: !!opts.spikeSampling, depth_m: DEPTH, voxel_m: VOX, models: {} }
  const plyMeta = { models: {} }

  for (const modelPath of opts.models) {
    const name = path.basename(modelPath).replace(/\.glb$/, '')
    // ---- payload
    let payload
    const payloadFile = opts.models.length === 1 ? opts.collision : null
    if (payloadFile) payload = JSON.parse(fs.readFileSync(payloadFile, 'utf8'))
    else {
      const py = spawnSync(path.join(REPO, '.venv/bin/python'), ['-c',
        'import json,sys\nfrom app.core.collision import fit_capsules\n'
        + 'print(json.dumps(fit_capsules(open(sys.argv[1],"rb").read())))', path.resolve(modelPath)],
      { cwd: REPO, encoding: 'utf8', maxBuffer: 1 << 26 })
      if (py.status !== 0) throw new Error(`fit_capsules failed: ${py.stderr}`)
      payload = JSON.parse(py.stdout)
    }
    // ---- figure, as the client builds it
    const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder)
    const gltf = await loader.parseAsync(arrayBufferOf(stripGlbImages(fs.readFileSync(modelPath))), '')
    const template = gltf.scene
    const b0 = new THREE.Box3().setFromObject(template)
    const s0 = b0.getSize(new THREE.Vector3())
    if (s0.z > s0.y * 1.5) template.rotation.x = -Math.PI / 2
    template.updateMatrixWorld(true)
    const corrections = restCorrections(THREE, donorRest, template)
    const adapted = adaptExternalClips(library.map((c) => c.clone()), template, corrections, donorHipsY)
    const gc = createGarmentCollision(THREE, template, payload)
    if (!gc) throw new Error(`${name}: no colliding garment or no capsules — nothing to check`)
    const bones = new Map()
    template.traverse((o) => { if (o.isBone && !bones.has(normBoneName(o.name))) bones.set(normBoneName(o.name), o) })

    // ---- skinner over every skinned mesh
    const parts = []
    let total = 0
    template.traverse((o) => {
      if (!o.isSkinnedMesh) return
      const g = o.geometry
      const entry = gc.entries.find((e) => e.mesh === o) ?? null
      const w = g.getAttribute('_collide')
      parts.push({ mesh: o, garment: inGarment(o), entry, pos: g.attributes.position, si: g.attributes.skinIndex,
        sw: g.attributes.skinWeight, weight: w ?? null, offset: total, count: g.attributes.position.count })
      total += g.attributes.position.count
    })
    const faceList = []
    for (const p of parts) {
      const idx = p.mesh.geometry.index
      if (idx) for (let i = 0; i < idx.count; i++) faceList.push(idx.getX(i) + p.offset)
      else for (let i = 0; i < p.count; i++) faceList.push(i + p.offset)
    }
    const faces = Uint32Array.from(faceList)
    const dominant = new Array(total)
    for (const p of parts) {
      const names = p.mesh.skeleton.bones.map((b) => normBoneName(b.name))
      for (let i = 0; i < p.count; i++) {
        let best = 0
        for (let j = 1; j < 4; j++) if (p.sw.getComponent(i, j) > p.sw.getComponent(i, best)) best = j
        dominant[p.offset + i] = names[p.si.getComponent(i, best)]
      }
    }
    const isBody = new Uint8Array(total)
    for (const p of parts) if (!p.garment) isBody.fill(1, p.offset, p.offset + p.count)
    const garmentIdx = []
    for (const p of parts) if (p.garment) for (let i = 0; i < p.count; i++) garmentIdx.push(p.offset + i)
    const pos = new Float32Array(total * 3)
    const skin = () => {
      template.updateMatrixWorld(true)
      for (const p of parts) {
        const { mesh } = p
        const mats = mesh.skeleton.bones.map((b, i) => new THREE.Matrix4()
          .multiplyMatrices(mesh.matrixWorld, mesh.bindMatrixInverse)
          .multiply(b.matrixWorld).multiply(mesh.skeleton.boneInverses[i]).multiply(mesh.bindMatrix).elements)
        for (let i = 0; i < p.count; i++) {
          const x = p.pos.getX(i), y = p.pos.getY(i), z = p.pos.getZ(i)
          let ox = 0, oy = 0, oz = 0
          for (let j = 0; j < 4; j++) {
            const w = p.sw.getComponent(i, j)
            if (!w) continue
            const e = mats[p.si.getComponent(i, j)]
            ox += w * (e[0] * x + e[4] * y + e[8] * z + e[12])
            oy += w * (e[1] * x + e[5] * y + e[9] * z + e[13])
            oz += w * (e[2] * x + e[6] * y + e[10] * z + e[14])
          }
          const o = (p.offset + i) * 3
          pos[o] = ox; pos[o + 1] = oy; pos[o + 2] = oz
        }
      }
      return pos
    }
    /** The renderers' push, on the CPU: per garment mesh in ITS local space. */
    const push = (src) => {
      gc.update()
      const out = Float32Array.from(src)
      const inv = new THREE.Matrix4(), v = new THREE.Vector3()
      let moved = 0
      for (const p of parts) {
        if (!p.entry) continue
        inv.copy(p.mesh.matrixWorld).invert()
        for (let i = 0; i < p.count; i++) {
          const o = (p.offset + i) * 3
          v.set(src[o], src[o + 1], src[o + 2]).applyMatrix4(inv)
          const q = pushOutOfCapsules([v.x, v.y, v.z], p.entry.local, p.weight ? p.weight.getX(i) : 1)
          v.set(q[0], q[1], q[2]).applyMatrix4(p.mesh.matrixWorld)
          if (Math.hypot(v.x - src[o], v.y - src[o + 1], v.z - src[o + 2]) > 1e-6) moved++
          out[o] = v.x; out[o + 1] = v.y; out[o + 2] = v.z
        }
      }
      return { out, moved }
    }
    // skin cross-check against three's own skinning
    skin()
    let worst = 0
    for (const p of parts) for (let k = 0; k < 40; k++) {
      const i = Math.floor((k / 40) * p.count)
      const v = new THREE.Vector3().fromBufferAttribute(p.pos, i)
      p.mesh.applyBoneTransform(i, v)
      v.applyMatrix4(p.mesh.matrixWorld)
      const o = (p.offset + i) * 3
      worst = Math.max(worst, Math.hypot(v.x - pos[o], v.y - pos[o + 1], v.z - pos[o + 2]))
    }
    const bind = Float32Array.from(pos)
    // body faces
    const bf = []
    for (let f = 0; f < faces.length; f += 3) {
      const a = faces[f], b = faces[f + 1], c = faces[f + 2]
      if (!isBody[a]) continue
        bf.push(a, b, c)
    }
    const bodyFaces = Uint32Array.from(bf)
    // hip band / sides, by the BIND pose
    const jointY = (key) => bones.get(key)?.getWorldPosition(new THREE.Vector3()) ?? null
    const hipsP = jointY('hips'), upL = jointY('leftupleg'), upR = jointY('rightupleg'), sp1 = jointY('spine1')
    const bandLo = Math.min(upL?.y ?? Infinity, upR?.y ?? Infinity) - 0.05
    const bandHi = sp1?.y ?? -Infinity
    const hipBand = [], hipSides = [], lower = [], upper = []
    for (const i of garmentIdx) (bind[i * 3 + 1] <= bandHi ? lower : upper).push(i)
    for (const i of garmentIdx) {
      const y = bind[i * 3 + 1]
      if (y < bandLo || y > bandHi) continue
      hipBand.push(i)
      if (hipsP && Math.abs(bind[i * 3] - hipsP.x) >= 0.08) hipSides.push(i)
    }
    const mm = report.models[name] = {
      file: modelPath, vertices: total, garment_vertices: garmentIdx.length, body_faces: bodyFaces.length / 3,
      skin_crosscheck_m: worst,
      capsules: gc.entries.map((e) => ({ mesh: e.mesh.name, kind: e.kind, count: e.capsules.length })),
      capsules_missing: gc.binding.missing,
      radii_cm: Object.fromEntries(gc.binding.capsules.map((c) => [c.capsule.id, +(c.capsule.r * 100).toFixed(1)])),
      hip_band: { y: [+bandLo.toFixed(3), +bandHi.toFixed(3)], vertices: hipBand.length, side_vertices: hipSides.length },
      split: { lower_vertices: lower.length, upper_vertices: upper.length },
      clips: {},
    }
    console.log(`== ${name}: ${total} verts (${garmentIdx.length} garment), skin check ${worst.toExponential(2)} m, `
      + `capsules ${mm.capsules.map((c) => `${c.mesh}:${c.count}`).join(' ')}, hip band ${hipBand.length} (sides ${hipSides.length})`)
    if (opts.ply) {
      fs.mkdirSync(path.join(opts.ply, 'meshes'), { recursive: true })
      writePly(path.join(opts.ply, 'meshes', `${name}_bind.ply`), bind, faces)
      plyMeta.models[name] = { parts: parts.map((p) => ({ name: p.garment ? `garment:${p.mesh.name}` : 'mesh', offset: p.offset, count: p.count })) }
    }
    const share = (field, P, idx) => {
      if (!idx.length) return null
      let n = 0
      for (const i of idx) if (field.depthAt(P[i * 3], P[i * 3 + 1], P[i * 3 + 2]) > DEPTH) n++
      return n / idx.length
    }
    const mixer = new THREE.AnimationMixer(template)
    for (const clip of adapted) {
      mixer.stopAllAction()
      mixer.clipAction(clip).reset().play()
      const rows = []
      for (let s = 0; s < opts.samples; s++) {
        const t = (s / opts.samples) * clip.duration
        mixer.setTime(t)
        const before = Float32Array.from(skin())
        const { out: after, moved } = push(before)
        const field = depthField(before, bodyFaces, opts.spikeSampling)
        const row = {
          t: +t.toFixed(3),
          before: share(field, before, garmentIdx), after: share(field, after, garmentIdx),
          hip_sides_before: share(field, before, hipSides), hip_sides_after: share(field, after, hipSides),
          hip_band_after: share(field, after, hipBand), moved_share: moved / garmentIdx.length,
          // the garment split at the Spine1 joint's bind height: below = skirt/hips, above = bodice/sleeves
          lower_before: share(field, before, lower), lower_after: share(field, after, lower),
          upper_before: share(field, before, upper), upper_after: share(field, after, upper),
          body_volume_closed: field.closed,
        }
        // Where the rest sits: for the garment vertices still > 5 mm inside, the dominant bone of the NEAREST
        // body vertex (whose part of the body it is in) — e.g. "leftarm" = inside the arm, "spine2" = the chest.
        const CELL = 0.03
        const hash = new Map()
        const key = (x, y, z) => `${Math.floor(x / CELL)},${Math.floor(y / CELL)},${Math.floor(z / CELL)}`
        for (let i = 0; i < total; i++) {
          if (!isBody[i]) continue
          const k = key(before[i * 3], before[i * 3 + 1], before[i * 3 + 2])
          let list = hash.get(k); if (!list) hash.set(k, list = []); list.push(i)
        }
        const where = {}
        for (const i of garmentIdx) {
          const x = after[i * 3], y = after[i * 3 + 1], z = after[i * 3 + 2]
          if (field.depthAt(x, y, z) <= DEPTH) continue
          let best = Infinity, bi = -1
          const cx = Math.floor(x / CELL), cy = Math.floor(y / CELL), cz = Math.floor(z / CELL)
          for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
            for (const j of hash.get(`${cx + dx},${cy + dy},${cz + dz}`) ?? []) {
              const d = (before[j * 3] - x) ** 2 + (before[j * 3 + 1] - y) ** 2 + (before[j * 3 + 2] - z) ** 2
              if (d < best) { best = d; bi = j }
            }
          }
          const region = bi < 0 ? '?' : dominant[bi]
          where[region] = (where[region] ?? 0) + 1
        }
        row.after_inside = Object.fromEntries(Object.entries(where).sort((x, y) => y[1] - x[1]).slice(0, 8))
        rows.push(row)
        if (opts.ply) {
          writePly(path.join(opts.ply, 'meshes', `${name}_${clip.name}_s${s}.ply`), before, faces)
          writePly(path.join(opts.ply, 'meshes', `${name}c_${clip.name}_s${s}.ply`), after, faces)
        }
      }
      const max = (k) => Math.max(...rows.map((r) => r[k] ?? 0))
      mm.clips[clip.name] = { before_max: max('before'), after_max: max('after'),
        lower_before_max: max('lower_before'), lower_after_max: max('lower_after'),
        upper_before_max: max('upper_before'), upper_after_max: max('upper_after'),
        hip_sides_before_max: max('hip_sides_before'), hip_sides_after_max: max('hip_sides_after'), samples: rows }
      const pct = (v) => v === null || v === undefined ? '—' : `${(v * 100).toFixed(2)}%`
      const open = (r) => (r.body_volume_closed ? '' : '!')
      console.log(`  ${clip.name.padEnd(12)} before ${rows.map((r) => pct(r.before) + open(r)).join(' ')} | after ${rows.map((r) => pct(r.after) + open(r)).join(' ')}`
        + ` | lower ${pct(max('lower_before'))} → ${pct(max('lower_after'))} | upper ${pct(max('upper_before'))} → ${pct(max('upper_after'))}`
        + ` | hip sides ${pct(max('hip_sides_before'))} → ${pct(max('hip_sides_after'))} | moved ${pct(Math.max(...rows.map((r) => r.moved_share)))}`)
    }
    gc.dispose()
  }
  if (opts.json) fs.writeFileSync(opts.json, JSON.stringify(report, null, 1))
  if (opts.ply) {
    for (const [n, m] of Object.entries(plyMeta.models)) plyMeta.models[`${n}c`] = m
    fs.writeFileSync(path.join(opts.ply, 'render_meta.json'), JSON.stringify(plyMeta, null, 1))
  }
}

/** Binary PLY in Blender axes (x, −z, y) — the spike's layout. */
function writePly(file, pos, faces) {
  const nv = pos.length / 3, nf = faces.length / 3
  const header = `ply\nformat binary_little_endian 1.0\nelement vertex ${nv}\nproperty float x\nproperty float y\nproperty float z\n`
    + `element face ${nf}\nproperty list uchar uint vertex_indices\nend_header\n`
  const body = Buffer.alloc(nv * 12 + nf * 13)
  for (let i = 0; i < nv; i++) {
    body.writeFloatLE(pos[i * 3], i * 12)
    body.writeFloatLE(-pos[i * 3 + 2], i * 12 + 4)
    body.writeFloatLE(pos[i * 3 + 1], i * 12 + 8)
  }
  let o = nv * 12
  for (let f = 0; f < nf; f++) {
    body.writeUInt8(3, o); body.writeUInt32LE(faces[f * 3], o + 1)
    body.writeUInt32LE(faces[f * 3 + 1], o + 5); body.writeUInt32LE(faces[f * 3 + 2], o + 9); o += 13
  }
  fs.writeFileSync(file, Buffer.concat([Buffer.from(header, 'ascii'), body]))
}

main().catch((e) => { console.error(e); process.exit(1) })
