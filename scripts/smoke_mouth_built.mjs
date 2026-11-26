#!/usr/bin/env node
/**
 * Ruling A203: a model whose mouth channel was BUILT carries it as a declared channel with the mouth's id; the
 * renderers then take that one as the figure's mouth and add no head-bone mouth beside it. Numbers by hand (§ B5a).
 *
 * Usage: node scripts/smoke_mouth_built.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE: a skinned figure with a Head bone at (0, 1.6, 0) (three vertices, all on the head joint) and a payload
 * with the measured mouth {a_pos (0, 1.57, 0.11), b_pos (0, 1.52, 0.02)}.
 * [1] Without a built channel the figure has ONE channel, the head-bone mouth: id "mouth", O the measured
 *     (0, 1.57, 0.11), depth 0.5 x 0.2 = 0.1, r 0.1 x 0.2 = 0.02.
 * [2] With the built channel {id "mouth", a = b = Head, a_pos (0, 1.57, 0.11), b_pos = a_pos + (0, -0.6, -0.8) x
 *     0.08 = (0, 1.522, 0.046), r 0.025, cone 35, funnel 0.03, min_length 0, compress_min 0.6, suppress [head]}:
 *     still ONE channel with id "mouth", and it is the built one — depth 0.08 (not 0.1), r 0.025 (not 0.02),
 *     u (0, -0.6, -0.8), funnel 0.03, minLength 0, compressMin 0.6, suppress {head}.
 * [3] Head turned +30 degrees about x (as in smoke_mouth_measured [2]): the built opening follows the head —
 *     rel O (0, -0.03, 0.11) -> (0, -0.080981, 0.080263) -> O (0, 1.519019, 0.080263); the depth stays 0.08.
 * [4] findContact-style ids: MOUTH_CHANNEL_ID is "mouth".
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function load() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-mouth-built-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: "export * from '@anima/scene-render';", resolveDir: ROOT, loader: 'ts' },
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

// fixture
const make = () => {
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
  return { root, headBone }
}
const mouth = { a: 'mixamorig:Head', a_pos: [0, 1.57, 0.11], b_pos: [0, 1.52, 0.02] }
const built = { id: 'mouth', kind: 'channel', a: 'mixamorig:Head', b: 'mixamorig:Head', a_pos: [0, 1.57, 0.11],
  b_pos: [0, 1.522, 0.046], r: 0.025, cone_deg: 35, funnel: 0.03, accepts: ['attached_part', 'appendage_chain'],
  min_length: 0, compress_min: 0.6, suppress: ['head'], frame: { side: [1, 0, 0], up: [0, 1, 0], front: [0, 0, 1] },
  placement: 'rig', applied: null }

// [1]
let f = make()
let bound = SR.bindChannels(THREE, f.root, { version: SR.COLLISION_VERSION, capsules: [], mouth })
check('[1] one channel, the head-bone mouth', bound?.channels.length === 1 && bound.channels[0].id === 'mouth',
  bound && bound.channels.map((c) => c.id).join(','))
check('[1] depth 0.1, r 0.02', near(bound.channels[0].depth, 0.1, 1e-9) && near(bound.channels[0].r, 0.02, 1e-9),
  `${bound.channels[0].depth} ${bound.channels[0].r}`)

// [2]
f = make()
bound = SR.bindChannels(THREE, f.root, { version: SR.COLLISION_VERSION, capsules: [], mouth, channels: [built] })
const c = bound?.channels[0]
check('[2] still one channel with the mouth id', bound?.channels.length === 1 && c.id === 'mouth',
  bound && bound.channels.map((x) => x.id).join(','))
check('[2] the built depth and radius', near(c.depth, 0.08, 1e-6) && near(c.r, 0.025, 1e-9), `${c.depth} ${c.r}`)
check('[2] the built axis', vnear(c.u, [0, -0.6, -0.8]), fmt(c.u))
check('[2] O at the built opening', vnear(c.o, [0, 1.57, 0.11]), fmt(c.o))
check('[2] gates of the built record', near(c.funnel, 0.03, 1e-9) && c.minLength === 0 && c.compressMin === 0.6
  && c.suppress.has('head') && c.coneDeg === 35, JSON.stringify({ f: c.funnel, m: c.minLength, k: c.compressMin }))

// [3]
f.headBone.rotation.x = Math.PI / 6; f.root.updateMatrixWorld(true); bound.update()
const t = bound.channels[0]
check('[3] head turned: the built opening follows', vnear(t.o, [0, 1.519019, 0.080263]), fmt(t.o))
check('[3] head turned: depth stays 0.08, one channel', near(t.depth, 0.08, 1e-6) && bound.channels.length === 1, `${t.depth}`)

// [4]
check('[4] MOUTH_CHANNEL_ID', SR.MOUTH_CHANNEL_ID === 'mouth', SR.MOUTH_CHANNEL_ID)

console.log(failed ? `FAILED (${failed})` : 'ALL OK')
process.exit(failed ? 1 : 0)
