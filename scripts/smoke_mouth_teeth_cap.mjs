#!/usr/bin/env node
/**
 * Ruling A211: under a contact opening the teeth follow the skin's radial map vertex by vertex, so no tooth ends up
 * outside the face (owner finding 2026-11-19: tooth pieces above the upper lip while a thick part sat in the open
 * mouth) and no tooth vertex stays inside the part — straight, tilted or beside the axis. Numbers by hand (§ B5a).
 *
 * Usage: node scripts/smoke_mouth_teeth_cap.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE: channel O origin, u +z, D 0.08, R 0.02, F 0.03; occupant r 0.012 → T = r + 2 mm = 0.014,
 * B = max(0.015, 1.5 · max(0.012, 0.02)) = 0.03, b = T + B = 0.044; f(d) = d + 0.014 · (1 − d/0.044)² for d < b.
 * Bones Head, Jaw at the origin; every vertex weighted 1.0 to Head; all at s = 0.01 (axial weight 1).
 * Teeth (material mouth_teeth): tip (0, 0.004, 0.01), gum (0, 0.024, 0.01), across the axis (0, −0.002, 0.01).
 * Skin (Material_0): (0, 0.030, 0.01).
 * [1] STRAIGHT, segment (0, 0, −0.05) → (0, 0, 0.10): radially along ±y —
 *     tip d 0.004 → f = 0.004 + 0.014 · (40/44)² = 0.0155702; gum d 0.024 → 0.024 + 0.014 · (20/44)² = 0.0268926;
 *     across d 0.002 → 0.002 + 0.014 · (42/44)² = 0.0147562 → y −0.0147562; skin d 0.030 → 0.030 + 0.014 ·
 *     (14/44)² = 0.0314174. Every tooth vertex ≥ T = 0.014 from the axis (none inside the part); the gum
 *     0.0268926 < the skin 0.0314174 (behind the skin).
 * [2] TILTED 30°, segment through the origin along w = (0, −sin 30°, cos 30°) = (0, −0.5, 0.8660254), ± 0.1 w:
 *     tip: Q = (P · w) w, P · w = −0.002 + 0.0086603 = 0.0066603 → Q (0, −0.0033301, 0.0057679), P − Q
 *     (0, 0.0073301, 0.0042321), d = 0.0084641 → f = 0.0084641 + 0.014 · (1 − 0.0084641/0.044)² = 0.0084641 +
 *     0.014 · 0.8076341² = 0.0175959 → tip Q + (P − Q) · f/d (f/d = 2.0788855) = (0, 0.0119081, 0.0145659), at
 *     0.0175959 ≥ 0.014 from the axis.
 * [3] BESIDE THE AXIS by 15 mm, segment (0.015, 0, −0.05) → (0.015, 0, 0.10): tip P − Q = (−0.015, 0.004, 0),
 *     d = 0.0155242 ≥ T already; f = 0.0155242 + 0.014 · (1 − 0.0155242/0.044)² = 0.0155242 + 0.014 · 0.6471773² =
 *     0.0213880, f/d = 1.3777199 → tip (0.015 − 0.0206658, 0.0055109, 0.01) = (−0.0056658, 0.0055109, 0.01).
 * [4] pre-fix proofs:
 *     - at 2a23beb00 (one rigid translation per row, uncapped) the straight case: the row's dir is +y (its centroid
 *       (0, 0.0086667, 0.01) radially from the axis); the tip needs t 0.010, the across vertex (0, −0.002 + t) needs
 *       t 0.016 → t = 0.016: gum y 0.040, ABOVE the skin's 0.0314174 — outside the face;
 *     - at 1afafe501 (that translation capped by the skin) the across vertex moves against dir → cap 0: the tip stays
 *       at y 0.004, 0.004 < 0.014 from the axis — inside the part.
 */
import { execFileSync } from 'node:child_process'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function load(entry, tag) {
  const dir = await mkdtemp(join(ROOT, `scripts/.smoke-teeth-cap-${tag}-`))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: `export * from '${entry}';`, resolveDir: join(ROOT, 'client3d'), loader: 'ts' },
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

const SR = await load('@anima/scene-render', 'now')
const THREE = await import(join(ROOT, 'node_modules/three/build/three.module.js'))
let failed = 0
const check = (label, ok, got = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${ok ? '' : `  (got ${got})`}`)
  if (!ok) failed++
}
const near = (a, b, eps) => Math.abs(a - b) <= eps
const vnear = (a, b, eps = 1e-6) => a.every((x, i) => near(x, b[i], eps))
const fmt = (v) => `[${v.map((x) => x.toFixed(7)).join(', ')}]`

const ch = { id: 'mouth', o: [0, 0, 0], u: [0, 0, 1], depth: 0.08, r: 0.02, coneDeg: 35, funnel: 0.03, accepts: [],
  minLength: 0, compressMin: 0.6, kinds: null, suppress: new Set() }
const straight = [{ a: [0, 0, -0.05], b: [0, 0, 0.10], r: 0.012 }]
const w = [0, -0.5, 0.8660254]
const tilted = [{ a: w.map((x) => -0.1 * x), b: w.map((x) => 0.1 * x), r: 0.012 }]
const beside = [{ a: [0.015, 0, -0.05], b: [0.015, 0, 0.10], r: 0.012 }]

const meshOf = (positions, material) => {
  const n = positions.length / 3
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(new Array(3 * n).fill(0).map((_, i) => (i % 3 === 2 ? 1 : 0)), 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Array(4 * n).fill(0), 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(new Array(n).fill(0).flatMap(() => [1, 0, 0, 0]), 4))
  const mat = new THREE.MeshBasicMaterial(); mat.name = material
  return new THREE.SkinnedMesh(geo, mat)
}
const run = (lib, segs) => {
  const root = new THREE.Group()
  const head = new THREE.Bone(); head.name = 'mixamorig:Head'
  const jaw = new THREE.Bone(); jaw.name = 'mixamorig:Jaw'
  root.add(head, jaw)
  const skin = meshOf([0, 0.030, 0.01], 'Material_0')
  const teeth = meshOf([0, 0.004, 0.01, 0, 0.024, 0.01, 0, -0.002, 0.01], 'mouth_teeth')
  root.add(skin, teeth)
  root.updateMatrixWorld(true)
  const skeleton = new THREE.Skeleton([head, jaw])
  skin.bind(skeleton); teeth.bind(skeleton)
  const b = lib.bindChannelOpening(THREE, root, ch)
  b.apply(ch, segs)
  const at = (m, i) => [0, 1, 2].map((c) => m.geometry.attributes.position.array[3 * i + c])
  const out = { tip: at(teeth, 0), gum: at(teeth, 1), across: at(teeth, 2), skin: at(skin, 0) }
  b.dispose()
  return out
}
const axisDist = (p, seg) => {
  const ab = seg.b.map((x, i) => x - seg.a[i]), l2 = ab.reduce((s, x) => s + x * x, 0)
  const t = Math.max(0, Math.min(1, p.reduce((s, x, i) => s + (x - seg.a[i]) * ab[i], 0) / l2))
  return Math.hypot(...p.map((x, i) => x - seg.a[i] - ab[i] * t))
}

// [1]
const s1 = run(SR, straight)
check('[1] tip y 0.0155702', vnear(s1.tip, [0, 0.0155702, 0.01]), fmt(s1.tip))
check('[1] gum y 0.0268926', vnear(s1.gum, [0, 0.0268926, 0.01]), fmt(s1.gum))
check('[1] across the axis y −0.0147562', vnear(s1.across, [0, -0.0147562, 0.01]), fmt(s1.across))
check('[1] skin y 0.0314174', vnear(s1.skin, [0, 0.0314174, 0.01]), fmt(s1.skin))
check('[1] no tooth vertex inside T 0.014; the gum behind the skin',
  [s1.tip, s1.gum, s1.across].every((p) => axisDist(p, straight[0]) >= 0.014 - 1e-6) && s1.gum[1] < s1.skin[1])
// [2]
const s2 = run(SR, tilted)
check('[2] tilted 30°: tip (0, 0.0119081, 0.0145659)', vnear(s2.tip, [0, 0.0119081, 0.0145659]), fmt(s2.tip))
check('[2] tilted: tip 0.0175959 from the axis, every tooth vertex ≥ 0.014',
  near(axisDist(s2.tip, tilted[0]), 0.0175959, 1e-6) && [s2.tip, s2.gum, s2.across].every((p) => axisDist(p, tilted[0]) >= 0.014 - 1e-6),
  axisDist(s2.tip, tilted[0]))
// [3]
const s3 = run(SR, beside)
check('[3] 15 mm beside: tip (−0.0056658, 0.0055109, 0.01)', vnear(s3.tip, [-0.0056658, 0.0055109, 0.01]), fmt(s3.tip))
check('[3] beside: every tooth vertex ≥ 0.014 from the axis',
  [s3.tip, s3.gum, s3.across].every((p) => axisDist(p, beside[0]) >= 0.014 - 1e-6))
// [4]
for (const [hash, label, test] of [
  ['2a23beb00', 'uncapped rigid row: gum y 0.040, above the skin 0.0314174',
    (p) => near(p.gum[1], 0.040, 1e-6) && p.gum[1] > p.skin[1]],
  ['1afafe501', 'capped rigid row: cap 0, the tip stays at y 0.004 — inside T 0.014',
    (p) => near(p.tip[1], 0.004, 1e-6) && axisDist(p.tip, straight[0]) < 0.014],
]) {
  const tmp = await mkdtemp(join(ROOT, 'scripts/.smoke-teeth-cap-src-'))
  try {
    execFileSync('sh', ['-c', `git -C "${ROOT}" archive ${hash} packages/scene-render/src | tar -x -C "${tmp}"`])
    const p = run(await load(join(tmp, 'packages/scene-render/src/index.ts'), hash), straight)
    check(`[4] at ${hash} ${label}`, test(p), JSON.stringify(p))
  } catch (e) {
    console.log(`SKIP [4] ${hash} (source not available: ${e.message.split('\n')[0]})`)
  } finally {
    await rm(tmp, { recursive: true, force: true })
  }
}

console.log(failed ? `FAILED (${failed})` : 'ALL OK')
process.exit(failed ? 1 : 0)
