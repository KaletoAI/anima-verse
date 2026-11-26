#!/usr/bin/env node
/**
 * Smoke check: a figure's textures are filtered anisotropically in every viewer (`prepareFigureTextures`).
 *
 * Usage: node scripts/smoke_figure_anisotropy.mjs
 *
 * WHY (measured 2026-11-20 on an assembled figure with template gloves and a template bra): the template dialog's
 * picture (Blender Workbench, factory anisotropic filter 2x, 8 AA samples, 590 px/m) showed the pieces sharper than
 * the 3D preview (three.js; GLTFLoader leaves Texture.anisotropy = 1). The image, the UVs and the delivery copy are
 * byte-identical in both. The difference is the filter: a fitted template piece is UV-mapped by its bounding box
 * (`garment_template_fitted`: u = x over the box width x 0.47, v = z over the box height x 0.96, scaled independently),
 * so its texel rate depends on the direction. Gloves in T-pose: box ~1.62 m wide, ~0.12 m high ->
 * 1024 x 0.47 / 1.62 = 297 texels/m along the arm, 1024 x 0.96 / 0.12 = 8192 across (measured medians 291 / 5197).
 *
 * HAND-DERIVED LOD (EXT_texture_filter_anisotropic: N = min(ceil(Pmax / Pmin), maxAniso), lambda = log2(Pmax / N);
 * the sampled mip divides BOTH axes by 2^lambda). The gloves seen at 300 screen px/m: Pmax = 5197 / 300 = 17.32,
 * Pmin = 291 / 300 = 0.97 (< 1: magnified, ratio 17.9 -> ceil 18):
 *   anisotropy 1:  N = 1,  lambda = log2(17.32) = 4.11 -> along the arm 291 / 17.32 = 16.8 texels/m
 *   anisotropy 16: N = 16, lambda = log2(17.32 / 16) = 0.11 -> along the arm 291 / 1.08 = 268.8 texels/m
 * (the dialog's Blender picture: N = 2 at 590 px/m, Pmax = 8.81 -> lambda = log2(4.40) = 2.14 -> 66.1 texels/m).
 *
 * CHECKS (a THREE scene built here, no GPU):
 *   [0] the LOD arithmetic above, recomputed: 16.8 and 268.8 texels/m (+-0.1), lambda 4.11 and 0.11 (+-0.01).
 *   [1] prepareFigureTextures(root, 16) on one mesh with map + normalMap + roughnessMap (three distinct textures,
 *       anisotropy 1, each with an image) returns 3 and leaves every one at 16 with version 1 (needsUpdate once).
 *   [2] a second mesh sharing the same map adds nothing: the shared texture counts once (3, not 4).
 *   [3] maxAnisotropy 8 (a weaker GPU) -> 8; maxAnisotropy 64 -> FIGURE_ANISOTROPY = 16 (capped); 0 / NaN -> 1.
 *   [4] a texture already at 16 is never lowered by a call with 4 (returns 0, stays 16, version unchanged).
 *   [5] a texture without an image gets anisotropy 16 but no needsUpdate (version stays 0: three would warn).
 *   [6] Source: Model3DViewer and meshSnapshot call prepareFigureTextures.
 * Before this change (commit 309b0d6fb) `prepareFigureTextures` did not exist — [1] fails there by construction.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_figure_anisotropy_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['node_modules/.bin/esbuild', 'frontend/node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) { console.error('esbuild not found (npm install) — nothing was checked'); process.exit(1) }
    const built = spawnSync(bin, [__filename, '--bundle', '--platform=node', '--format=esm', '--log-level=warning',
      `--outfile=${bundlePath}`], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath, ...process.argv.slice(2)], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root })
    process.exit(run.status ?? 1)
  }
  const THREE = await import('three')
  const { prepareFigureTextures, FIGURE_ANISOTROPY } = await import('../packages/scene-render/src/index.ts')
  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }

  // [0] the docstring's LOD arithmetic
  const lod = (pmax, pmin, maxAniso) => {
    const n = Math.min(Math.ceil(pmax / Math.max(pmin, 1e-9)), maxAniso)
    return Math.max(0, Math.log2(pmax / n))
  }
  const pmax = 5197 / 300; const pmin = 291 / 300
  const l1 = lod(pmax, pmin, 1); const l16 = lod(pmax, pmin, 16)
  const along1 = 291 / 2 ** l1; const along16 = 291 / 2 ** l16
  check('[0] anisotropy 1: lambda 4.11, 16.8 texels/m along the arm',
    Math.abs(l1 - 4.11) < 0.01 && Math.abs(along1 - 16.8) < 0.1, `${l1.toFixed(3)} / ${along1.toFixed(2)}`)
  check('[0] anisotropy 16: lambda 0.11, 268.8 texels/m along the arm',
    Math.abs(l16 - 0.11) < 0.01 && Math.abs(along16 - 268.8) < 0.1, `${l16.toFixed(3)} / ${along16.toFixed(2)}`)

  const img = () => ({ width: 4, height: 4, data: new Uint8Array(64) })
  const tex = (withImage = true) => {
    const t = new THREE.Texture(withImage ? img() : undefined)
    return t
  }
  const geo = new THREE.BufferGeometry()
  const map = tex(); const normalMap = tex(); const roughnessMap = tex()
  const a = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map, normalMap, roughnessMap }))
  const root = new THREE.Group(); root.add(a)
  const n1 = prepareFigureTextures(root, 16)
  const all = [map, normalMap, roughnessMap]
  check('[1] three textures raised to 16, uploaded again once', n1 === 3
    && all.every((t) => t.anisotropy === 16 && t.version === 1), `n=${n1} ${all.map((t) => `${t.anisotropy}/v${t.version}`)}`)

  const root2 = new THREE.Group()
  const map2 = tex(); const nrm2 = tex(); const rgh2 = tex()
  root2.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: map2, normalMap: nrm2, roughnessMap: rgh2 })))
  root2.add(new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ map: map2 })))
  const n2 = prepareFigureTextures(root2, 16)
  check('[2] a shared texture counts once', n2 === 3 && map2.version === 1, `n=${n2} v${map2.version}`)

  const one = (maxAniso) => {
    const t = tex(); const r = new THREE.Group()
    r.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: t })))
    prepareFigureTextures(r, maxAniso)
    return t.anisotropy
  }
  const v8 = one(8); const v64 = one(64); const v0 = one(0); const vNaN = one(NaN)
  check('[3] GPU max 8 -> 8, 64 -> 16 (FIGURE_ANISOTROPY), 0 / NaN -> 1',
    FIGURE_ANISOTROPY === 16 && v8 === 8 && v64 === 16 && v0 === 1 && vNaN === 1, `${v8} ${v64} ${v0} ${vNaN}`)

  const keep = tex(); keep.anisotropy = 16
  const r4 = new THREE.Group(); r4.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: keep })))
  const n4 = prepareFigureTextures(r4, 4)
  check('[4] never lowered', n4 === 0 && keep.anisotropy === 16 && keep.version === 0, `n=${n4} ${keep.anisotropy} v${keep.version}`)

  const bare = tex(false)
  const r5 = new THREE.Group(); r5.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: bare })))
  prepareFigureTextures(r5, 16)
  check('[5] no image: anisotropy set, no needsUpdate', bare.anisotropy === 16 && bare.version === 0,
    `${bare.anisotropy} v${bare.version}`)

  const root6 = process.cwd()   // the bundle runs from /tmp; the run's cwd is the repo root
  const src = (rel) => fs.readFileSync(path.join(root6, rel), 'utf8')
  for (const rel of ['frontend/src/tabs/characters/Model3DViewer.tsx', 'frontend/src/tabs/characters/meshSnapshot.ts']) {
    check(`[6] ${rel} calls prepareFigureTextures`, /prepareFigureTextures\(/.test(src(rel)))
  }

  if (failures.length) {
    console.error(`FAILED: ${failures.length}`)
    process.exit(1)
  }
  console.log('OK')
}

main().catch((e) => { console.error(e); process.exit(1) })
