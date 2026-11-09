#!/usr/bin/env node
/**
 * Smoke check: a GARMENT mesh in a character GLB does not count toward the
 * figure's height — `figureBox` / `anchorFigureBind` in
 * `packages/scene-render/src/figure.ts`, the routine the 3D client
 * (`client3d/src/scene/figures.ts`: model height, figure anchor) and the
 * admin viewer (`Model3DViewer`: marker figures through `anchorFigureBind`,
 * the dims overlay) measure a figure with. Numbers, not screenshots (§ B5a).
 * Contract: docs/schnittstellen-3d.md § A3a.
 *
 * Usage: node scripts/smoke_figure_height_garment.mjs
 *
 * WHY: since phase 4 of the base-body programme the served character GLB may
 * carry hair as an extra skinned mesh (`garment_<kind>_<item>`, node extras
 * `garment = {kind, item_id, fsig}`). Hair stands over the crown, so a box
 * over the whole model makes a 1.70 m body taller — and every number derived
 * from it (`model.height`, `clipHeightOffsetM`, the procedural gait
 * amplitude, the marker figure's scale) drifts with the haircut.
 *
 * THE CASES, hand-derived (all boxes are axis-aligned, so the bounding box
 * is exact):
 *
 * [1] Body only: BoxGeometry 0.40 × 1.70 × 0.30 lifted by 0.85 → y 0..1.70.
 *     figureBox height = 1.70 = setFromObject height (fast path, same call).
 * [2] Body + a garment marked by `userData.garment` (what GLTFLoader makes of
 *     node extras): a 0.30 × 0.30 × 0.30 box centred at y 1.63 → y
 *     1.48..1.78. setFromObject height = 1.78 (the old measure); figureBox
 *     height = 1.70, min y 0, centre x/z 0.
 * [3] The same garment marked ONLY by its name `garment_hair_hair_kira` (a
 *     pipeline that dropped extras): figureBox height 1.70.
 * [4] A multi-primitive garment: three makes a Group carrying the node's
 *     extras with plain meshes under it. Group extras + an unnamed child box
 *     reaching 1.90 → figureBox height 1.70 (the whole subtree is skipped).
 * [5] The garment hanging BEHIND the body (z −0.40..−0.10, y 1.20..1.78) must
 *     not move the XZ centre: figureBox centre z = 0 (body z −0.15..0.15);
 *     the old box would centre at z = (−0.40 + 0.15) / 2 = −0.125.
 * [6] anchorFigureBind(pivot, 1.70) on body + garment: scale k = 1.70 / 1.70
 *     = 1 (the old measure gave 1.70 / 1.78 = 0.9551), soles on 0.
 * [8] Skinned meshes (what a GLB delivers): body and hair as SkinnedMeshes
 *     bound to one identity bone — old 1.78, figureBox 1.70.
 * [7] Consumers: client3d/src/scene/figures.ts measures its figures with
 *     `figureBox` — no `setFromObject(template)` / `setFromObject(inst)` left.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_figure_height_garment_bundled.mjs'
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

  const { figureBox, anchorFigureBind, isGarmentNode } =
    await import('../packages/scene-render/src/figure.ts')
  const THREE = await import('three')

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps
  const mat = new THREE.MeshBasicMaterial()
  const boxMesh = (w, h, d, x, y, z) => {
    const g = new THREE.BoxGeometry(w, h, d)
    g.translate(x, y, z)
    return new THREE.Mesh(g, mat)
  }
  const body = () => boxMesh(0.4, 1.7, 0.3, 0, 0.85, 0)
  const height = (b) => b.max.y - b.min.y

  // [1]
  {
    const root = new THREE.Group()
    root.add(body())
    const fb = figureBox(THREE, root)
    const old = new THREE.Box3().setFromObject(root)
    check('[1] body only: 1.70', near(height(fb), 1.7), height(fb).toFixed(4))
    check('[1] equals setFromObject', fb.equals(old))
  }
  // [2]
  {
    const root = new THREE.Group()
    root.add(body())
    const hair = boxMesh(0.3, 0.3, 0.3, 0, 1.63, 0)
    hair.userData.garment = { kind: 'hair', item_id: 'hair_kira', fsig: 'abc123def456' }
    root.add(hair)
    const old = new THREE.Box3().setFromObject(root)
    const fb = figureBox(THREE, root)
    check('[2] old measure is 1.78', near(height(old), 1.78), height(old).toFixed(4))
    check('[2] figureBox height 1.70', near(height(fb), 1.7), height(fb).toFixed(4))
    check('[2] min y 0', near(fb.min.y, 0))
    const c = fb.getCenter(new THREE.Vector3())
    check('[2] centre x/z 0', near(c.x, 0) && near(c.z, 0), `${c.x} ${c.z}`)
    check('[2] isGarmentNode(extras)', isGarmentNode(hair) && !isGarmentNode(root.children[0]))
  }
  // [3]
  {
    const root = new THREE.Group()
    root.add(body())
    const hair = boxMesh(0.3, 0.3, 0.3, 0, 1.63, 0)
    hair.name = 'garment_hair_hair_kira'
    root.add(hair)
    const fb = figureBox(THREE, root)
    check('[3] name-only garment: 1.70', near(height(fb), 1.7), height(fb).toFixed(4))
  }
  // [4]
  {
    const root = new THREE.Group()
    root.add(body())
    const node = new THREE.Group()
    node.userData.garment = { kind: 'hair', item_id: 'hair_kira', fsig: 'abc123def456' }
    node.add(boxMesh(0.3, 0.3, 0.3, 0, 1.75, 0))   // y 1.60..1.90
    root.add(node)
    const old = new THREE.Box3().setFromObject(root)
    const fb = figureBox(THREE, root)
    check('[4] old measure is 1.90', near(height(old), 1.9), height(old).toFixed(4))
    check('[4] multi-primitive garment group: 1.70', near(height(fb), 1.7), height(fb).toFixed(4))
  }
  // [5]
  {
    const root = new THREE.Group()
    root.add(body())
    const hair = boxMesh(0.3, 0.58, 0.3, 0, 1.49, -0.25)   // y 1.20..1.78, z -0.40..-0.10
    hair.userData.garment = { kind: 'hair', item_id: 'hair_kira', fsig: 'abc123def456' }
    root.add(hair)
    const old = new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3())
    const c = figureBox(THREE, root).getCenter(new THREE.Vector3())
    check('[5] old centre z -0.125', near(old.z, -0.125), old.z.toFixed(4))
    check('[5] figure centre z 0', near(c.z, 0), c.z.toFixed(4))
  }
  // [6]
  {
    const pivot = new THREE.Group()
    pivot.add(body())
    const hair = boxMesh(0.3, 0.3, 0.3, 0, 1.63, 0)
    hair.userData.garment = { kind: 'hair', item_id: 'hair_kira', fsig: 'abc123def456' }
    pivot.add(hair)
    const k = anchorFigureBind(THREE, pivot, 1.7)
    check('[6] anchor scale 1 (old 0.9551)', near(k, 1), k.toFixed(4))
    pivot.updateMatrixWorld(true)
    const after = figureBox(THREE, pivot)
    check('[6] soles on 0, figure 1.70', near(after.min.y, 0) && near(height(after), 1.7),
      `${after.min.y.toFixed(4)} ${height(after).toFixed(4)}`)
  }
  // [8] What a real GLB holds: body AND hair are SkinnedMeshes on one
  //     skeleton (one identity bone, every weight on it). The skinned path
  //     measures the mesh's OWN box (`SkinnedMesh.boundingBox`): body 1.70.
  {
    const bone = new THREE.Bone()
    const skinned = (w, h, d, y) => {
      const g = new THREE.BoxGeometry(w, h, d)
      g.translate(0, y, 0)
      const n = g.getAttribute('position').count
      g.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Array(n * 4).fill(0), 4))
      g.setAttribute('skinWeight', new THREE.Float32BufferAttribute(
        Array.from({ length: n * 4 }, (_, i) => (i % 4 === 0 ? 1 : 0)), 4))
      const m = new THREE.SkinnedMesh(g, mat)
      return m
    }
    const root = new THREE.Group()
    root.add(bone)
    const skeleton = new THREE.Skeleton([bone])
    const b = skinned(0.4, 1.7, 0.3, 0.85)
    const hair = skinned(0.3, 0.3, 0.3, 1.63)
    hair.name = 'garment_hair_hair_kira'
    hair.userData.garment = { kind: 'hair', item_id: 'hair_kira', fsig: 'abc123def456' }
    root.add(b, hair)
    root.updateMatrixWorld(true)
    b.bind(skeleton)
    hair.bind(skeleton)
    const old = new THREE.Box3().setFromObject(root)
    const fb = figureBox(THREE, root)
    check('[8] skinned: old 1.78, figure 1.70', near(height(old), 1.78, 1e-5) && near(height(fb), 1.7, 1e-5),
      `${height(old).toFixed(4)} ${height(fb).toFixed(4)}`)
  }
  // [7]
  {
    const src = fs.readFileSync(path.join(process.cwd(), 'client3d/src/scene/figures.ts'), 'utf8')
    const left = src.match(/setFromObject\((template|inst)\)/g) || []
    check('[7] figures.ts measures with figureBox', left.length === 0 && /figureBox\(THREE, template\)/.test(src)
      && /figureBox\(THREE, inst\)/.test(src), left.join(', '))
  }

  if (failures.length) {
    console.log(`FAILED: ${failures.length} — ${failures.join('; ')}`)
    process.exit(1)
  }
  console.log('ALL OK')
}

main().catch((e) => { console.error(e); process.exit(1) })
