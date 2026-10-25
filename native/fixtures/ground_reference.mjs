#!/usr/bin/env node
/**
 * Reference values for the native client's ground surfaces (Task S3b), computed by the BROWSER'S OWN
 * FUNCTIONS on the --check fixtures:
 *
 *   packages/scene-render/src/layerCut.ts      packLayerWindow, layerPairAt, layerSdAt, layerSdBlockAt,
 *                                              topLayerAt, lcNoise, lcPushedSd, layerWeight
 *   client3d/src/scene/heightTiles.ts          wantedTiles (the mask tiles' want set, 560 m)
 *   client3d/src/scene/naturalGroundMath.ts    ngTintFactors, ngAoShade, ngFieldUv
 *   three                                       Color (the colour-slice bytes of layerGround.setLayerTable)
 *
 * Inputs (read-only): native/fixtures/terrain_layers.json (index), terrain_layers_tiles.json (tiles),
 * heightfield.json (the AO field header), terrain.json (catalog colours).
 * Output: native/fixtures/ground_reference.json. `Check/GroundCheck.cs` demands its C# port to match
 * (1e-9 for distances/weights/noise, exact for pairs, keys and bytes).
 *
 * Usage (from the repository root, needs `npm install` for three + esbuild):
 *   node native/fixtures/ground_reference.mjs
 * Bundles itself with esbuild like scatter_reference.mjs.
 */
import { spawnSync } from 'child_process'
import * as crypto from 'crypto'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const ROOT = path.join(__dirname, '../../')

/** The fixture anchor (--goto=harbour → loc-house). */
const ANCHOR = [64, 128]
/** Probe points of the near window, with the pixel size in metres the cut is evaluated at. */
const PROBES = [
  [80.3, 99.7, 0.05],     // tile 2,3 uniform forest
  [99.98, 100.2, 0.05],   // tile 3,3, 2 cm west of the hard forest|path line x = 100
  [100.3, 99.1, 0.05],    // tile 3,3, path side
  [100.3, 99.1, 1.0],     // same point, a far-away pixel of 1 m
  [80.4, 138.6, 0.05],    // tile 2,4, soft forest|grass line at z = 139, forest side
  [80.4, 139.3, 0.05],    // tile 2,4, grass side
  [110.0, 170.0, 0.05],   // inside the window, tile 3,5 not delivered → neutral fill
  [98.0, 101.0, 0.05],    // tile 3,3, collapsed texel (forest, forest)
  [139.7, 97.5, 0.05],    // tile 4,3, path side of x = 140
  [140.2, 97.5, 0.05],    // tile 4,3, forest side
  [101.5, 102.0, 0.05],   // tile 3,3, collapsed (path, path)
  [170.0, 100.0, 0.05],   // tile 5,3 uniform lake
  [110.0, 140.0, 0.05],   // tile 3,4 uniform meadow
  [80.5, 159.5, 0.05],    // tile 2,4 collapsed (grass, grass)
]
const AO_CASES = [[1, 0], [0, 1], [5, 0], [0, 0], [0.03515625, 0.0234375]]
const UV_POINTS = [[-255, 128], [64, 128], [-400, 0], [300, 300]]

async function main() {
  if (!process.env.GROUND_REFERENCE_BUNDLED) {
    const bundlePath = '/tmp/anima_native_ground_reference_bundled.mjs'
    const bin = ['client3d/node_modules/.bin/esbuild', 'frontend/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(ROOT, rel)).find((p) => fs.existsSync(p))
    if (!bin) { console.error('esbuild not found (npm install)'); process.exit(1) }
    const built = spawnSync(bin, [__filename, '--bundle', '--platform=node', '--format=esm',
      `--outfile=${bundlePath}`, '--log-level=warning'], { cwd: ROOT, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', cwd: ROOT,
      env: { ...process.env, GROUND_REFERENCE_BUNDLED: '1', GROUND_REFERENCE_ROOT: ROOT },
    })
    process.exit(run.status ?? 1)
  }

  const root = process.env.GROUND_REFERENCE_ROOT
  const LC = await import('../../packages/scene-render/src/layerCut.ts')
  const { wantedTiles } = await import('../../client3d/src/scene/heightTiles.ts')
  const NG = await import('../../client3d/src/scene/naturalGroundMath.ts')
  const THREE = await import('three')
  const read = (f) => JSON.parse(fs.readFileSync(path.join(root, 'native/fixtures', f), 'utf8'))

  const index = read('terrain_layers.json')
  const batch = read('terrain_layers_tiles.json')
  const hf = read('heightfield.json')
  const terrain = read('terrain.json')

  const want = wantedTiles(new Set(index.tile_keys), index.tile_m, ANCHOR[0], ANCHOR[1])
  // refreshLayerTiles: one batch per 16 keys; the server answers only indexed keys — all of them here.
  const tiles = new Map()
  for (const key of want) if (batch.tiles[key]) tiles.set(key, batch.tiles[key])
  const win = LC.packLayerWindow(tiles, index)
  const sha = (u8) => crypto.createHash('sha256').update(Buffer.from(u8)).digest('hex')
  const blendOf = (a) => index.layers[a]?.edge_blend_m ?? 0

  const probes = PROBES.map(([x, z, pixelM]) => {
    const [a, b] = LC.layerPairAt(win, x, z)
    const sdBlock = LC.layerSdBlockAt(win, x, z)
    const blend = blendOf(a)
    const pushed = LC.lcPushedSd(sdBlock, blend, x, z)
    return { x, z, pixelM, a, b, sdRaw: LC.layerSdAt(win, x, z), sdBlock, top: LC.topLayerAt(win, x, z),
             blend, pushed, weight: LC.layerWeight(pushed, blend, pixelM) }
  })

  const tint = PROBES.slice(0, 6).map(([x, z]) => {
    const nB = LC.lcNoise(x / 25, z / 25)
    const nS = LC.lcNoise(x / 25 + 37, z / 25 + 11)
    const f = NG.ngTintFactors(nB, nS)
    return { x, z, nB, nS, brightness: f.brightness, saturation: f.saturation }
  })
  const noise = PROBES.map(([x, z]) => ({ x, z, edge: LC.lcNoise(x / 2 + 5, z / 2 + 23), wide: LC.lcNoise(x / 7, z / 7) }))
  const ao = AO_CASES.map(([ring, own]) => ({ ring, own, shade: NG.ngAoShade(ring, own) }))
  const rows = hf.heights.length
  const cols = hf.heights[0].length
  const field = { origin_x: hf.origin_x, origin_z: hf.origin_z, step_m: hf.step_m, rows, cols }
  const fieldUv = UV_POINTS.map(([x, z]) => ({ x, z, ...NG.ngFieldUv(x, z, field) }))
  const weights = [[0.3, 1.5, 0.05], [-0.75, 1.5, 0.05], [0.75, 1.5, 0.05], [0.01, 0, 0.05], [-0.01, 0, 0.05],
                   [0.2, 0, 1.0], [0.0, 0, 0.0]]
    .map(([sd, blend, fw]) => ({ sd, blend, fw, w: LC.layerWeight(sd, blend, fw) }))

  // setLayerTable's colour slice: new THREE.Color(css) (sRGB hex → linear working space), Math.round(c · 255).
  const colours = {}
  for (const t of terrain.types) {
    if (!t.color) continue
    const c = new THREE.Color(t.color)
    colours[t.color] = [Math.round(c.r * 255), Math.round(c.g * 255), Math.round(c.b * 255)]
  }
  const fallback = new THREE.Color('#888888')
  colours['#888888'] = [Math.round(fallback.r * 255), Math.round(fallback.g * 255), Math.round(fallback.b * 255)]

  const out = {
    anchor: ANCHOR,
    want,
    window: { originX: win.originX, originZ: win.originZ, idStep: win.idStep, sdStep: win.sdStep,
              idSize: win.idSize, sdSize: win.sdSize, sdZero: win.sdZero, sdCodesPerM: win.sdCodesPerM,
              sdBandM: win.sdBandM, idSha256: sha(win.id), sdSha256: sha(win.sd) },
    probes, noise, tint, ao, fieldUv, weights, colours,
  }
  fs.writeFileSync(path.join(root, 'native/fixtures/ground_reference.json'), JSON.stringify(out, null, 1) + '\n')
  console.log(`want=${want.join(';')} window=${win.idSize}/${win.sdSize} @(${win.originX},${win.originZ}) `
    + `probes=${probes.length} colours=${Object.keys(colours).length}`)
  for (const p of probes) {
    console.log(`  (${p.x}, ${p.z}) pair=(${p.a},${p.b}) sd=${p.sdBlock.toFixed(6)} pushed=${p.pushed.toFixed(6)} `
      + `w=${p.weight.toFixed(6)} top=${p.top}`)
  }
  console.log('wrote native/fixtures/ground_reference.json')
}

main().catch((e) => { console.error(e); process.exit(1) })
