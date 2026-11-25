#!/usr/bin/env node
/**
 * Smoke: ONE light for a figure — the 3D client and the Game-Admin model views build the same daylight rig, and
 * figure textures are filtered by `prepareFigureTextures` (figure.ts, its own smoke).
 *
 * Usage: node scripts/smoke_model_light.mjs   (no server, no world; bundles scene-render with esbuild, imports three)
 *
 * WHY (finding 2026-11-20, Glut): the admin viewer had a private rig (ambient 2 + hemisphere 3 + key 3 + fill 1.5
 * + back 1.5, no tone mapping) that put a front face at ~2.3x its albedo — skin glared orange there and looked
 * like skin in the game. And fitted gloves streaked: their UV islands are stretched along the arm, an isotropic
 * mip blurs the print along it.
 *
 * EXPECTED VALUES, by hand from the game client's rig (client3d `engine.ts` + `skyLight.ts` as of 5248c8b3f):
 *   A  daylightIntensities(1) = (sun .25 + 2, hemi .35 + 1.2, fill .15 + .4) = (2.25, 1.55, 0.55);
 *      daylightIntensities(0) = (0.25, 0.35, 0.15). gameHourLights(12) (sunAngle π/2, day = sin(π/2) = 1) gives the
 *      same three numbers and sunAngle π/2; gameHourLights(12).sun is the noon colour 0xfff2d8.
 *   B  sunOffset(π/2) = (cos(π/2)·60, max(.08, 1)·80, 25) = (0, 80, 25); sunOffset(0) = (60, 0.08·80 = 6.4, 25).
 *   C  createDaylightRig: hemi sky 0xdfeeff, ground 0x8a9a78, intensity 1.55; sun 0xfff2d8, 2.25 at (0, 80, 25);
 *      fill 0xdde8ff, 0.55 at (-30, 20, -25).
 *   D  The Lambert factor of a front face (normal +z) at noon, linear, per channel — three's physical lights:
 *      hemisphere, normal horizontal: ½ (sky + ground) · 1.55; sky linear (0.7379, 0.8550, 1.0), ground
 *      (0.2542, 0.3231, 0.1878) -> (0.7688, 0.9131, 0.9205); sun: cos = 25 / √(80² + 25²) = 0.29827,
 *      2.25 · 0.29827 · (1.0, 0.8879, 0.6867) = (0.6711, 0.5959, 0.4609); fill: its direction has z -25 -> cos < 0
 *      -> 0. Sum (1.4399, 1.5090, 1.3814) / π = (0.4584, 0.4803, 0.4397). Re-computed here from the rig's own
 *      lights (colour.r/g/b are linear in three) and compared within 1e-3. The old admin rig: ambient 2 +
 *      hemisphere 3·½(1 + 0.1329) + key 3·3/√14 + fill 1.5·2/3 = 2 + 1.6994 + 2.4054 + 1.0 = 7.1048 -> /π = 2.2615.
 *      (Measured headless 2026-11-20 on a sRGB-128 plane: old 2.33x, new (0.474, 0.496, 0.452) — the hand value
 *      plus the rough specular lobe.)
 *   E  (anisotropy: prepareFigureTextures in figure.ts, guarded by scripts/smoke_figure_anisotropy.mjs)
 *   G  `prepareGlossyPieces(root, env)` (round 2026-11-25): a mesh with three materials — `anima_material`
 *      "leather_glossy" (explicit_metallic false), "metal" (explicit_metallic true), "leather_rough" — and a body
 *      material without userData: it returns 2; the glossy leather gets the env at GLOSSY_ENV_INTENSITY = 0.3 (was 0.5),
 *      the metal at METAL_ENV_INTENSITY = 1.0 (before the round: no env — a metal with no diffuse colour rendered
 *      black between the highlights), the rough leather and the body none. env null -> 0, nothing set.
 *   F  Call sites (source text): Model3DViewer.tsx, meshSnapshot.ts and client3d engine.ts build the lights through
 *      createDaylightRig and construct no AmbientLight / HemisphereLight / DirectionalLight of their own;
 *      Model3DViewer and meshSnapshot call createModelEnvironment, prepareGlossyPieces and prepareFigureTextures;
 *      no `toneMappingExposure` is left in the two admin files.
 */
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function bundle(contents, resolveDir, name) {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-model-light-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents, resolveDir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, name), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, name)
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

const SR = await bundle("export * from '@anima/scene-render';", join(ROOT, 'client3d'), 'sr.mjs')
const SKY = await bundle("export { gameHourLights } from './src/scene/skyLight';", join(ROOT, 'client3d'), 'sky.mjs')
const THREE = await import('three')
let n = 0
const ok = (msg) => { n += 1; console.log('  ok  ', msg) }
const near = (a, b, eps, msg) => assert.ok(Math.abs(a - b) <= eps, `${msg}: ${a} vs ${b}`)

// A
{
  const noon = SR.daylightIntensities(1), night = SR.daylightIntensities(0)
  near(noon.sun, 2.25, 1e-12, 'A noon sun'); near(noon.hemi, 1.55, 1e-12, 'A noon hemi'); near(noon.fill, 0.55, 1e-12, 'A noon fill')
  near(night.sun, 0.25, 1e-12, 'A night sun'); near(night.hemi, 0.35, 1e-12, 'A night hemi'); near(night.fill, 0.15, 1e-12, 'A night fill')
  const L = SKY.gameHourLights(12)
  near(L.sunIntensity, 2.25, 1e-9, 'A clock sun'); near(L.hemiIntensity, 1.55, 1e-9, 'A clock hemi')
  near(L.fillIntensity, 0.55, 1e-9, 'A clock fill'); near(L.sunAngle, Math.PI / 2, 1e-12, 'A clock angle')
  assert.equal(L.sun.getHex(), 0xfff2d8, 'A noon sun colour')
  ok('A intensities per day factor; the clock at noon uses them')
}
// B
{
  const a = SR.sunOffset(Math.PI / 2), b = SR.sunOffset(0)
  near(a[0], 0, 1e-9, 'B noon x'); near(a[1], 80, 1e-12, 'B noon y'); near(a[2], 25, 0, 'B noon z')
  near(b[0], 60, 1e-12, 'B dawn x'); near(b[1], 6.4, 1e-12, 'B dawn y'); near(b[2], 25, 0, 'B dawn z')
  const out = [0, 0, 0]
  assert.equal(SR.sunOffset(1, out), out, 'B writes into out')
  ok('B the sun offset per angle')
}
// C + D
{
  const rig = SR.createDaylightRig(THREE)
  assert.equal(rig.hemi.color.getHex(), 0xdfeeff); assert.equal(rig.hemi.groundColor.getHex(), 0x8a9a78)
  assert.equal(rig.sun.color.getHex(), 0xfff2d8); assert.equal(rig.fill.color.getHex(), 0xdde8ff)
  near(rig.hemi.intensity, 1.55, 1e-12, 'C hemi'); near(rig.sun.intensity, 2.25, 1e-12, 'C sun')
  near(rig.fill.intensity, 0.55, 1e-12, 'C fill')
  assert.deepEqual(rig.fill.position.toArray(), [-30, 20, -25])
  near(rig.sun.position.x, 0, 1e-9, 'C sun x'); near(rig.sun.position.y, 80, 1e-12, 'C sun y')
  ok('C the rig')
  const n_ = new THREE.Vector3(0, 0, 1)
  const want = [0.4584, 0.4803, 0.4397]
  for (const [k, ch] of [[0, 'r'], [1, 'g'], [2, 'b']]) {
    const hemi = 0.5 * (rig.hemi.color[ch] + rig.hemi.groundColor[ch]) * rig.hemi.intensity
    const dir = (l) => Math.max(0, l.position.clone().normalize().dot(n_)) * l.intensity * l.color[ch]
    const f = (hemi + dir(rig.sun) + dir(rig.fill)) / Math.PI
    near(f, want[k], 1e-3, `D front-face factor ${ch}`)
  }
  const old = (2 + 3 * 0.5 * (1 + new THREE.Color(0x666666).r) + 3 * 3 / Math.sqrt(14) + 1.5 * 2 / 3) / Math.PI
  near(old, 2.2615, 1e-3, 'D old admin rig')
  ok('D a front face at noon: (0.458, 0.480, 0.440) x albedo, was 2.26x')
}
// G
{
  near(SR.GLOSSY_ENV_INTENSITY, 0.3, 0, 'G glossy intensity'); near(SR.METAL_ENV_INTENSITY, 1.0, 0, 'G metal intensity')
  const mats = [{ userData: { anima_material: 'leather_glossy', explicit_metallic: false } },
    { userData: { anima_material: 'metal', explicit_metallic: true } },
    { userData: { anima_material: 'leather_rough', explicit_metallic: false } }, { userData: {} }]
  const root = { traverse: (fn) => [{ isMesh: true, material: mats.slice(0, 3) }, { isMesh: true, material: mats[3] }].forEach(fn) }
  assert.equal(SR.prepareGlossyPieces(root, null), 0, 'G no env -> nothing')
  const env = { tag: 'env' }
  assert.equal(SR.prepareGlossyPieces(root, env), 2, 'G two materials set')
  assert.equal(mats[0].envMap, env); near(mats[0].envMapIntensity, 0.3, 0, 'G glossy leather env')
  assert.equal(mats[1].envMap, env); near(mats[1].envMapIntensity, 1.0, 0, 'G metal env')
  assert.equal(mats[2].envMap, undefined, 'G rough leather keeps none'); assert.equal(mats[3].envMap, undefined, 'G body none')
  ok('G glossy leather at 0.3, metal at 1.0, nothing else')
}
// F
{
  const src = async (p) => readFile(join(ROOT, p), 'utf8')
  const viewer = await src('frontend/src/tabs/characters/Model3DViewer.tsx')
  const snap = await src('frontend/src/tabs/characters/meshSnapshot.ts')
  const engine = await src('client3d/src/scene/engine.ts')
  const own = /new THREE\.(AmbientLight|HemisphereLight|DirectionalLight)\(/
  for (const [name, text] of [['Model3DViewer', viewer], ['meshSnapshot', snap], ['engine', engine]]) {
    assert.ok(text.includes('createDaylightRig(THREE)'), `F ${name} builds the shared rig`)
    assert.ok(!own.test(text), `F ${name} builds no light of its own`)
  }
  for (const [name, text] of [['Model3DViewer', viewer], ['meshSnapshot', snap]]) {
    for (const call of ['createModelEnvironment(', 'prepareGlossyPieces(', 'prepareFigureTextures(']) {
      assert.ok(text.includes(call), `F ${name} calls ${call}`)
    }
    assert.ok(!text.includes('toneMappingExposure'), `F ${name}: no dead exposure`)
  }
  assert.ok(engine.includes('createModelEnvironment('), 'F engine environment')
  ok('F call sites')
}
console.log(`${n}/6 checks passed`)
