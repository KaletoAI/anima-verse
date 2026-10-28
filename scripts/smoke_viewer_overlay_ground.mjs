#!/usr/bin/env node
/**
 * Smoke run for the GROUND of the admin 3D preview (`Model3DViewer.tsx`,
 * `rebuildOverlay`): the plane, the 1.70 m figure and the W/D/H box stand on
 * the lower edge of the mesh AS RENDERED.
 *
 * Usage:  node scripts/smoke_viewer_overlay_ground.mjs
 *         (plain three from the workspace node_modules; no bundler, no server)
 *
 * THE FINDING (2026-10-28): every Blender-built prop "sank into the floor" of
 * the prop preview. The framing centres the model by moving its pivot
 * (`pivot.position.sub(center)`) and the overlay then measures
 * `Box3.setFromObject(object)` in the same tick. `setFromObject` refreshes
 * the world matrix of `object` only, never of its parents, so the box was
 * taken through the pivot's matrix from BEFORE the move.
 *
 * HAND CASE, the whiteboard (1.8 × 1.2 × 0.1 m, Blender export, origin at
 * the bottom, so the mesh spans y = 0 … 1.2):
 *   - box centre y = 0.6, so the framing moves the pivot to y = −0.6;
 *   - rendered mesh: y = −0.6 … 0.6, lower edge −0.6;
 *   - stale measure: lower edge 0 — the opaque ground disc 0.6 m above the
 *     real lower edge buries half the board;
 *   - an AI mesh is already centred (centre 0), moves by 0 and showed nothing,
 *     which is why only the Blender props were hit.
 * Section [2] pins the fix in the viewer source: the overlay refreshes the
 * preview root's world matrices before it measures.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import * as THREE from 'three'

let failed = 0
const check = (name, ok, detail = '') => {
  console.log(`  ${ok ? '✓' : '✗'} ${name}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failed++
}
const near = (a, b) => Math.abs(a - b) < 1e-6

console.log('[1] the hand case: a bottom-origin mesh after the framing move')
const geo = new THREE.BoxGeometry(1.8, 1.2, 0.1)
geo.translate(0, 0.6, 0)
const object = new THREE.Mesh(geo)
const pivot = new THREE.Group()
pivot.add(object)
const previewRoot = new THREE.Group()
previewRoot.add(pivot)
previewRoot.updateMatrixWorld(true)
const centre = new THREE.Box3().setFromObject(pivot).getCenter(new THREE.Vector3())
check('the framing centre is y = 0.6', near(centre.y, 0.6), String(centre.y))
pivot.position.sub(centre)
const stale = new THREE.Box3().setFromObject(object)
check('measured without a refresh the lower edge stays at 0 (the bug)', near(stale.min.y, 0), String(stale.min.y))
previewRoot.updateMatrixWorld(true)
const fresh = new THREE.Box3().setFromObject(object)
check('after the refresh the lower edge is the rendered −0.6', near(fresh.min.y, -0.6), String(fresh.min.y))

console.log('[2] the viewer refreshes before the overlay measures')
const src = readFileSync(fileURLToPath(new URL('../frontend/src/tabs/characters/Model3DViewer.tsx', import.meta.url)), 'utf8')
const start = src.indexOf('const rebuildOverlay = () => {')
const measure = src.indexOf('const ob = new THREE.Box3().setFromObject(object)', start)
const refresh = src.lastIndexOf('previewRoot.updateMatrixWorld(true)', measure)
check('rebuildOverlay exists and measures the object box', start > 0 && measure > start)
check('previewRoot.updateMatrixWorld(true) runs inside it, before the measure', refresh > start && refresh < measure)

if (failed) {
  console.log(`\nFAILED (${failed})`)
  process.exit(1)
}
console.log('\nALL GREEN')
