#!/usr/bin/env node
/**
 * Motion check for EXTENSION-BONE CONTACT — how deep the tips of the secondary-motion links sink into
 * the body's collision capsules while the real library clips play, with the contact off and on
 * (`createSecondaryMotion(...).setCollision`, packages/scene-render/src/secondaryMotion.ts; spec
 * `docs/superpowers/specs/2026-11-08-collision-capsules-design.md`, "Numbers, not looks").
 *
 * Usage:
 *   node scripts/check_extension_collision.mjs MODEL.glb --motion MOTION.json
 *        [--collision PAYLOAD.json]   collision payload (default: fitted from the GLB by
 *                                     app/core/collision.py::fit_capsules via ./.venv/bin/python)
 *        [--clips celebrating,walk]   clip kinds (default celebrating,walk)
 *        [--scan]                     contact OFF only, every clip in the clip directory, ranked by tip depth
 *        [--set female]               clip set tried before the root set
 *        [--fps 60] [--loops 2]       simulation rate; loops played, the LAST one is measured
 *        [--json FILE]                write the numbers as JSON
 *   MOTION.json = the `motion` payload of `GET /characters/{name}/model3d` (`{"rev", "groups"}`).
 *   Clips from ANIMATION_CLIPS_DIR (default shared/models/clips), the retarget reference from
 *   ANIMATION_RIG_FILE (default shared/models/rig/reference.fbx) — read only. Self-bundling via
 *   esbuild; runs without the server and without a world.
 *
 * THE POSE is the 3D client's: `adaptExternalClips` of client3d (rest corrections and hips height
 * against the reference rig), a three AnimationMixer stepped at --fps, then the secondary motion of
 * @anima/scene-render stepped with the same dt — exactly the client's frame order.
 *
 * THE TIPS are the renderers' own: `contactTips()` names every link with contacts, its bone-frame tip
 * (next chain joint, else twice the centroid lever) and the capsules it is kept outside of (the
 * chain's ancestor capsules already excluded). Both runs (off/on) measure the same tips:
 * world tip = bone.matrixWorld · tipLocal.
 *
 * METRIC per clip and run, over every (frame, tip) of the measured loop:
 *  - `inside` = share deeper than 1 mm into a contact capsule under the bind rule (radius × the tip's
 *    bind factor — what the contact is meant to remove); `depth_max_mm` / `depth_p95_mm` of those;
 *    `nominal_inside` the same against the plain radii; `worst` = capsule and frame of the deepest.
 *  - COLLAPSE: `offset_*_mm` = distance of the tip from its REST tip (parent.matrixWorld · bind local ·
 *    tipLocal — where the tip sits when the link rides its parent rigidly), p50/p95/max, and
 *    `swing_max_deg` = the largest angle between the rendered and the rest lever. A contact that
 *    folds a link away shows up as an offset beyond the off-run's range.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const REPO = process.env.SMOKE_BUNDLED ? process.cwd() : path.join(__dirname, '..')

function parseArgs(argv) {
  const opts = { models: [], clips: ['celebrating', 'walk'], set: '', fps: 60, loops: 2 }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--collision') opts.collision = argv[++i]
    else if (a === '--motion') opts.motion = argv[++i]
    else if (a === '--clips') opts.clips = argv[++i].split(',').filter(Boolean)
    else if (a === '--scan') opts.scan = true
    else if (a === '--set') opts.set = argv[++i]
    else if (a === '--fps') opts.fps = Math.max(10, Number(argv[++i]))
    else if (a === '--loops') opts.loops = Math.max(1, Number(argv[++i]))
    else if (a === '--json') opts.json = argv[++i]
    else if (a.startsWith('--')) throw new Error(`unknown option ${a}`)
    else opts.models.push(a)
  }
  if (opts.models.length !== 1 || !opts.motion) throw new Error('usage: check_extension_collision.mjs MODEL.glb --motion MOTION.json [options]')
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

const quantile = (sorted, q) => (sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))] : 0)
const mm = (m) => +(m * 1000).toFixed(1)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/check_extension_collision_bundled.mjs'
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(REPO, rel)).find((p) => fs.existsSync(p))
    if (!bin) { console.error('esbuild not found (npm install) — nothing was checked'); process.exit(1) }
    const built = spawnSync(bin, [__filename, '--bundle', '--platform=node', '--format=esm', `--outfile=${bundlePath}`,
      '--log-level=error'], { cwd: REPO, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const args = process.argv.slice(2).map((a) => (/\.(glb|json)$/.test(a) || a.includes('/') ? path.resolve(a) : a))
    const run = spawnSync('node', ['--max-old-space-size=8192', bundlePath, ...args], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: REPO })
    process.exit(run.status ?? 1)
  }
  const opts = parseArgs(process.argv.slice(2))
  stubBrowser()
  const THREE = await import('three')
  const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
  const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
  const { MeshoptDecoder } = await import('three/examples/jsm/libs/meshopt_decoder.module.js')
  const SkeletonUtils = await import('three/examples/jsm/utils/SkeletonUtils.js')
  const SR = await import('../packages/scene-render/src/index.ts')
  const { adaptExternalClips } = await import('../client3d/src/scene/figures.ts')
  const { restPoseOf, restCorrections, rigHipsHeight, createSecondaryMotion, bindCollision, tipBindFactors } = SR

  const arrayBufferOf = (buf) => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)
  const loadFbx = (file) => new FBXLoader().parse(arrayBufferOf(fs.readFileSync(file)), '')
  const clipDir = process.env.ANIMATION_CLIPS_DIR || path.join(REPO, 'shared/models/clips')
  const rigFile = process.env.ANIMATION_RIG_FILE || path.join(REPO, 'shared/models/rig/reference.fbx')
  const modelPath = opts.models[0]
  const motion = JSON.parse(fs.readFileSync(opts.motion, 'utf8'))

  let payload
  if (opts.collision) payload = JSON.parse(fs.readFileSync(opts.collision, 'utf8'))
  else {
    const py = spawnSync(path.join(REPO, '.venv/bin/python'), ['-c',
      'import json,sys\nfrom app.core.collision import fit_capsules\n'
      + 'print(json.dumps(fit_capsules(open(sys.argv[1],"rb").read())))', path.resolve(modelPath)],
    { cwd: REPO, encoding: 'utf8', maxBuffer: 1 << 26 })
    if (py.status !== 0) throw new Error(`fit_capsules failed: ${py.stderr}`)
    payload = JSON.parse(py.stdout)
  }

  const kinds = opts.scan
    ? [...new Set(fs.readdirSync(clipDir).filter((f) => /^[^_]+\.fbx$/.test(f)).map((f) => f.replace(/\.fbx$/, '')))].sort()
    : opts.clips
  const library = []
  const clipFiles = {}
  for (const kind of kinds) {
    const file = [opts.set && path.join(clipDir, opts.set, `${kind}.fbx`), path.join(clipDir, `${kind}.fbx`)]
      .find((p) => p && fs.existsSync(p))
    if (!file) throw new Error(`no clip for ${kind} in ${clipDir}`)
    try {
      const clip = loadFbx(file).animations[0]?.clone()
      if (!clip) continue
      clip.name = kind
      library.push(clip)
      clipFiles[kind] = path.relative(REPO, file)
    } catch (e) { console.log(`  skip ${kind}: ${e.message}`) }
  }
  const rig = loadFbx(rigFile)
  const donorRest = restPoseOf(THREE, rig)
  const donorHipsY = rigHipsHeight(THREE, rig)

  const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder)
    .parseAsync(arrayBufferOf(stripGlbImages(fs.readFileSync(modelPath))), '')
  const template = gltf.scene
  const s0 = new THREE.Box3().setFromObject(template).getSize(new THREE.Vector3())
  if (s0.z > s0.y * 1.5) template.rotation.x = -Math.PI / 2
  template.updateMatrixWorld(true)
  const adapted = adaptExternalClips(library.map((c) => c.clone()), template, restCorrections(THREE, donorRest, template), donorHipsY)

  // The tips, their contacts and bind factors — from a figure in the bind pose with the contact on.
  const probe = SkeletonUtils.clone(template)
  probe.updateMatrixWorld(true)
  const probeMotion = createSecondaryMotion(THREE, probe, motion, template)
  probeMotion.setCollision(payload)
  const tips = probeMotion.contactTips()
  if (!tips.length) throw new Error('no link with contacts (no extension bones, no capsules, or none outside the ancestors)')
  const probeBinding = bindCollision(THREE, probe, payload)
  const byId = new Map(probeBinding.capsules.map((c) => [c.capsule.id, c]))
  for (const t of tips) {
    const contacts = t.capsules.map((id) => byId.get(id))
    t.factors = tipBindFactors(t.tip, contacts.map((c) => c.now))
    t.ancestorCapsules = probeBinding.capsules.filter((c) => !t.capsules.includes(c.capsule.id)).map((c) => c.capsule.id)
  }
  probeMotion.dispose()
  const report = { model: modelPath, clip_files: clipFiles, fps: opts.fps, loops: opts.loops, motion_rev: motion.rev,
    tips: tips.map((t) => ({ bone: t.bone, tip_local: t.tipLocal.map((x) => +x.toFixed(4)), contacts: t.capsules,
      bind_factor: Object.fromEntries(t.capsules.map((id, i) => [id, +t.factors[i].toFixed(3)])), excluded: t.ancestorCapsules })),
    capsules_missing: probeBinding.missing, clips: {} }
  console.log(`== ${path.basename(modelPath)}: ${tips.length} tips`)
  for (const t of report.tips) console.log(`  ${t.bone}: contacts ${t.contacts.join(' ')} | excluded (ancestors) ${t.excluded.join(' ')}`
    + ` | bind factor < 1: ${Object.entries(t.bind_factor).filter(([, f]) => f < 1).map(([k, f]) => `${k} ${f}`).join(' ') || '—'}`)

  const runs = opts.scan ? [false] : [false, true]
  for (const clip of adapted) {
    const row = report.clips[clip.name] = {}
    for (const on of runs) {
      const fig = SkeletonUtils.clone(template)
      fig.updateMatrixWorld(true)
      const sm = createSecondaryMotion(THREE, fig, motion, template)
      if (on) sm.setCollision(payload)
      const binding = bindCollision(THREE, fig, payload)
      const bones = new Map()
      fig.traverse((o) => { if (o.isBone) bones.set(o.name, o) })
      const tb = tips.map((t) => {
        const bone = bones.get(t.bone)
        return { t, bone, local: bone.matrix.clone(), tipLocal: new THREE.Vector3(...t.tipLocal),
          caps: t.capsules.map((id) => binding.capsules.find((c) => c.capsule.id === id)) }
      })
      const mixer = new THREE.AnimationMixer(fig)
      mixer.clipAction(clip).play()
      const dt = 1 / opts.fps
      const frames = Math.max(1, Math.round(clip.duration * opts.fps))
      const depths = [], nominal = [], offsets = []
      let swingMax = 0, worst = { depth: 0 }
      const tip = new THREE.Vector3(), rest = new THREE.Vector3(), head = new THREE.Vector3(), restHead = new THREE.Vector3()
      const restWorld = new THREE.Matrix4()
      for (let loop = 0; loop < opts.loops; loop++) {
        for (let f = 0; f < frames; f++) {
          mixer.update(dt)
          fig.updateMatrixWorld(true)
          sm.update(dt)
          if (loop !== opts.loops - 1) continue
          binding.update()
          for (const { t, bone, local, tipLocal, caps } of tb) {
            tip.copy(tipLocal).applyMatrix4(bone.matrixWorld)
            restWorld.multiplyMatrices(bone.parent.matrixWorld, local)
            rest.copy(tipLocal).applyMatrix4(restWorld)
            head.setFromMatrixPosition(bone.matrixWorld)
            restHead.setFromMatrixPosition(restWorld)
            offsets.push(tip.distanceTo(rest))
            swingMax = Math.max(swingMax, tip.clone().sub(head).angleTo(rest.clone().sub(restHead)) * 180 / Math.PI)
            let deep = 0, deepNominal = 0, capsule = ''
            caps.forEach((c, i) => {
              const [a, b] = [c.now.a, c.now.b]
              const ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]]
              const ap = [tip.x - a[0], tip.y - a[1], tip.z - a[2]]
              const l2 = ab[0] ** 2 + ab[1] ** 2 + ab[2] ** 2
              const s = l2 > 1e-12 ? Math.min(1, Math.max(0, (ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / l2)) : 0
              const d = Math.hypot(ap[0] - ab[0] * s, ap[1] - ab[1] * s, ap[2] - ab[2] * s)
              const e = c.now.r * t.factors[i] - d
              if (e > deep) { deep = e; capsule = c.capsule.id }
              deepNominal = Math.max(deepNominal, c.now.r - d)
            })
            depths.push(deep); nominal.push(deepNominal)
            if (deep > worst.depth) worst = { depth: deep, capsule, bone: t.bone, frame: f, t: +(f / frames).toFixed(3) }
          }
        }
      }
      sm.dispose()
      const inside = depths.filter((d) => d > 0.001).sort((a, b) => a - b)
      const nominalInside = nominal.filter((d) => d > 0.001).length
      const off = [...offsets].sort((a, b) => a - b)
      row[on ? 'on' : 'off'] = {
        samples: depths.length,
        inside: +(inside.length / depths.length).toFixed(4),
        depth_max_mm: mm(inside.at(-1) ?? 0), depth_p95_mm: mm(quantile(inside, 0.95)),
        nominal_inside: +(nominalInside / depths.length).toFixed(4),
        worst: worst.depth > 0 ? { ...worst, depth_mm: mm(worst.depth) } : null,
        offset_p50_mm: mm(quantile(off, 0.5)), offset_p95_mm: mm(quantile(off, 0.95)), offset_max_mm: mm(off.at(-1) ?? 0),
        swing_max_deg: +swingMax.toFixed(1),
      }
    }
    const r = row
    const fmtRun = (x) => `inside ${(x.inside * 100).toFixed(2)}% (max ${x.depth_max_mm} mm, p95 ${x.depth_p95_mm} mm`
      + `${x.worst ? `, worst ${x.worst.capsule}@t=${x.worst.t}` : ''}), offset p95/max ${x.offset_p95_mm}/${x.offset_max_mm} mm, swing ≤ ${x.swing_max_deg}°`
    console.log(`  ${clip.name.padEnd(22)} off: ${fmtRun(r.off)}`)
    if (r.on) console.log(`  ${''.padEnd(22)} on:  ${fmtRun(r.on)}`)
  }
  if (opts.scan) {
    const ranked = Object.entries(report.clips).sort((a, b) => b[1].off.depth_max_mm - a[1].off.depth_max_mm)
    report.ranked = ranked.map(([k, v]) => [k, v.off.depth_max_mm, v.off.inside])
    console.log('-- ranked by tip depth (off):')
    for (const [k, d, s] of report.ranked.slice(0, 12)) console.log(`  ${k.padEnd(22)} ${d} mm, ${(s * 100).toFixed(2)}% inside`)
  }
  if (opts.json) fs.writeFileSync(opts.json, JSON.stringify(report, null, 1))
}

main().catch((e) => { console.error(e); process.exit(1) })
