#!/usr/bin/env node
/**
 * Ruling A193: the mouth channel takes its opening and axis from the MEASURED `mouth` of the collision record (v9),
 * and a channel override's `tilt_deg` turns the axis (`previewChannel`). Every expected number is derived BY HAND
 * below (§ B5a).
 *
 * Usage: node scripts/smoke_mouth_measured.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * [1] mouthChannel with only a Head bone at (0,1.6,0) (L 0.2, f +z, h +y) and mouthO (0,1.57,0.11), mouthB
 *     (0,1.52,0.02): o = mouthO; u = unit(0, −0.05, −0.09) = (0, −0.485643, −0.874157) (|·| 0.102956); D, R stay the
 *     head-length ones: 0.1, 0.02. Without mouthB the formula holds: O (0, 1.63, 0.1), u (0,0,−1).
 * [2] bindChannels on a skinned figure with a Head bone at (0,1.6,0) and the payload's mouth {a mixamorig:Head,
 *     a_pos (0,1.57,0.11), b_pos (0,1.52,0.02)}: at rest the mouth channel is [1]. Head turned +30° about x
 *     (y' = y cos − z sin, z' = y sin + z cos about the head joint): rel O (0, −0.03, 0.11) →
 *     (0, −0.025981 − 0.055, −0.015 + 0.095263) = (0, −0.080981, 0.080263) → O (0, 1.519019, 0.080263);
 *     u → (0, −0.420579 + 0.437079, −0.242822 − 0.757042) = (0, 0.016500, −0.999864): the channel turns with the head.
 * [3] previewChannel: record a_pos (0,1,0.05), b_pos (0,1.13,0.05), frame side (1,0,0), applied null; draft tilt +30
 *     → b_pos = a_pos + (0, 0.13·cos 30°, −0.13·sin 30°) = (0, 1.112583, −0.015). Tilt −30 → (0, 1.112583, 0.115).
 *     From applied tilt 30 to draft 30 → unchanged b_pos.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function load() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-mouth-measured-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: "export * from '@anima/scene-render';", resolveDir: join(ROOT, 'client3d'), loader: 'ts' },
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

const SR = await load()
const THREE = await import(join(ROOT, 'node_modules/three/build/three.module.js'))
let failed = 0
const check = (label, ok, got = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${ok ? '' : `  (got ${got})`}`)
  if (!ok) failed++
}
const near = (a, b, eps) => Math.abs(a - b) <= eps
const vnear = (a, b, eps = 1e-5) => a.length === b.length && a.every((x, i) => near(x, b[i], eps))
const fmt = (v) => `[${v.map((x) => x.toFixed(6)).join(', ')}]`

// [1]
const tb = { head: [0, 1.6, 0], headZ: [0, 0, 1], headY: [0, 1, 0], mouthO: [0, 1.57, 0.11], mouthB: [0, 1.52, 0.02] }
const m = SR.mouthChannel(tb)
check('[1] o = measured', vnear(m.o, [0, 1.57, 0.11]), fmt(m.o))
check('[1] u toward the throat', vnear(m.u, [0, -0.485643, -0.874157]), fmt(m.u))
check('[1] D, R from the head length', near(m.depth, 0.1, 1e-9) && near(m.r, 0.02, 1e-9), `${m.depth} ${m.r}`)
const f = SR.mouthChannel({ head: [0, 1.6, 0], headZ: [0, 0, 1], headY: [0, 1, 0], mouthO: [0, 1.57, 0.11] })
check('[1] without mouthB: the formula', vnear(f.o, [0, 1.63, 0.1]) && vnear(f.u, [0, 0, -1]), fmt(f.o))

// [2]
const root = new THREE.Group()
const hips = new THREE.Bone(); hips.name = 'mixamorig:Hips'; root.add(hips)
const headBone = new THREE.Bone(); headBone.name = 'mixamorig:Head'; headBone.position.set(0, 1.6, 0); hips.add(headBone)
const geo = new THREE.BufferGeometry()
geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 1.6, 0.1, 0, 1.7, 0.1, 0, 1.5, 0.1], 3))
geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
root.add(mesh); root.updateMatrixWorld(true)
mesh.bind(new THREE.Skeleton([hips, headBone]))
const payload = { version: SR.COLLISION_VERSION, capsules: [],
  mouth: { a: 'mixamorig:Head', a_pos: [0, 1.57, 0.11], b_pos: [0, 1.52, 0.02] } }
const bound = SR.bindChannels(THREE, root, payload)
const rest = bound?.channels.at(-1)
check('[2] rest: measured O', !!rest && vnear(rest.o, [0, 1.57, 0.11]), rest && fmt(rest.o))
check('[2] rest: measured u', !!rest && vnear(rest.u, [0, -0.485643, -0.874157]), rest && fmt(rest.u))
headBone.rotation.x = Math.PI / 6; root.updateMatrixWorld(true); bound.update()
const tilt = bound.channels.at(-1)
check('[2] head turned: O follows', vnear(tilt.o, [0, 1.519019, 0.080263]), fmt(tilt.o))
check('[2] head turned: u follows', vnear(tilt.u, [0, 0.0165, -0.999864]), fmt(tilt.u))

// [3]
const rec = { id: 'c', kind: 'channel', a: 'mixamorig:Hips', b: 'mixamorig:Hips', a_pos: [0, 1, 0.05], b_pos: [0, 1.13, 0.05],
  r: 0.035, cone_deg: 30, funnel: 0.05, accepts: [], min_length: 1, compress_min: 0.8, suppress: [],
  frame: { side: [1, 0, 0], up: [0, 1, 0], front: [0, 0, 1] }, placement: 'rig', applied: null }
const d = (tiltDeg) => ({ offset_mm: [0, 0, 0], radius_scale: 1, depth_scale: 1, cone_deg: 30, tilt_deg: tiltDeg })
check('[3] tilt +30 → back', vnear(SR.previewChannel(rec, null, d(30)).b_pos, [0, 1.112583, -0.015]),
  fmt(SR.previewChannel(rec, null, d(30)).b_pos))
check('[3] tilt −30 → front', vnear(SR.previewChannel(rec, null, d(-30)).b_pos, [0, 1.112583, 0.115]))
check('[3] applied 30 → draft 30 unchanged', vnear(SR.previewChannel(rec, d(30), d(30)).b_pos, [0, 1.13, 0.05]))

console.log(failed ? `FAILED (${failed})` : 'ALL OK')
process.exit(failed ? 1 : 0)
