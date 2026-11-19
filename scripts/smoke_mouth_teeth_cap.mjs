#!/usr/bin/env node
/**
 * Ruling A211: under a contact opening the rigid tooth rows never move farther than the skin around them, so no tooth
 * ends up outside the face (owner finding 2026-11-19: white tooth pieces above the upper lip, under the nose, while a
 * thick part sat in the open mouth). Numbers by hand (§ B5a).
 *
 * Usage: node scripts/smoke_mouth_teeth_cap.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE: channel O origin, u +z, D 0.08, R 0.02, F 0.03; occupant one segment (0, 0, −0.05) → (0, 0, 0.10), r 0.012
 * → T = r + 2 mm = 0.014, B = max(0.015, 1.5 · max(0.012, 0.02)) = 0.03, b = T + B = 0.044. Bones Head, Jaw at the origin.
 * ONE tooth row on Head (material mouth_teeth): an incisor tip (0, 0.004, 0.01) and its gum edge (0, 0.024, 0.01).
 * The skin above it (Material_0, Head): (0, 0.030, 0.01).
 * [1] rigidRowPush (dir +y, the row's centroid (0, 0.014, 0.01) radially from the axis): the tip needs 0.014 − 0.004
 *     = 0.010; the gum already keeps 0.024 ≥ 0.014 → 0.010.
 * [2] rigidRowCap: the radial map moves a point at d by 0.014 · (1 − d/0.044)², here all along +y:
 *     tip d 0.004 → 0.014 · (40/44)² = 0.0115702; gum d 0.024 → 0.014 · (20/44)² = 0.0028926 → cap 0.0028926.
 *     A point past D + falloff (s 0.2: axial weight 0) is not moved by the skin → cap 0. A point the map moves
 *     AGAINST dir ((0, −0.004, 0.01) with dir +y) → cap 0.
 * [3] the binding: the row moves min(0.010, 0.0028926) = 0.0028926 → tip y 0.0068926, gum y 0.0268926; the skin
 *     vertex moves 0.014 · (1 − 0.030/0.044)² = 0.0014174 → y 0.0314174. The gum stays BELOW the skin over it
 *     (0.0268926 < 0.0314174).
 * [4] pre-fix proof at 2a23beb00 (before A211): the row moved the full 0.010 → gum y 0.034, ABOVE the skin's
 *     0.0314174 — the tooth outside the face.
 */
import { execFileSync } from 'node:child_process'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
const PRE_FIX = '2a23beb00'

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

const ch = { id: 'mouth', o: [0, 0, 0], u: [0, 0, 1], depth: 0.08, r: 0.02, coneDeg: 35, funnel: 0.03, accepts: [],
  minLength: 0, compressMin: 0.6, kinds: null, suppress: new Set() }
const seg = [{ a: [0, 0, -0.05], b: [0, 0, 0.10], r: 0.012 }]
const row = [0, 0.004, 0.01, 0, 0.024, 0.01]

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
const figure = () => {
  const root = new THREE.Group()
  const head = new THREE.Bone(); head.name = 'mixamorig:Head'
  const jaw = new THREE.Bone(); jaw.name = 'mixamorig:Jaw'
  root.add(head, jaw)
  const skin = meshOf([0, 0.030, 0.01], 'Material_0')
  const teeth = meshOf(row, 'mouth_teeth')
  root.add(skin, teeth)
  root.updateMatrixWorld(true)
  const skeleton = new THREE.Skeleton([head, jaw])
  skin.bind(skeleton); teeth.bind(skeleton)
  return { root, skin, teeth }
}
const y = (mesh, i) => mesh.geometry.attributes.position.getY(i)
const run = (lib) => {
  const F = figure()
  const b = lib.bindChannelOpening(THREE, F.root, ch)
  b.apply(ch, seg)
  const out = { tip: y(F.teeth, 0), gum: y(F.teeth, 1), skin: y(F.skin, 0) }
  b.dispose()
  return out
}

// [1]
check('[1] rigidRowPush 0.010', near(SR.rigidRowPush(row, [0, 1, 0], ch, seg), 0.010, 1e-9), SR.rigidRowPush(row, [0, 1, 0], ch, seg))
// [2]
check('[2] rigidRowCap 0.0028926 (the gum bounds it)', near(SR.rigidRowCap(row, [0, 1, 0], ch, seg), 0.0028926, 1e-7),
  SR.rigidRowCap(row, [0, 1, 0], ch, seg))
check('[2] the tip alone: 0.0115702', near(SR.rigidRowCap([0, 0.004, 0.01], [0, 1, 0], ch, seg), 0.0115702, 1e-7),
  SR.rigidRowCap([0, 0.004, 0.01], [0, 1, 0], ch, seg))
check('[2] a point the skin does not move (s 0.2) → 0', SR.rigidRowCap([...row, 0, 0.004, 0.2], [0, 1, 0], ch, seg) === 0)
check('[2] a point moved against dir → 0', SR.rigidRowCap([...row, 0, -0.004, 0.01], [0, 1, 0], ch, seg) === 0)
// [3]
const now = run(SR)
check('[3] tip y 0.0068926, gum y 0.0268926', near(now.tip, 0.0068926, 1e-6) && near(now.gum, 0.0268926, 1e-6), JSON.stringify(now))
check('[3] skin y 0.0314174', near(now.skin, 0.0314174, 1e-6), now.skin)
check('[3] the gum stays below the skin over it', now.gum < now.skin, JSON.stringify(now))
// [4]
let pre = null
const tmp = await mkdtemp(join(ROOT, 'scripts/.smoke-teeth-cap-src-'))
try {
  execFileSync('sh', ['-c', `git -C "${ROOT}" archive ${PRE_FIX} packages/scene-render/src | tar -x -C "${tmp}"`])
  pre = run(await load(join(tmp, 'packages/scene-render/src/index.ts'), 'pre'))
} catch (e) {
  console.log(`SKIP [4] (pre-fix source ${PRE_FIX} not available: ${e.message.split('\n')[0]})`)
} finally {
  await rm(tmp, { recursive: true, force: true })
}
if (pre) {
  check(`[4] at ${PRE_FIX} the gum went to y 0.034, above the skin's 0.0314174`, near(pre.gum, 0.034, 1e-6)
    && near(pre.skin, 0.0314174, 1e-6) && pre.gum > pre.skin, JSON.stringify(pre))
}

console.log(failed ? `FAILED (${failed})` : 'ALL OK')
process.exit(failed ? 1 : 0)
