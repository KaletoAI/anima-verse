#!/usr/bin/env node
/**
 * Measurement check for PARTNER CONTACT (cross-person collision, stage 1; spec
 * `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md` Parts 1–3 and 5, plan
 * `docs/superpowers/plans/2026-11-14-cross-person-collision.md` Task 9): how deep one figure's hair and extension
 * chains lie inside ANOTHER figure's capsules while a pair clip plays, with partner contact off and on, how much a
 * tip jitters against a probe sweeping at constant speed, and what the partner contact costs per reader and frame.
 * Numbers, never screenshots.
 *
 * Usage:
 *   node scripts/check_partner_collision.mjs --a A.glb --b B.glb --clip-a HALF_A.fbx --clip-b HALF_B.fbx
 *        --collision-a A.json --collision-b B.json --motion-a A.json --motion-b B.json
 *        [--strands-a RECORD.json]   A's strand record (its GLB must carry `_STRAND_CARD`/`_STRAND_U`,
 *                                    `scripts/hair_strands_export.py`): also run the per-strand hair path
 *        [--idle IDLE.fbx]           the clip the sweep and the budget play (default the library's idle.fbx)
 *        [--sweep 0.5]               the probe's speed, m/s
 *        [--overlap 0.04]            pass sweep: how deep the passing probe reaches into the nearest tip, m
 *        [--span 0.08]               approach sweep: the triangle wave's half span, m (touching at offset 0)
 *        [--frames n]                frames of a pair run (default two loops of the pair clip; the LAST loop — the
 *                                    second half — is measured) and measured frames of a sweep (default 240)
 *        [--every 4]                 measured frames between two hair-vertex samples
 *        [--only pair,sweep,budget]  the sections to run (default all)
 *        [--no-off]                  sweep: skip the contact-off runs (tuning loops)
 *        [--const NAME=VALUE]        override a `partnerContact.ts` constant for this run (repeatable; tuning)
 *        [--channels]                also run CHANNELS: B's payload must carry a declared channel (collision v7)
 *                                    and A an accepted chain (`MotionGroup.op`); see CHANNELS below
 *        [--trace FILE]              write a sha256 per section over every bone `matrixWorld` and `contactTips()`
 *                                    after each secondary update (parity runs between two commits)
 *        [--json FILE]               write every number as JSON
 *   The inputs are READ-ONLY COPIES (plan: never a live world): the GLBs and their served collision payloads, the
 *   motion payloads (`{rev, groups}`), the two halves of one pair clip, the retarget reference from
 *   ANIMATION_RIG_FILE (default shared/models/rig/reference.fbx). Self-bundling via esbuild; no server, no world,
 *   no network.
 *
 * THE POSE is the 3D client's (`scripts/check_extension_collision.mjs`): client3d's `adaptExternalClips`, a three
 * AnimationMixer per figure at 60 fps. A pair half stands at its clip-frame root path (client3d's
 * `extractRootPath` of the RAW clip, `npcs.ts` `tickInteraction`: `anchor + R_y(yaw) · clipRoot(t)`, anchor at the
 * origin, yaw 0); the clip itself plays in place. No height scaling (the stored models' own size).
 *
 * THE FRAME is the client's two-phase frame (`client3d/src/scene/partnerFrame.ts`, `NpcManager.tickSecondary`):
 * phase A poses both figures; phase B snapshots each figure's capsules once (`snapshotPartner`), then each reader
 * steps its strand hair (`StrandHair.setPartners(hairPartnerCapsules(…))`) and its secondary motion
 * (`update(dt, {partners})`) against the OTHER figure's snapshot. Each figure reads the other (the pair's members
 * come first in `selectPartners`, and there are only two). Contact OFF = `partners: []` (today's frame, bit for bit);
 * ON = the snapshot. The GPU hair push re-reads the partner on its final pose (`setGpuPartners`, after phase B).
 *
 * MODES of a figure with hair: `gpu` = the hair chains swing (`MotionGroup.hair`, Swing on) and the hair mesh is
 * pushed by the GPU push, measured through its TypeScript twin (`pushOutOfCapsules` with the entry's own capsules,
 * squeeze, and — contact on — the entry's partner block `GarmentCollisionEntry.partners`, exactly what
 * `createGarmentCollision` writes into the uniforms); `static` = the same without the hair chains
 * (`withoutHairGroups`: the hair rides its joints rigidly, as with Swing off, the default), so off → on is the GPU
 * partner push ALONE; `strand` = the per-strand hair runs (`createStrandHair`, the hair chains taken out, as
 * `Figure.update` does) and the mesh is the strand rebuild.
 *
 * NUMBERS of a pair run, per reader and mode, contact off / on, over the measured frames:
 *  - hair vertex depth: every vertex of the hair mesh (CPU-skinned with its CURRENT skin, then — gpu — pushed),
 *    its depth inside the partner's hair-consumer capsules (`partnerCapsules('hair', …)`, full radius) =
 *    max(r − distance to the axis); `inside` = share deeper than 1 mm, p50/p90/max over those, `mean` over ALL
 *    vertices (the shallow ones count 0) — every `--every` frames;
 *  - tip depth: every link tip with contacts (`contactTips()` of a bind-pose probe: bone + bone-frame tip;
 *    world tip = bone.matrixWorld · tip), against the partner's capsules of ITS consumer (hair chains: `hair`,
 *    extension chains: `extension`), split hair / extension; `pushed` = share of tip-frames a partner capsule
 *    pushed (`contactTips().partner`);
 *  - ms per reader per frame (`performance.now`, field names as `client3d/src/game/perfstats.ts`: `secondaryMs` the
 *    secondary motion's `update`, `strandMs` the strand handle's `update`, `snapshotMs` one `snapshotPartner`).
 *
 * JITTER (the spec's Part 3 measure). One reader plays the idle clip (2 s warm-up without a partner); the probe —
 * the OTHER figure's capsules in their bind pose (`probeCapsules`, `partnerProbe.ts`) — faces it and moves at
 * `--sweep` m/s in two ways:
 *  - PASS: the probe slides sideways (its own x axis) from −0.5 m to +0.5 m past the reader at constant speed, then
 *    starts over; its depth is set (bisection) so that it reaches `--overlap` into the nearest measured tip of the
 *    warm-up pose (half the deepest it can reach where its capsule set never gets that deep);
 *  - APPROACH: the admin probe's sweep along its own facing (`probeSweepOffset` / `probeSweptPose`, a triangle wave
 *    of ±`--span`), its centre set so that it just touches the tips at offset 0.
 * Passes: BEHIND the reader (hair chain tips) and IN FRONT of it (extension tips). Per tip and frame f the delta
 * Δ_f = p_f − p_{f−1}; JITTER = |Δ_f − Δ_{f−1}| (mm), counted while a partner capsule pushed the tip in frames f, f−1
 * and f−2 (`contactTips().partner`) — a tip carried smoothly by a probe at constant speed scores the curvature of
 * its path, a tip flapping in and out scores the size of the flap. `near` = the same over every frame within 10 cm of
 * the probe (contact onset and release included: a tip at rest that the probe starts carrying jumps by its speed,
 * about 4–8 mm a frame, which no constant removes); `flip` = min(|Δ_f|, |Δ_{f−1}|) when Δ reverses (dot < 0), the
 * back-and-forth part. Frames within 3 of a change of the probe's own velocity (approach reversals, the pass's jump
 * back) are left out. `pushed` = share of tip-frames with a partner push; `delta` = |Δ| p95.
 * CHANNELS (`--channels`, plan Task 14). The pair clip as in PAIR (mode gpu, two loops, the last measured), both
 * members of the running pair interaction {pair, pair}. B is the partner: its snapshot carries its declared channels
 * (`bindChannels` on its instance, as `Figure.partnerSnapshot`). Two copies of A play the same frames — one reading B
 * WITH the channels (and passing its interaction), one the same snapshot WITHOUT them; B reads the second (so B never
 * sees the channels' effect). Over the measured frames of the first copy:
 *  - `engaged` = share of frames in which a `contactTips` row names a channel (w > 0), `full` = with w = 1;
 *  - ρ EXCESS = max(0, ρ − R'(s)) of every guided link tip at w = 1 with s ≥ −F (R' from `allowedRadius` with
 *    r_c = the link's own extension capsule radius of A's payload, girth 1): p95 and max, mm;
 *  - PAST THE BOTTOM = max(0, s − (D − r_c)) over the guided tips: the max, mm; `k_min` the smallest depth scale;
 *  - `channelAddedMs` = mean `secondaryMs` of the first copy − of the second (interleaved, alternating order).
 * BUDGET. The reader plays idle with FOUR probes (the other figure's bind capsules in front, behind, left and right,
 * each where it first touches the reader's hair tips, or where it comes closest — bisection as above). Two copies of the reader step the same frames, one with the four
 * partners and one with `[]`; `partnerAddedMs` = mean(with) − mean(without) of `secondaryMs` (and of `strandMs`
 * with the strand hair). A LONE figure: `update(dt)` against `update(dt, {partners: []})` — the added cost must be
 * 0.00. `snapshotMs` = one `snapshotPartner` of the other (real, posed) figure.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const REPO = process.env.PARTNER_CHECK_BUNDLED ? process.cwd() : path.join(__dirname, '..')

function parseArgs(argv) {
  const opts = { sweep: 0.5, span: 0.08, overlap: 0.04, every: 4, only: ['pair', 'sweep', 'budget'], consts: {}, off: true,
    channels: false }
  const take = { '--a': 'a', '--b': 'b', '--clip-a': 'clipA', '--clip-b': 'clipB', '--collision-a': 'collisionA',
    '--collision-b': 'collisionB', '--motion-a': 'motionA', '--motion-b': 'motionB', '--strands-a': 'strandsA',
    '--idle': 'idle', '--json': 'json', '--trace': 'trace' }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (take[a]) opts[take[a]] = argv[++i]
    else if (a === '--sweep') opts.sweep = Number(argv[++i])
    else if (a === '--span') opts.span = Number(argv[++i])
    else if (a === '--overlap') opts.overlap = Number(argv[++i])
    else if (a === '--frames') opts.frames = Math.max(8, Math.round(Number(argv[++i])))
    else if (a === '--every') opts.every = Math.max(1, Math.round(Number(argv[++i])))
    else if (a === '--only') opts.only = argv[++i].split(',').filter(Boolean)
    else if (a === '--no-off') opts.off = false
    else if (a === '--channels') opts.channels = true
    else if (a === '--const') {
      const [k, v] = argv[++i].split('=')
      if (!/^PARTNER_[A-Z_]+$/.test(k) || !Number.isFinite(Number(v))) throw new Error(`bad --const ${k}=${v}`)
      opts.consts[k] = Number(v)
    } else throw new Error(`unknown option ${a}`)
  }
  for (const k of ['a', 'b', 'clipA', 'clipB', 'collisionA', 'collisionB', 'motionA', 'motionB']) {
    if (!opts[k]) throw new Error(`missing ${k} (see Usage)`)
  }
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

/** Strip images/textures from a GLB (node cannot decode them); geometry, skins, nodes, extras untouched. */
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

/** esbuild plugin: `partnerContact.ts`'s `PARTNER_*` constants read an override from `PARTNER_CONST` (JSON) at
 *  module load — the tuning runs of `--const`; without the variable every constant keeps its source value. */
const constPlugin = {
  name: 'partner-const',
  setup(build) {
    build.onLoad({ filter: /partnerContact\.ts$/ }, async (args) => {
      const src = await fs.promises.readFile(args.path, 'utf8')
      const head = 'const __partnerConst = (k: string, v: number): number => { '
        + 'const o = JSON.parse((globalThis as any).process?.env?.PARTNER_CONST || "{}"); '
        + 'return k in o ? Number(o[k]) : v }\n'
      const contents = head + src.replace(/^export const (PARTNER_[A-Z_]+) = ([0-9.e-]+)$/gm,
        (_m, k, v) => `export const ${k} = __partnerConst('${k}', ${v})`)
      return { contents, loader: 'ts' }
    })
  },
}

const quantile = (sorted, q) => (sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))] : 0)
const mm = (m) => +(m * 1000).toFixed(2)
const ms4 = (x) => +x.toFixed(4)

/** Distance from p (x, y, z) to the segment a→b. */
function segDist(x, y, z, a, b) {
  const abx = b[0] - a[0], aby = b[1] - a[1], abz = b[2] - a[2]
  const apx = x - a[0], apy = y - a[1], apz = z - a[2]
  const l2 = abx * abx + aby * aby + abz * abz
  const t = l2 > 1e-12 ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / l2)) : 0
  return Math.hypot(apx - abx * t, apy - aby * t, apz - abz * t)
}
/** Depth of p inside the capsules (max r − d; negative = the gap to the nearest surface). */
function depthIn(x, y, z, caps) {
  let deep = -Infinity
  for (const c of caps) { const e = c.r - segDist(x, y, z, c.a, c.b); if (e > deep) deep = e }
  return deep
}
/** p50 / p90 / max (mm) over the depths > 1 mm, their share, and the mean over all (≤ 0 counts 0). */
function depthStats(depths) {
  const inside = depths.filter((d) => d > 0.001).sort((a, b) => a - b)
  let sum = 0, closest = -Infinity
  for (const d of depths) { if (d > 0) sum += d; if (d > closest) closest = d }
  return { samples: depths.length, closest_mm: mm(closest), inside: +(inside.length / Math.max(1, depths.length)).toFixed(5),
    p50_mm: mm(quantile(inside, 0.5)), p90_mm: mm(quantile(inside, 0.9)), max_mm: mm(inside.at(-1) ?? 0),
    mean_mm: +((sum / Math.max(1, depths.length)) * 1000).toFixed(4) }
}
const msStats = (times) => {
  const sorted = [...times].sort((a, b) => a - b)
  return { mean: ms4(times.reduce((a, b) => a + b, 0) / Math.max(1, times.length)), p95: ms4(quantile(sorted, 0.95)) }
}

async function main() {
  if (!process.env.PARTNER_CHECK_BUNDLED) {
    const opts = parseArgs(process.argv.slice(2))
    const bundlePath = `/tmp/check_partner_collision_bundled.${process.pid}.mjs`
    const esbuild = await import(path.join(REPO, 'node_modules/esbuild/lib/main.js'))
    await esbuild.build({ entryPoints: [__filename], bundle: true, platform: 'node', format: 'esm',
      outfile: bundlePath, logLevel: 'error', plugins: [constPlugin] })
    const args = process.argv.slice(2).map((a) => (/\.(glb|json|fbx)$/.test(a) || a.includes('/') ? path.resolve(a) : a))
    const run = spawnSync('node', ['--max-old-space-size=8192', bundlePath, ...args], { stdio: 'inherit', cwd: REPO,
      env: { ...process.env, PARTNER_CHECK_BUNDLED: '1', PARTNER_CONST: JSON.stringify(opts.consts) } })
    spawnSync('rm', ['-f', bundlePath])
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
  const { adaptExternalClips, extractRootPath, rootPathAt, hairPartnerCapsules } = await import('../client3d/src/scene/figures.ts')
  const { restPoseOf, restCorrections, rigHipsHeight, createSecondaryMotion, bindCollision, withoutHairGroups,
    createGarmentCollision, createStrandHair, pushOutOfCapsules, partnerCapsules, snapshotPartner, probeCapsules,
    probeSweepOffset, probeSweptPose, probeSnapshot } = SR
  // --trace: one running sha256 per section over the bones and contact rows after every secondary update.
  const { createHash } = await import('crypto')
  const traces = {}
  const trace = (section, fig) => {
    if (!opts.trace) return
    const h = traces[section] ??= createHash('sha256')
    fig.inst.traverse((o) => { if (o.isBone) h.update(new Uint8Array(new Float64Array(o.matrixWorld.elements).buffer)) })
    h.update(JSON.stringify(fig.sm.contactTips()))
  }
  const constants = Object.fromEntries(['PARTNER_MAX', 'PARTNER_COLLIDE_MAX', 'PARTNER_PUSH_MAX_M', 'PARTNER_HYST_M',
    'PARTNER_RELEASE_DEG_S', 'PARTNER_PREFILTER_SLACK_M'].map((k) => [k, SR[k]]))
  const FPS = 60, DT = 1 / FPS

  const read = (f) => fs.readFileSync(f)
  const arrayBufferOf = (buf) => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)
  const loadFbx = (file) => new FBXLoader().parse(arrayBufferOf(read(file)), '')
  const rigFile = process.env.ANIMATION_RIG_FILE || path.join(REPO, 'shared/models/rig/reference.fbx')
  const idleFile = opts.idle || path.join(process.env.ANIMATION_CLIPS_DIR || path.join(REPO, 'shared/models/clips'), 'idle.fbx')
  const rig = loadFbx(rigFile)
  const donorRest = restPoseOf(THREE, rig)
  const donorHipsY = rigHipsHeight(THREE, rig)
  const rawClip = (file, name) => { const c = loadFbx(file).animations[0].clone(); c.name = name; return c }

  async function loadSide(name, glb, collisionFile, motionFile, clipFile, strandsFile) {
    const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).parseAsync(arrayBufferOf(stripGlbImages(read(glb))), '')
    const template = gltf.scene
    const s0 = new THREE.Box3().setFromObject(template).getSize(new THREE.Vector3())
    if (s0.z > s0.y * 1.5) template.rotation.x = -Math.PI / 2
    template.updateMatrixWorld(true)
    const pair = rawClip(clipFile, `pair_${name}`)
    const idle = rawClip(idleFile, 'idle')
    const [pairClip, idleClip] = adaptExternalClips([pair.clone(), idle.clone()], template,
      restCorrections(THREE, donorRest, template), donorHipsY)
    const motion = JSON.parse(read(motionFile))
    const hairBones = new Set(Object.values(motion.groups ?? {}).filter((g) => g.hair).flatMap((g) => g.bones))
    return { name, template, collision: JSON.parse(read(collisionFile)).collision ?? JSON.parse(read(collisionFile)),
      motion, hairBones, pairClip, idleClip, rootPath: extractRootPath(pair),
      strandRecord: strandsFile ? JSON.parse(read(strandsFile)) : null, files: { glb, collisionFile, motionFile, clipFile } }
  }
  const A = await loadSide('A', opts.a, opts.collisionA, opts.motionA, opts.clipA, opts.strandsA)
  const B = await loadSide('B', opts.b, opts.collisionB, opts.motionB, opts.clipB, null)
  const other = (side) => (side === A ? B : A)

  /** One figure: its root (the client's `Figure.root`), the instance, secondary motion, binding, hair. */
  function makeFigure(side, mode, clip) {
    const holder = new THREE.Group()
    const inst = SkeletonUtils.clone(side.template)
    holder.add(inst)
    holder.updateMatrixWorld(true)
    const strandMode = mode === 'strand' && !!side.strandRecord
    const motion = strandMode || mode === 'static' ? withoutHairGroups(side.motion) : side.motion
    const sm = createSecondaryMotion(THREE, inst, motion, side.template)
    sm.setCollision(side.collision)
    const binding = bindCollision(THREE, inst, side.collision)
    if (!binding) throw new Error(`${side.name}: the collision payload does not bind (version ${side.collision?.version})`)
    let gc = null, strand = null, hairMesh = null, hairEntry = null
    if (strandMode) {
      strand = createStrandHair(THREE, inst, side.strandRecord)
      if (!strand) throw new Error(`${side.name}: createStrandHair refused the model + record`)
      strand.setEnabled(true)
      hairMesh = strand.mesh
    } else {
      gc = createGarmentCollision(THREE, inst, side.collision)
      hairEntry = gc?.entries.find((e) => e.kind === 'hair') ?? null
      hairMesh = hairEntry?.mesh ?? null
    }
    const mixer = new THREE.AnimationMixer(inst)
    const action = clip ? mixer.clipAction(clip) : null
    action?.play()
    return { side, mode: strandMode ? 'strand' : mode, holder, inst, sm, binding, gc, strand, hairMesh, hairEntry,
      mixer, action, bones: boneMap(inst) }
  }
  function boneMap(root) {
    const m = new Map()
    root.traverse((o) => { if (o.isBone && !m.has(o.name)) m.set(o.name, o) })
    return m
  }
  /** The tips the check measures: `contactTips()` of a bind-pose figure (bone + bone-frame tip), split hair / ext. */
  function tipsOf(side, mode) {
    const fig = makeFigure(side, mode, null)
    const rows = fig.sm.contactTips()
    fig.sm.dispose(); fig.strand?.dispose(); fig.gc?.dispose()
    return rows.map((r) => ({ bone: r.bone, tipLocal: new THREE.Vector3(...r.tipLocal), hair: side.hairBones.has(r.bone) }))
  }
  const snapCopy = (binding) => binding.capsules.map((c) => ({ id: c.capsule.id, region: c.capsule.region, now: c.now }))
  const consumerNows = (consumer, caps) => partnerCapsules(consumer, caps.map((capsule) => ({ capsule }))).map((e) => e.capsule.now)

  /** Phase A of one figure at 60 fps: the mixer, the pair root path (pair runs), the world matrices. */
  function phaseA(fig, pair) {
    fig.mixer.update(DT)
    if (pair) {
      const t = fig.action.time
      const r = rootPathAt(fig.side.rootPath, t)
      fig.holder.position.set(r.x, 0, r.z)
    }
    fig.holder.updateMatrixWorld(true)
  }

  // ---- CPU skinning of the hair mesh with its CURRENT geometry (the strand rebuild re-skins cards to the head)
  const skinHair = (mesh, out) => {
    const g = mesh.geometry
    const pos = g.getAttribute('position'), si = g.getAttribute('skinIndex'), sw = g.getAttribute('skinWeight')
    const n = pos.count
    const mats = mesh.skeleton.bones.map((b, i) => new THREE.Matrix4().multiplyMatrices(mesh.matrixWorld, mesh.bindMatrixInverse)
      .multiply(b.matrixWorld).multiply(mesh.skeleton.boneInverses[i]).multiply(mesh.bindMatrix).elements)
    for (let i = 0; i < n; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i)
      let ox = 0, oy = 0, oz = 0
      for (let j = 0; j < 4; j++) {
        const w = sw.getComponent(i, j)
        if (!w) continue
        const e = mats[si.getComponent(i, j)]
        ox += w * (e[0] * x + e[4] * y + e[8] * z + e[12])
        oy += w * (e[1] * x + e[5] * y + e[9] * z + e[13])
        oz += w * (e[2] * x + e[6] * y + e[10] * z + e[14])
      }
      out[i * 3] = ox; out[i * 3 + 1] = oy; out[i * 3 + 2] = oz
    }
    return n
  }
  /** The GPU push of the hair entry on the CPU (its twin), in the mesh's local space, world in and out. */
  const gpuTwin = (fig, world, n) => {
    fig.gc.update()
    const { mesh, local, partners } = fig.hairEntry
    const g = mesh.geometry, pos = g.getAttribute('position'), w = g.getAttribute('_collide')
    const inv = new THREE.Matrix4().copy(mesh.matrixWorld).invert()
    const v = new THREE.Vector3()
    for (let i = 0; i < n; i++) {
      v.set(world[i * 3], world[i * 3 + 1], world[i * 3 + 2]).applyMatrix4(inv)
      const q = pushOutOfCapsules([v.x, v.y, v.z], local, w ? w.getX(i) : 1, [pos.getX(i), pos.getY(i), pos.getZ(i)],
        { squeeze: true, partners })
      v.set(q[0], q[1], q[2]).applyMatrix4(mesh.matrixWorld)
      world[i * 3] = v.x; world[i * 3 + 1] = v.y; world[i * 3 + 2] = v.z
    }
  }

  const report = { constants, inputs: { a: A.files, b: B.files, strands_a: opts.strandsA ?? null, idle: idleFile,
    rig: rigFile }, fps: FPS }
  console.log(`== partner contact check — constants ${JSON.stringify(constants)}`)

  // ================================================================ PAIR
  if (opts.only.includes('pair')) {
    const loop = Math.max(A.pairClip.duration, B.pairClip.duration)
    const total = opts.frames ?? 2 * Math.round(loop * FPS)
    const measureFrom = Math.floor(total / 2)
    const modes = ['gpu', 'static', ...(A.strandRecord ? ['strand'] : [])]
    report.pair = { clip_s: +loop.toFixed(3), frames: total, measured_from: measureFrom, every: opts.every, runs: {} }
    for (const mode of modes) {
      const tips = { A: tipsOf(A, mode), B: tipsOf(B, mode) }
      for (const contact of [false, true]) {
        const figs = [makeFigure(A, mode, A.pairClip), makeFigure(B, mode, B.pairClip)]
        const acc = figs.map(() => ({ hairV: [], tipHair: [], tipExt: [], pushed: 0, tipFrames: 0,
          secondaryMs: [], strandMs: [], snapshotMs: [] }))
        const world = new Float32Array(Math.max(...figs.map((f) => f.hairMesh ? f.hairMesh.geometry.getAttribute('position').count : 0)) * 3)
        for (let f = 0; f < total; f++) {
          for (const fig of figs) phaseA(fig, true)
          const snaps = figs.map((fig, k) => {
            const t0 = performance.now()
            const s = snapshotPartner(fig.side.name, fig.binding, { id: 'pair', kind: 'pair' })
            acc[k].snapshotMs.push(performance.now() - t0)
            return s
          })
          figs.forEach((fig, k) => {
            const partners = contact ? [snaps[1 - k]] : []
            if (fig.strand) {
              fig.strand.setPartners(contact ? hairPartnerCapsules(partners) : null)
              fig.holder.updateMatrixWorld(true)
              const t0 = performance.now()
              fig.strand.update(DT)
              acc[k].strandMs.push(performance.now() - t0)
            }
            const t0 = performance.now()
            fig.sm.update(DT, { partners })
            acc[k].secondaryMs.push(performance.now() - t0)
            trace(`pair:${mode}:${contact ? 'on' : 'off'}`, fig)
          })
          if (f < measureFrom) continue
          // The final capsules (after phase B) — what the GPU push re-reads and what is seen.
          const finals = figs.map((fig) => { fig.binding.update(); return snapCopy(fig.binding) })
          figs.forEach((fig, k) => {
            const them = finals[1 - k]
            const hairCaps = consumerNows('hair', them), extCaps = consumerNows('extension', them)
            const pushedBones = new Set(fig.sm.contactTips().filter((r) => r.partner.length).map((r) => r.bone))
            const tip = new THREE.Vector3()
            for (const t of tips[fig.side.name]) {
              const bone = fig.bones.get(t.bone)
              if (!bone) continue
              tip.copy(t.tipLocal).applyMatrix4(bone.matrixWorld)
              const d = depthIn(tip.x, tip.y, tip.z, t.hair ? hairCaps : extCaps)
              ;(t.hair ? acc[k].tipHair : acc[k].tipExt).push(d)
              acc[k].tipFrames++
              if (pushedBones.has(t.bone)) acc[k].pushed++
            }
            if (fig.hairMesh && (f - measureFrom) % opts.every === 0) {
              const n = skinHair(fig.hairMesh, world)
              if (fig.gc) {
                fig.gc.setPartners(contact ? hairCaps : null)
                gpuTwin(fig, world, n)
              }
              for (let i = 0; i < n; i++) acc[k].hairV.push(depthIn(world[i * 3], world[i * 3 + 1], world[i * 3 + 2], hairCaps))
            }
          })
        }
        figs.forEach((fig, k) => {
          const a = acc[k]
          const key = `${fig.side.name}/${mode}`
          const row = report.pair.runs[key] ??= {}
          row[contact ? 'on' : 'off'] = {
            hair_vertices: fig.hairMesh ? depthStats(a.hairV) : null,
            tip_hair: a.tipHair.length ? depthStats(a.tipHair) : null,
            tip_ext: a.tipExt.length ? depthStats(a.tipExt) : null,
            pushed: +(a.pushed / Math.max(1, a.tipFrames)).toFixed(4),
            secondaryMs: msStats(a.secondaryMs.slice(measureFrom)),
            strandMs: a.strandMs.length ? msStats(a.strandMs.slice(measureFrom)) : null,
            snapshotMs: msStats(a.snapshotMs.slice(measureFrom)),
          }
          fig.sm.dispose(); fig.strand?.dispose(); fig.gc?.dispose()
        })
      }
    }
    console.log(`-- pair clip (${report.pair.clip_s} s, frames ${total}, measured from ${measureFrom}; depth inside the PARTNER, mm)`)
    const fmt = (s) => (s ? `closest ${s.closest_mm} in ${(s.inside * 100).toFixed(2)}% p50 ${s.p50_mm} p90 ${s.p90_mm} max ${s.max_mm} mean ${s.mean_mm}` : '—')
    for (const [key, row] of Object.entries(report.pair.runs)) {
      for (const k of ['off', 'on']) {
        const r = row[k]
        console.log(`  ${key.padEnd(9)} ${k.padEnd(3)} hair vertices: ${fmt(r.hair_vertices)}`)
        console.log(`  ${''.padEnd(13)} hair tips: ${fmt(r.tip_hair)} | ext tips: ${fmt(r.tip_ext)} | pushed ${(r.pushed * 100).toFixed(1)}%`)
        console.log(`  ${''.padEnd(13)} secondaryMs ${r.secondaryMs.mean}/${r.secondaryMs.p95}`
          + `${r.strandMs ? ` strandMs ${r.strandMs.mean}/${r.strandMs.p95}` : ''} snapshotMs ${r.snapshotMs.mean}`)
      }
    }
  }

  // ---- probes: the other figure's capsules in their bind pose, placed to just touch the reader's tips
  const probeSource = (side) => {
    const fig = makeFigure(side, 'gpu', null)
    fig.binding.update()
    const src = fig.binding.capsules.map((c) => ({ id: c.capsule.id, region: c.capsule.region, a: [...c.now.a], b: [...c.now.b], r: c.now.r }))
    fig.sm.dispose(); fig.gc?.dispose()
    return src
  }
  /** The probe's position along an axis (`place(s)`, s from 1.5 m towards −0.6 m: approaching the reader) where its
   *  consumer capsules first reach `overlap` into the nearest of `pts` — a 1 cm scan from the far side, refined by
   *  bisection. When the scan never gets that deep (a gap in the probe's set), half the deepest it gets is used.
   *  `{s, overlap}`, or null when it never touches. */
  const touchAt = (src, pts, consumer, place, overlap = 0, closest = false) => {
    const deepest = (s) => {
      const caps = consumerNows(consumer, probeCapsules(src, place(s), false))
      let d = -Infinity
      for (const p of pts) d = Math.max(d, depthIn(p.x, p.y, p.z, caps))
      return d
    }
    let most = -Infinity, mostAt = 0
    for (let s = 1.5; s >= -0.6; s -= 0.01) { const d = deepest(s); if (d > most) { most = d; mostAt = s } }
    if (most <= 0) return closest ? { s: mostAt, overlap: most } : null
    const want = Math.min(overlap, most / 2)
    let lo = 1.5, hi = null
    for (let s = 1.5; s >= -0.6; s -= 0.01) { if (deepest(s) >= want) { hi = s; break } lo = s }
    for (let i = 0; i < 40; i++) { const mid = (lo + hi) / 2; if (deepest(mid) >= want) hi = mid; else lo = mid }
    return { s: hi, overlap: want }
  }
  const PLACES = {
    back: (s) => ({ x: 0, z: -s, yaw: 0 }),
    front: (s) => ({ x: 0, z: s, yaw: 180 }),
    left: (s) => ({ x: s, z: 0, yaw: -90 }),
    right: (s) => ({ x: -s, z: 0, yaw: 90 }),
  }
  const WARM = 2 * FPS

  // ================================================================ SWEEP (jitter)
  if (opts.only.includes('sweep')) {
    const measured = opts.frames ?? 240
    report.sweep = { speed_m_s: opts.sweep, overlap_m: opts.overlap, span_m: opts.span, warmup: WARM, frames: measured, passes: {} }
    const passes = [[A, 'back', true], [A, 'front', false], [B, 'front', false]]
    const L = 0.5
    for (const kind of ['pass', 'approach']) {
      for (const [side, dir, hair] of passes) {
        const tips = tipsOf(side, 'gpu').filter((t) => t.hair === hair)
        if (!tips.length) continue
        const consumer = hair ? 'hair' : 'extension'
        const src = probeSource(other(side))
        // the warm-up pose's tips (no partner) decide where the probe stands
        const warm = makeFigure(side, 'gpu', side.idleClip)
        for (let f = 0; f < WARM; f++) { phaseA(warm, false); warm.sm.update(DT, { partners: [] }) }
        const pts = tips.map((t) => t.tipLocal.clone().applyMatrix4(warm.bones.get(t.bone).matrixWorld))
        warm.sm.dispose(); warm.gc?.dispose()
        const touch = touchAt(src, pts, consumer, PLACES[dir], kind === 'pass' ? opts.overlap : 0)
        const key = `${kind}:${side.name}/${dir}`
        if (touch === null) { console.log(`  ${key}: the probe never touches — skipped`); continue }
        const centre = PLACES[dir](touch.s)
        // pass: the probe slides sideways (its own +x turned by the yaw) from −L to +L at constant speed, then starts
        // over (the jump back happens 0.5 m away); approach: the admin sweep along its facing (triangle wave).
        const lateral = [Math.cos(centre.yaw * Math.PI / 180), -Math.sin(centre.yaw * Math.PI / 180)]
        const poseAt = (t) => {
          if (kind === 'approach') return { offset: probeSweepOffset(t, opts.sweep, opts.span), pose: probeSweptPose(centre, probeSweepOffset(t, opts.sweep, opts.span)) }
          const x = -L + ((opts.sweep * t) % (2 * L))
          return { offset: x, pose: { x: centre.x + x * lateral[0], z: centre.z + x * lateral[1], yaw: centre.yaw } }
        }
        const row = report.sweep.passes[key] = { consumer, tips: tips.length, overlap_m: +touch.overlap.toFixed(4),
          centre: { x: +centre.x.toFixed(4), z: +centre.z.toFixed(4), yaw: centre.yaw } }
        for (const contact of (opts.off ? [false, true] : [true])) {
          const fig = makeFigure(side, 'gpu', side.idleClip)
          for (let f = 0; f < WARM; f++) { phaseA(fig, false); fig.sm.update(DT, { partners: [] }) }
          const track = tips.map(() => [])
          const near = tips.map(() => [])
          const held = tips.map(() => [])
          const offsets = []
          let pushedFrames = 0
          for (let f = 0; f < measured; f++) {
            phaseA(fig, false)
            const { offset, pose } = poseAt(f * DT)
            offsets.push(offset)
            const caps = probeCapsules(src, pose, false)
            fig.sm.update(DT, { partners: contact ? [probeSnapshot(caps)] : [] })
            trace(`sweep:${key}:${contact ? 'on' : 'off'}`, fig)
            const nows = consumerNows(consumer, caps)
            const pushed = new Set(fig.sm.contactTips().filter((r) => r.partner.length).map((r) => r.bone))
            tips.forEach((t, i) => {
              const p = t.tipLocal.clone().applyMatrix4(fig.bones.get(t.bone).matrixWorld)
              track[i].push(p)
              near[i].push(depthIn(p.x, p.y, p.z, nows) > -0.10)
              held[i].push(pushed.has(t.bone))
              if (pushed.has(t.bone)) pushedFrames++
            })
          }
          fig.sm.dispose(); fig.gc?.dispose()
          // a change of the probe's own velocity (approach: its reversals; pass: the jump back) — ±3 frames left out
          const turn = offsets.map((o, f) => f >= 2 && Math.abs((o - offsets[f - 1]) - (offsets[f - 1] - offsets[f - 2])) > 1e-6)
          const steady = offsets.map((_, f) => { for (let g = f - 3; g <= f + 3; g++) if (turn[g]) return false; return true })
          const jitter = [], nearJ = [], flip = [], delta = []
          tips.forEach((_, i) => {
            const p = track[i]
            for (let f = 2; f < measured; f++) {
              if (!steady[f] || !near[i][f] || !near[i][f - 1] || !near[i][f - 2]) continue
              const d1 = p[f].clone().sub(p[f - 1]), d0 = p[f - 1].clone().sub(p[f - 2])
              const j = d1.clone().sub(d0).length()
              nearJ.push(j)
              flip.push(d1.dot(d0) < 0 ? Math.min(d1.length(), d0.length()) : 0)
              delta.push(d1.length())
              // in contact: pushed by the probe in all three frames (contact = the off run's would-be pushes: none)
              if (held[i][f] && held[i][f - 1] && held[i][f - 2]) jitter.push(j)
            }
          })
          for (const x of [jitter, nearJ, flip, delta]) x.sort((a, b) => a - b)
          row[contact ? 'on' : 'off'] = { samples: jitter.length, jitter_p95_mm: mm(quantile(jitter, 0.95)),
            jitter_max_mm: mm(jitter.at(-1) ?? 0), near_samples: nearJ.length, near_p95_mm: mm(quantile(nearJ, 0.95)),
            near_max_mm: mm(nearJ.at(-1) ?? 0), flip_p95_mm: mm(quantile(flip, 0.95)), flip_max_mm: mm(flip.at(-1) ?? 0),
            delta_p95_mm: mm(quantile(delta, 0.95)), pushed: +(pushedFrames / Math.max(1, measured * tips.length)).toFixed(4) }
        }
      }
    }
    console.log(`-- sweep at ${opts.sweep} m/s (pass: overlap ${opts.overlap} m; approach: ±${opts.span} m) — jitter = |Δ_f − Δ_(f−1)| of a tip, mm`)
    for (const [key, r] of Object.entries(report.sweep.passes)) {
      for (const k of ['off', 'on']) {
        if (!r[k]) continue
        console.log(`  ${key.padEnd(17)} ${k.padEnd(3)} jitter p95 ${r[k].jitter_p95_mm} max ${r[k].jitter_max_mm} (${r[k].samples})`
          + ` | near p95 ${r[k].near_p95_mm} max ${r[k].near_max_mm} | flip p95 ${r[k].flip_p95_mm} max ${r[k].flip_max_mm} | delta p95 ${r[k].delta_p95_mm}`
          + ` | pushed ${(r[k].pushed * 100).toFixed(1)}% (${r[k].samples} samples, ${r.tips} tips)`)
      }
    }
  }

  // ================================================================ CHANNELS
  if (opts.channels) {
    const { bindChannels, channelCoords, allowedRadius } = SR
    const loop = Math.max(A.pairClip.duration, B.pairClip.duration)
    const total = opts.frames ?? 2 * Math.round(loop * FPS)
    const measureFrom = Math.floor(total / 2)
    const guided = makeFigure(A, 'gpu', A.pairClip), plain = makeFigure(A, 'gpu', A.pairClip)
    const partner = makeFigure(B, 'gpu', B.pairClip)
    const bound = bindChannels(THREE, partner.inst, B.collision)
    if (!bound) throw new Error(`B: no declared channel binds (payload version ${B.collision?.version}, `
      + `${B.collision?.channels?.length ?? 0} channels)`)
    const ops = Object.values(A.motion.groups ?? {}).map((g) => g.op).filter(Boolean)
    // r_c per link: its own extension capsule (start joint = the link), as the solver reads it.
    const linkR = new Map()
    for (const c of A.collision.capsules ?? []) {
      const key = SR.normBoneName(c.a)
      if (['chest', 'attached_part', 'appendage'].includes(c.region) && !linkR.has(key)) linkR.set(key, c.r)
    }
    const pair = { id: 'pair', kind: 'pair' }
    const acc = { engaged: 0, full: 0, frames: 0, excess: [], past: 0, kMin: 1, rows: 0, with: [], without: [] }
    for (let f = 0; f < total; f++) {
      for (const fig of [guided, plain, partner]) phaseA(fig, true)
      const snapB = snapshotPartner('B', partner.binding, pair)
      bound.update()
      const snapBCh = { ...snapB, channels: [...bound.channels] }
      const snapA = snapshotPartner('A', plain.binding, pair)
      const rec = f >= measureFrom
      for (const o of f % 2 ? [0, 1] : [1, 0]) {
        const t0 = performance.now()
        if (o) guided.sm.update(DT, { partners: [snapBCh], interaction: pair })
        else plain.sm.update(DT, { partners: [snapB], interaction: pair })
        if (rec) (o ? acc.with : acc.without).push(performance.now() - t0)
      }
      partner.sm.update(DT, { partners: [snapA] })
      if (!rec) continue
      acc.frames++
      const rows = guided.sm.contactTips().filter((r) => r.channel)
      if (rows.length) acc.engaged++
      if (rows.some((r) => r.channel.w === 1)) acc.full++
      for (const r of rows) {
        acc.rows++
        const ch = snapBCh.channels.find((c) => c.id === r.channel.id)
        if (!ch) continue
        const rc = linkR.get(SR.normBoneName(r.bone)) ?? 0
        const { s, rho } = channelCoords(r.tip, ch)
        if (r.channel.w === 1 && s >= -ch.funnel) acc.excess.push(Math.max(0, rho - allowedRadius(s, ch, rc)))
        acc.past = Math.max(acc.past, s - (ch.depth - rc))
        acc.kMin = Math.min(acc.kMin, r.channel.k)
      }
    }
    for (const fig of [guided, plain, partner]) { fig.sm.dispose(); fig.gc?.dispose() }
    acc.excess.sort((a, b) => a - b)
    const row = report.channels = {
      frames: acc.frames, channels: bound.channels.map((c) => c.id), accepted_ops: ops,
      engaged: +(acc.engaged / Math.max(1, acc.frames)).toFixed(4), full: +(acc.full / Math.max(1, acc.frames)).toFixed(4),
      guided_tips: acc.excess.length, rho_excess_p95_mm: mm(quantile(acc.excess, 0.95)), rho_excess_max_mm: mm(acc.excess.at(-1) ?? 0),
      past_bottom_max_mm: mm(Math.max(0, acc.rows ? acc.past : 0)), k_min: +acc.kMin.toFixed(4),
      secondaryMs: { with: msStats(acc.with), without: msStats(acc.without) },
      channelAddedMs: ms4(msStats(acc.with).mean - msStats(acc.without).mean),
    }
    console.log(`-- channels ${row.channels.join(', ')} (A ops ${ops.join(', ') || '—'}; ${row.frames} frames): engaged`
      + ` ${(row.engaged * 100).toFixed(1)}% (w = 1 ${(row.full * 100).toFixed(1)}%) | ρ excess p95 ${row.rho_excess_p95_mm}`
      + ` max ${row.rho_excess_max_mm} mm (${row.guided_tips} tips) | past the bottom max ${row.past_bottom_max_mm} mm,`
      + ` k min ${row.k_min} | secondaryMs ${row.secondaryMs.with.mean} vs ${row.secondaryMs.without.mean}`
      + ` → channelAddedMs ${row.channelAddedMs}`)
  }

  // ================================================================ BUDGET
  if (opts.only.includes('budget')) {
    const N = 600
    report.budget = { frames: N, readers: {} }
    for (const side of [A, B]) {
      for (const mode of side.strandRecord ? ['gpu', 'strand'] : ['gpu']) {
        const tips = tipsOf(side, mode)
        const src = probeSource(other(side))
        const warm = makeFigure(side, mode, side.idleClip)
        for (let f = 0; f < WARM; f++) { phaseA(warm, false); warm.sm.update(DT, { partners: [] }) }
        const pts = tips.map((t) => t.tipLocal.clone().applyMatrix4(warm.bones.get(t.bone).matrixWorld))
        if (warm.hairMesh) {   // the hair mesh counts too (the GPU push and the strand read the same partners)
          const world = new Float32Array(warm.hairMesh.geometry.getAttribute('position').count * 3)
          const n = skinHair(warm.hairMesh, world)
          for (let i = 0; i < n; i += 50) pts.push(new THREE.Vector3(world[i * 3], world[i * 3 + 1], world[i * 3 + 2]))
        }
        warm.sm.dispose(); warm.strand?.dispose(); warm.gc?.dispose()
        const probes = Object.entries(PLACES).map(([dir, place]) => {
          const touch = touchAt(src, pts, 'hair', place, 0, true)
          return touch === null ? null : probeSnapshot(probeCapsules(src, place(touch.s), false)).capsules
        }).filter(Boolean).map((caps, i) => ({ name: `probe${i}`, capsules: caps, channels: [], interaction: null }))
        // the other figure, posed, for the snapshot cost
        const partnerFig = makeFigure(other(side), 'gpu', other(side).idleClip)
        const withP = makeFigure(side, mode, side.idleClip), without = makeFigure(side, mode, side.idleClip)
        const lone = makeFigure(side, mode, side.idleClip)
        const t = { with: [], without: [], strandWith: [], strandWithout: [], lonePlain: [], loneEmpty: [], snapshot: [] }
        const step = (fig, partners, bucket, strandBucket, plain = false) => {
          phaseA(fig, false)
          if (fig.strand) {
            fig.strand.setPartners(partners.length ? hairPartnerCapsules(partners) : null)
            const t0 = performance.now(); fig.strand.update(DT); strandBucket?.push(performance.now() - t0)
          }
          const t0 = performance.now()
          if (plain) fig.sm.update(DT); else fig.sm.update(DT, { partners })
          bucket?.push(performance.now() - t0)
        }
        for (let f = 0; f < WARM + N; f++) {
          const rec = f >= WARM
          phaseA(partnerFig, false)
          const t0 = performance.now()
          snapshotPartner('B', partnerFig.binding, null)
          if (rec) t.snapshot.push(performance.now() - t0)
          partnerFig.sm.update(DT, { partners: [] })
          const order = f % 2 ? [0, 1] : [1, 0]
          for (const o of order) {
            if (o) step(withP, probes, rec ? t.with : null, rec ? t.strandWith : null)
            else step(without, [], rec ? t.without : null, rec ? t.strandWithout : null)
          }
          if (f % 2) { step(lone, [], rec ? t.lonePlain : null, null, true); }
          else step(lone, [], rec ? t.loneEmpty : null, null)
        }
        const st = (x) => msStats(x)
        const row = report.budget.readers[`${side.name}/${mode}`] = {
          partners: probes.length,
          secondaryMs: { with: st(t.with), without: st(t.without) },
          partnerAddedMs: ms4(st(t.with).mean - st(t.without).mean),
          strandMs: t.strandWith.length ? { with: st(t.strandWith), without: st(t.strandWithout) } : null,
          strandPartnerAddedMs: t.strandWith.length ? ms4(st(t.strandWith).mean - st(t.strandWithout).mean) : null,
          lone: { plain: st(t.lonePlain), empty: st(t.loneEmpty), addedMs: ms4(st(t.loneEmpty).mean - st(t.lonePlain).mean) },
          snapshotMs: st(t.snapshot),
        }
        for (const fig of [partnerFig, withP, without, lone]) { fig.sm.dispose(); fig.strand?.dispose(); fig.gc?.dispose() }
        console.log(`-- budget ${side.name}/${mode}: ${row.partners} partners — secondaryMs ${row.secondaryMs.with.mean} vs`
          + ` ${row.secondaryMs.without.mean} → partnerAddedMs ${row.partnerAddedMs}`
          + `${row.strandMs ? ` | strandMs ${row.strandMs.with.mean} vs ${row.strandMs.without.mean} → ${row.strandPartnerAddedMs}` : ''}`
          + ` | lone: ${row.lone.plain.mean} vs [] ${row.lone.empty.mean} → ${row.lone.addedMs} | snapshotMs ${row.snapshotMs.mean}`)
      }
    }
  }
  if (opts.trace) {
    const digests = Object.fromEntries(Object.entries(traces).map(([k, h]) => [k, h.digest('hex')]))
    fs.writeFileSync(opts.trace, JSON.stringify(digests, null, 1))
    console.log(`-- trace: ${Object.keys(digests).length} sections → ${opts.trace}`)
  }
  if (opts.json) fs.writeFileSync(opts.json, JSON.stringify(report, null, 1))
}

main().catch((e) => { console.error(e); process.exit(1) })
