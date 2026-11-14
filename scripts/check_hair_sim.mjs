#!/usr/bin/env node
/**
 * Real-hair check of the per-strand hair sim (strand-hair plan 2026-11-13 Task 9, spec § 6.4 "Acceptance on real
 * hair"): the client's own `createStrandHair` (scene-render `hairSim.ts`) on a real fit, driven by the real library
 * clips, measured with the sim's own metrics (`hairSimMath.ts`).
 *
 * Usage:
 *   node scripts/check_hair_sim.mjs ASSEMBLED.glb STRANDS.json [--clips sit,celebrating,walk] [--json FILE]
 *        [--set female] [--loops 2] [--every 6] [--game] [--snap] [--ref REF_STRANDS.json]
 *   ASSEMBLED.glb = a skinned figure whose hair primitive carries `_STRAND_CARD` / `_STRAND_U` (the full tier, or
 *   the Hairstyles preview / `scripts/hair_strands_export.py`'s `<fit>.strands.glb`); STRANDS.json its record.
 *   Clips come from ANIMATION_CLIPS_DIR (default shared/models/clips), the retarget reference from
 *   ANIMATION_RIG_FILE (default shared/models/rig/reference.fbx) — read only. Self-bundling via esbuild; no server,
 *   no world. `--loops` loops per clip at 60 fps, `--every` frames between scalp-exposure samples.
 *
 * THE POSE is the 3D client's, as in `scripts/check_garment_collision.mjs`: client3d's `adaptExternalClips` (rest
 * corrections against the reference rig, hips height), a three AnimationMixer, `updateMatrixWorld`, then the strand
 * handle's `update(1/60)` — the frame order of `Figure.update` (after the mixer, before the secondary motion). The
 * sim starts reset on the clip's first frame (a long delta); the first second is not measured.
 *
 * NUMBERS per clip (spec § 6.4, measured every frame unless said otherwise):
 *  - eye: the most rows inside the eye box that were outside it at rest (`eyePointsEntered`; criterion 0);
 *  - depth: the deepest a free row lies in the head SDF beyond its rest depth (`maxSdfDepthMm`; ≤ 3 mm), with
 *    the same over the rows above the ear line (the cranium), the same number for today's skin in the same frame (`skin depth`: every row at its target) and where the
 *    deepest row sits (its `free_frac` and its head-bind height above the ear line) — the SDF rides the head
 *    rigidly, so a target that follows Neck/Spine2 can lie inside it when the head turns against the neck;
 *  - scalp exposure (`scalpExposure`, every `--every` frames after the first second): the share of the scalp
 *    (the fit body's triangles above the ear line, behind the face plane, inside the head SDF box) the spike's three
 *    head-fixed cameras (back 180°, 135°, 225°; 0.85 m; aimed at the head centre at ear height + 4 cm) see past the
 *    opaque hair, in head-bind space. Reported as the peak minus the BIND rest (`Δ bind`) — the criterion, ≤ +2 pp —
 *    (and its p95 over the samples: a peak of one frame against a held one) and minus today's skin in the same frame (`Δ skin`: every row at its target, what the hair looks like without
 *    the sim) — the share the sim itself adds;
 *  - ms per frame: the handle's update (targets, capsules, steps, rebuild), mean / p95, and its cost EMA;
 *  - stretch (Ruling H-R10): the longest card relative to its target chain (arc of the 17 simulated rows / arc of
 *    their targets), the worst frame's card — criterion ≤ 1.1;
 *  - flyaways (Ruling H-R10): the most cards in one frame whose free chord (last pin → tip, world) lies within 20°
 *    of the horizontal while its target chord hangs more than 45° below it (cards with ≥ 10 cm of free arc).
 *
 * `--game` (Ruling H-R10) moves the figure the way the 3D client does instead of on the spot: its yaw eased towards
 * the wanted facing by client3d's own `easeNpcYaw` (`game/npcWalk.ts`, a 10/s exponential ease — the NPC turning
 * code and the avatar's eased steering), walk at `WALK_SPEED` along a polyline whose corners turn 45°, −90°,
 * 135°, −180° (U-turn), 90°, −45° (2.5 m legs, a waypoint retired within `WAYPOINT_ARRIVE_M`), every other clip on
 * the spot turning 90°, 180°, −90°, 45° every 1.5 s. `--snap` adds the instant turns the client also makes
 * (`faceTowards(…, snap)`: a walk starting backwards, a 180° snap on the spot).
 * `--ref` (Ruling H-R8): a record of the same fit whose SDF reaches below the crop of STRANDS.json; the depth of
 * the rows BELOW the ear line in that SDF, split in front of the head centre (the jaw and cheeks, Head-rigid —
 * a real collision) and behind it (the neck, which the head-rigid SDF misplaces), for the sim and today's skin.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const REPO = process.env.HAIR_SIM_CHECK_BUNDLED ? process.cwd() : path.join(__dirname, '..')

function parseArgs(argv) {
  const opts = { files: [], clips: ['sit', 'celebrating', 'walk'], set: '', loops: 2, every: 6, game: false,
    snap: false, ref: '' }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--clips') opts.clips = argv[++i].split(',').filter(Boolean)
    else if (a === '--json') opts.json = argv[++i]
    else if (a === '--set') opts.set = argv[++i]
    else if (a === '--loops') opts.loops = Math.max(1, Number(argv[++i]))
    else if (a === '--every') opts.every = Math.max(1, Number(argv[++i]))
    else if (a === '--game') opts.game = true
    else if (a === '--snap') opts.snap = true
    else if (a === '--ref') opts.ref = argv[++i]
    else if (a.startsWith('--')) throw new Error(`unknown option ${a}`)
    else opts.files.push(a)
  }
  if (opts.files.length !== 2) throw new Error('usage: check_hair_sim.mjs ASSEMBLED.glb STRANDS.json [options]')
  return opts
}

function stubBrowser() {
  globalThis.self = globalThis
  if (!globalThis.window) globalThis.window = globalThis
  if (!globalThis.document) {
    const el = () => ({ style: {}, getContext: () => null, setAttribute() {}, addEventListener() {} })
    globalThis.document = { createElement: el, createElementNS: el, addEventListener() {}, body: el() }
  }
  if (!globalThis.location) globalThis.location = { href: 'http://localhost/', origin: 'http://localhost' }
}

/** A GLB without images/textures (node cannot decode them); geometry, skins and nodes untouched. */
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

const pct = (v) => +(v * 100).toFixed(2)
const quantile = (xs, q) => {
  const s = [...xs].sort((a, b) => a - b)
  return s.length ? s[Math.min(s.length - 1, Math.floor(q * s.length))] : 0
}

async function main() {
  if (!process.env.HAIR_SIM_CHECK_BUNDLED) {
    const bundlePath = `/tmp/check_hair_sim_bundled.${process.pid}.mjs`
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(REPO, rel)).find((p) => fs.existsSync(p))
    if (!bin) { console.error('esbuild not found (npm install) — nothing was checked'); process.exit(1) }
    const built = spawnSync(bin, [__filename, '--bundle', '--platform=node', '--format=esm', `--outfile=${bundlePath}`,
      '--log-level=error'], { cwd: REPO, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const args = process.argv.slice(2).map((a) => (/\.(glb|json)$/.test(a) || a.includes('/') ? path.resolve(a) : a))
    const run = spawnSync('node', ['--max-old-space-size=8192', bundlePath, ...args], {
      stdio: 'inherit', env: { ...process.env, HAIR_SIM_CHECK_BUNDLED: '1' }, cwd: REPO })
    spawnSync('rm', ['-f', bundlePath])
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
  const { easeNpcYaw, facingYaw, WALK_SPEED, WAYPOINT_ARRIVE_M } = await import('../client3d/src/game/npcWalk.ts')
  const { restPoseOf, restCorrections, rigHipsHeight, normBoneName, inGarment, createStrandHair, jointNowFrom,
    invertAffine, eyePointsEntered, restInsideBox, maxSdfDepthMm, scalpCameras, scalpExposure } = SR

  const [modelPath, recordPath] = opts.files
  const record = JSON.parse(fs.readFileSync(recordPath, 'utf8'))
  const arrayBufferOf = (buf) => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)
  const loadFbx = (file) => new FBXLoader().parse(arrayBufferOf(fs.readFileSync(file)), '')
  const clipDir = process.env.ANIMATION_CLIPS_DIR || path.join(REPO, 'shared/models/clips')
  const rigFile = process.env.ANIMATION_RIG_FILE || path.join(REPO, 'shared/models/rig/reference.fbx')
  const library = [], clipFiles = {}
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

  const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder)
  const gltf = await loader.parseAsync(arrayBufferOf(stripGlbImages(fs.readFileSync(modelPath))), '')
  const template = gltf.scene
  const b0 = new THREE.Box3().setFromObject(template)
  const s0 = b0.getSize(new THREE.Vector3())
  if (s0.z > s0.y * 1.5) template.rotation.x = -Math.PI / 2
  // The figure's root (client: `Figure.root`, turned and moved by the game; `--game`).
  const holder = new THREE.Group()
  holder.add(template)
  holder.updateMatrixWorld(true)
  const corrections = restCorrections(THREE, donorRest, template)
  const adapted = adaptExternalClips(library.map((c) => c.clone()), template, corrections, donorHipsY)

  const handle = createStrandHair(THREE, template, record)
  if (!handle) throw new Error('createStrandHair refused the model + record (no binding, or StrandMismatch)')
  handle.setEnabled(true)
  const { mesh, sim } = handle
  const headIdx = mesh.skeleton.bones.findIndex((b) => normBoneName(b.name) === normBoneName(record.head_bone))
  const headNow = () => jointNowFrom(mesh.matrixWorld.elements, mesh.bindMatrixInverse.elements,
    mesh.skeleton.bones[headIdx].matrixWorld.elements, mesh.skeleton.boneInverses[headIdx].elements,
    mesh.bindMatrix.elements).bindToWorld

  // The scalp (head-bind space = the GLB's bind space): body triangles above the ear line, behind the face plane,
  // inside the head SDF box (cx ± 0.15, cz ± 0.16 — `hair_strands.SDF_HALF_X` / `SDF_HALF_Z`).
  const sdf = record.sdf
  const cx = sdf.lo[0] + 0.15, cz = sdf.lo[2] + 0.16, top = sdf.lo[1] + sdf.vox * (sdf.dims[1] - 1)
  const scalpList = []
  template.traverse((o) => {
    if (!o.isSkinnedMesh || inGarment(o)) return
    const p = o.geometry.getAttribute('position'), idx = o.geometry.index
    const n = idx ? idx.count : p.count
    for (let t = 0; t + 2 < n; t += 3) {
      const v = [0, 1, 2].map((k) => (idx ? idx.getX(t + k) : t + k))
      const ok = v.every((i) => p.getY(i) > record.ear_y && p.getY(i) < top && p.getZ(i) < record.face_box[4]
        && Math.abs(p.getX(i) - cx) < 0.15 && Math.abs(p.getZ(i) - cz) < 0.16)
      if (ok) for (const i of v) scalpList.push(p.getX(i), p.getY(i), p.getZ(i))
    }
  })
  const scalp = Float32Array.from(scalpList)
  const cams = scalpCameras([cx, record.ear_y + 0.04, cz])
  const hairIdx = mesh.geometry.index
  const hairTris = new Float32Array((hairIdx ? hairIdx.count : mesh.geometry.getAttribute('position').count) * 3)
  const trisOf = (pos) => {
    const n = hairTris.length / 3
    for (let t = 0; t < n; t++) {
      const i = hairIdx ? hairIdx.getX(t) : t
      hairTris[3 * t] = pos[3 * i]; hairTris[3 * t + 1] = pos[3 * i + 1]; hairTris[3 * t + 2] = pos[3 * i + 2]
    }
    return hairTris
  }
  const posAttr = () => mesh.geometry.getAttribute('position').array
  // today's skin in the same frame: every row at its target, rebuilt into scratch arrays
  const skinPos = new Float32Array(posAttr().length), skinNrm = new Float32Array(posAttr().length)
  const saved = new Float32Array(sim.X.length)
  const skinExposure = (head) => {
    saved.set(sim.X)
    sim.X.set(handle.targets)
    sim.rebuild(invertAffine(head), skinPos, skinNrm)
    sim.X.set(saved)
    return scalpExposure(trisOf(skinPos), scalp, cams)
  }
  const restEye = restInsideBox(sim, record.eye_box)
  /** The deepest free row beyond its rest depth (as `maxSdfDepthMm`) and where it is. */
  const deepest = (head) => {
    const inv = invertAffine(head), X = sim.X, C0 = sim.binding.C0
    let deep = 0, at = -1, y = 0, deepAbove = 0
    for (let q = 0; q < sim.n; q++) {
      if (sim.pin[q]) continue
      const x0 = X[3 * q], y0 = X[3 * q + 1], z0 = X[3 * q + 2]
      const hy = inv[1] * x0 + inv[5] * y0 + inv[9] * z0 + inv[13]
      const now = SR.strandSdfAt(sim.sdf, inv[0] * x0 + inv[4] * y0 + inv[8] * z0 + inv[12], hy,
        inv[2] * x0 + inv[6] * y0 + inv[10] * z0 + inv[14])
      const d = Math.min(0, SR.strandSdfAt(sim.sdf, C0[3 * q], C0[3 * q + 1], C0[3 * q + 2])) - now
      if (d > deep) { deep = d; at = q; y = hy }
      if (hy > record.ear_y && d > deepAbove) deepAbove = d
    }
    return { mm: deep * 1000, frac: at < 0 ? 0 : record.free_frac[at], above_ear_cm: (y - record.ear_y) * 100,
      above_ear_mm: deepAbove * 1000 }
  }
  const skinDepth = (head) => {
    saved.set(sim.X)
    sim.X.set(handle.targets)
    const d = deepest(head).mm
    sim.X.set(saved)
    return d
  }
  // Ruling H-R10: card length against its target chain, and the near-horizontal flyaways (module docstring).
  const R = 17, S = record.cards
  const cardStretch = () => {
    const X = sim.X, T = handle.targets
    let worst = 0, card = -1
    for (let c = 0; c < S; c++) {
      let ax = 0, at = 0
      for (let i = 1; i < R; i++) {
        const o = 3 * (c * R + i), b = o - 3
        ax += Math.hypot(X[o] - X[b], X[o + 1] - X[b + 1], X[o + 2] - X[b + 2])
        at += Math.hypot(T[o] - T[b], T[o + 1] - T[b + 1], T[o + 2] - T[b + 2])
      }
      const r = at > 1e-6 ? ax / at : 1
      if (r > worst) { worst = r; card = c }
    }
    return { ratio: worst, card }
  }
  const elev = (dx, dy, dz) => Math.atan2(dy, Math.hypot(dx, dz)) * 180 / Math.PI
  const flyaways = () => {
    const X = sim.X, T = handle.targets, out = []
    for (let c = 0; c < S; c++) {
      if (record.free_arc[c * R + R - 1] < 0.10) continue
      const lp = 3 * (c * R + Math.max(1, record.pins[c]) - 1), tp = 3 * (c * R + R - 1)
      const te = elev(T[tp] - T[lp], T[tp + 1] - T[lp + 1], T[tp + 2] - T[lp + 2])
      if (te > -45) continue
      if (elev(X[tp] - X[lp], X[tp + 1] - X[lp + 1], X[tp + 2] - X[lp + 2]) >= -20) out.push(c)
    }
    return out
  }
  // Ruling H-R8: rows below the ear line in the reference SDF (front: the jaw and cheeks; back: the neck).
  const ref = opts.ref ? SR.decodeStrandSdf(JSON.parse(fs.readFileSync(opts.ref, 'utf8')).sdf) : null
  const bandDepth = (head, pts) => {
    const inv = invertAffine(head), C0 = sim.binding.C0
    let front = 0, back = 0
    for (let q = 0; q < sim.n; q++) {
      if (sim.pin[q]) continue
      const x0 = pts[3 * q], y0 = pts[3 * q + 1], z0 = pts[3 * q + 2]
      const hy = inv[1] * x0 + inv[5] * y0 + inv[9] * z0 + inv[13]
      if (hy >= record.ear_y) continue
      const hx = inv[0] * x0 + inv[4] * y0 + inv[8] * z0 + inv[12], hz = inv[2] * x0 + inv[6] * y0 + inv[10] * z0 + inv[14]
      const d = Math.min(0, SR.strandSdfAt(ref, C0[3 * q], C0[3 * q + 1], C0[3 * q + 2])) - SR.strandSdfAt(ref, hx, hy, hz)
      if (hz > cz) front = Math.max(front, d); else back = Math.max(back, d)
    }
    return [front * 1000, back * 1000]
  }

  /** The root motion of `--game` (module docstring): per frame the root's yaw and position. */
  const DT = 1 / 60
  const gameMotion = (kind) => {
    const turns = [45, -90, 135, -180, 90, -45]
    const st = { x: 0, z: 0, yaw: 0, target: 0, t: 0, leg: 0, way: [], snaps: 0 }
    if (kind === 'walk') {
      let h = 0, px = 0, pz = 0
      for (let i = 0; i <= turns.length; i++) {
        px += 2.5 * Math.sin(h); pz += 2.5 * Math.cos(h)
        st.way.push({ x: px, z: pz })
        if (i < turns.length) h += turns[i] * Math.PI / 180
      }
      if (opts.snap) { st.yaw = Math.PI; st.target = Math.PI }    // facing back: the walk starts with a snap
    }
    return () => {
      st.t += DT
      if (kind === 'walk') {
        let w = st.way[st.leg]
        if (w && Math.hypot(w.x - st.x, w.z - st.z) < WAYPOINT_ARRIVE_M && st.leg < st.way.length - 1) w = st.way[++st.leg]
        if (!w) w = st.way.at(-1)
        const dx = w.x - st.x, dz = w.z - st.z, dist = Math.hypot(dx, dz)
        if (dist > 1e-3) {
          const yaw = facingYaw({ x: dx, y: 0, z: dz })
          if (opts.snap && st.t <= DT * 1.5) { st.yaw = yaw; st.snaps++ }    // `faceTowards(dir, true)` at the start
          st.target = yaw
          const step = Math.min(dist, WALK_SPEED * DT)
          st.x += dx / dist * step; st.z += dz / dist * step
        }
        if (st.leg === st.way.length - 1 && dist < 1e-3) {             // the end: back to the start
          st.way.reverse(); st.leg = 0
        }
      } else if (kind !== 'sit') {
        const k = Math.floor(st.t / 1.5), at = [0, 90, 270, 180, 225]
        const want = at[k % at.length] * Math.PI / 180
        if (opts.snap && k % at.length === 3 && st.target !== want) { st.yaw = want; st.snaps++ }   // a 180° snap
        st.target = want
      }
      st.yaw = easeNpcYaw(st.yaw, st.target, DT)
      holder.position.set(st.x, 0, st.z)
      holder.rotation.y = st.yaw
    }
  }

  const bindExposure = scalpExposure(trisOf(posAttr()), scalp, cams)
  console.log(`== ${path.basename(modelPath)}: ${record.cards} cards, ${sim.n} rows, `
    + `${posAttr().length / 3} hair vertices, scalp ${scalp.length / 9} triangles, colliders [${handle.capsuleIds.join(', ')}]`)
  console.log(`   bind rest exposure (back/135/225): ${bindExposure.map(pct).join(' / ')} %`)

  const report = { model: path.basename(modelPath), record: path.basename(recordPath), game: opts.game, snap: opts.snap,
    cards: record.cards,
    rows: sim.n, colliders: handle.capsuleIds, clip_files: clipFiles, bind_exposure_pct: bindExposure.map(pct),
    clips: {} }
  for (const clip of adapted) {
    const mixer = new THREE.AnimationMixer(template)
    const action = mixer.clipAction(clip)
    action.play()
    mixer.setTime(0)
    holder.position.set(0, 0, 0)
    holder.rotation.y = 0
    const move = opts.game ? gameMotion(clip.name) : null
    holder.updateMatrixWorld(true)
    handle.update(1)   // a long delta: reset to this pose
    const frames = Math.max(opts.game ? 900 : 120, Math.round(clip.duration * opts.loops / DT))
    let eye = 0, depth = 0, skinDeep = 0, where = null, above = 0
    let stretch = { ratio: 0, card: -1, frame: 0 }, fly = { count: 0, cards: [], frame: 0 }, flyFrames = 0
    const band = [0, 0], skinBand = [0, 0]
    const series = [[], [], []]
    const peakBind = [0, 0, 0], peakSkin = [-1, -1, -1], peakAbs = [0, 0, 0], ms = []
    for (let f = 1; f <= frames; f++) {
      move?.()
      mixer.update(DT)
      holder.updateMatrixWorld(true)
      const t0 = performance.now()
      handle.update(DT)
      ms.push(performance.now() - t0)
      if (f < 60) continue
      const st = cardStretch()
      if (st.ratio > stretch.ratio) stretch = { ...st, frame: f }
      const fl = flyaways()
      if (fl.length) flyFrames++
      if (fl.length > fly.count) fly = { count: fl.length, cards: fl.slice(0, 12), frame: f }
      const head = headNow()
      if (ref) {
        const b = bandDepth(head, sim.X), sb = bandDepth(head, handle.targets)
        for (let k = 0; k < 2; k++) { band[k] = Math.max(band[k], b[k]); skinBand[k] = Math.max(skinBand[k], sb[k]) }
      }
      eye = Math.max(eye, eyePointsEntered(sim, head, record.eye_box, restEye))
      const d = maxSdfDepthMm(sim, head, sim.sdf)
      const w = deepest(head)
      above = Math.max(above, w.above_ear_mm)
      if (d > depth) { depth = d; where = w }
      skinDeep = Math.max(skinDeep, skinDepth(head))
      if (f % opts.every) continue
      const now = scalpExposure(trisOf(posAttr()), scalp, cams)
      const skin = skinExposure(head)
      for (let c = 0; c < 3; c++) {
        peakAbs[c] = Math.max(peakAbs[c], now[c])
        peakBind[c] = Math.max(peakBind[c], now[c] - bindExposure[c])
        series[c].push(now[c] - bindExposure[c])
        peakSkin[c] = Math.max(peakSkin[c], now[c] - skin[c])
      }
    }
    mixer.stopAllAction()
    mixer.uncacheRoot(template)
    const mean = ms.reduce((a, b) => a + b, 0) / ms.length
    const row = { frames, eye_rows_entered: eye, max_sdf_depth_mm: +depth.toFixed(2),
      skin_sdf_depth_mm: +skinDeep.toFixed(2), above_ear_depth_mm: +above.toFixed(2),
      delta_bind_p95_pp: series.map((xs) => pct(quantile(xs, 0.95))),
      deepest_row: where && { free_frac: +where.frac.toFixed(2), above_ear_cm: +where.above_ear_cm.toFixed(1) },
      peak_exposure_pct: peakAbs.map(pct), delta_bind_pp: peakBind.map(pct), delta_skin_pp: peakSkin.map(pct),
      ms_per_frame_mean: +mean.toFixed(2), ms_per_frame_p95: +quantile(ms, 0.95).toFixed(2),
      cost_ema_ms: +handle.costMs.toFixed(2),
      max_card_stretch: +stretch.ratio.toFixed(3), stretch_card: stretch.card, stretch_frame: stretch.frame,
      max_flyaways: fly.count, flyaway_cards: fly.cards, flyaway_frame: fly.frame, flyaway_frames: flyFrames,
      ...(ref ? { below_ear_front_mm: +band[0].toFixed(2), below_ear_back_mm: +band[1].toFixed(2),
        skin_below_ear_front_mm: +skinBand[0].toFixed(2), skin_below_ear_back_mm: +skinBand[1].toFixed(2) } : {}) }
    report.clips[clip.name] = row
    console.log(`   ${clip.name.padEnd(12)} eye ${eye}  depth ${row.max_sdf_depth_mm} mm (above the ear line ${row.above_ear_depth_mm}; skin ${row.skin_sdf_depth_mm}`
      + `${where ? `, deepest at frac ${row.deepest_row.free_frac}, ${row.deepest_row.above_ear_cm} cm above the ear line` : ''})  `
      + `Δ bind ${row.delta_bind_pp.join(' / ')} pp (p95 ${row.delta_bind_p95_pp.join(' / ')})  Δ skin ${row.delta_skin_pp.join(' / ')} pp  `
      + `${row.ms_per_frame_mean} ms/frame (p95 ${row.ms_per_frame_p95})`)
    console.log(`   ${''.padEnd(12)} stretch ${row.max_card_stretch} (card ${row.stretch_card}, frame ${row.stretch_frame})  `
      + `flyaways ${row.max_flyaways} (frame ${row.flyaway_frame}, ${row.flyaway_frames} frames; cards ${row.flyaway_cards.join(',')})`
      + (ref ? `  below the ear line in the reference SDF: front ${row.below_ear_front_mm} / back ${row.below_ear_back_mm} mm`
        + ` (skin ${row.skin_below_ear_front_mm} / ${row.skin_below_ear_back_mm})` : ''))
  }
  if (opts.json) fs.writeFileSync(opts.json, JSON.stringify(report, null, 2))
}

main().catch((e) => { console.error(e); process.exit(1) })
